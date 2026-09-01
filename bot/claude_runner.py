"""
Invokes headless Claude Code (`claude -p`) as a subprocess against a prepared
worktree, streams its stream-json output, and extracts a short summary plus
(if produced) a PR URL to relay back to Telegram.
"""
import asyncio
import json
import re
from pathlib import Path
from typing import AsyncIterator

from config import Config

PR_URL_RE = re.compile(r"https://github\.com/[^\s\"']+/pull/\d+")


def build_prompt(repo: str, issue_number: int) -> str:
    return (
        f"Resolve GitHub issue #{issue_number} in this repository. "
        f"Start by running `gh issue view {issue_number}` to read the issue text and "
        f"any comments. Implement a fix on the current branch, run the project's tests "
        f"and linters if they exist, commit your work, and open a pull request with "
        f"`gh pr create` that closes the issue. Follow the working rules you were given "
        f"for all working rules. "
        f"If anything is ambiguous or risky per those stop-and-ask conditions, "
        f"stop and explain what decision you need instead of guessing."
    )


async def run_job(
    cfg: Config, worktree: Path, repo: str, issue_number: int
) -> AsyncIterator[str]:
    """Runs claude -p in the worktree, yielding progress lines as they arrive,
    and a final line prefixed with RESULT: containing the summary."""
    prompt = build_prompt(repo, issue_number)

    try:
        agent_instructions = cfg.agent_config_path.read_text(encoding="utf-8")
    except OSError as e:
        yield (
            f"RESULT:? Could not read agent config at {cfg.agent_config_path}: {e}. "
            f"Has the coding-agent deploy workflow run yet?"
        )
        return

    cmd = [
        cfg.claude_binary,
        "-p", prompt,
        "--append-system-prompt", agent_instructions,
        "--output-format", "stream-json",
        "--verbose",
        "--allowedTools", "Read,Edit,Bash,Write",
        "--permission-mode", "acceptEdits",
        "--max-turns", str(cfg.max_turns),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(worktree),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    last_text = ""
    pr_url = None

    async def _read_stdout():
        nonlocal last_text, pr_url
        assert proc.stdout is not None
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # stream-json emits various event types; surface assistant text deltas
            # and tool-use summaries as lightweight progress pings.
            etype = event.get("type")
            if etype == "assistant":
                content = event.get("message", {}).get("content", [])
                for block in content:
                    if block.get("type") == "text":
                        last_text = block["text"]
                        found = PR_URL_RE.search(last_text)
                        if found:
                            pr_url = found.group(0)
                        yield f"?{last_text[-300:]}"
            elif etype == "result":
                result_text = event.get("result", "")
                if result_text:
                    last_text = result_text
                    found = PR_URL_RE.search(result_text)
                    if found:
                        pr_url = found.group(0)

    try:
        async with asyncio.timeout(cfg.job_timeout_seconds):
            async for progress in _read_stdout():
                yield progress
            await proc.wait()
    except asyncio.TimeoutError:
        proc.kill()
        yield f"RESULT:?? Job timed out after {cfg.job_timeout_seconds}s and was killed."
        return

    stderr = (await proc.stderr.read()).decode("utf-8", errors="replace") if proc.stderr else ""
    if proc.returncode != 0:
        yield f"RESULT:? claude exited with code {proc.returncode}.\n{stderr[-500:]}"
        return

    summary = last_text[-800:] if last_text else "(no summary produced)"
    if pr_url:
        yield f"RESULT:? {summary}\n\nPR: {pr_url}"
    else:
        yield f"RESULT:?? Finished, but no PR URL was detected. Check the branch manually.\n\n{summary}"