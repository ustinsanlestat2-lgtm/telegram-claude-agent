"""
Per-issue git worktree management, so multiple jobs on the same repo never collide.

Layout on disk:
    <workdir>/<org>/<repo>            <- bare-ish "home" clone, holds .git
    <workdir>/<org>/<repo>-issue-123  <- worktree checked out on branch agent/issue-123
"""
import subprocess
from pathlib import Path

from config import Config


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


def repo_url(cfg: Config, repo: str) -> str:
    # Fine-grained PAT used as bearer token in the HTTPS clone URL.
    return f"https://x-access-token:{cfg.github_token}@github.com/{cfg.github_org}/{repo}.git"


def ensure_home_clone(cfg: Config, repo: str) -> Path:
    home = cfg.workdir / cfg.github_org / repo
    if not home.exists():
        home.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", repo_url(cfg, repo), str(home)])
    else:
        _run(["git", "fetch", "origin"], cwd=home)
    return home


def create_issue_worktree(cfg: Config, repo: str, issue_number: int) -> Path:
    home = ensure_home_clone(cfg, repo)
    branch = f"agent/issue-{issue_number}"
    worktree_path = cfg.workdir / cfg.github_org / f"{repo}-issue-{issue_number}"

    if worktree_path.exists():
        # Reuse: reset to latest default branch tip on the existing branch.
        return worktree_path

    default_branch = _run(
        ["git", "remote", "show", "origin"], cwd=home
    )
    head_line = [l for l in default_branch.splitlines() if "HEAD branch" in l]
    base = head_line[0].split(":")[-1].strip() if head_line else "main"

    _run(["git", "fetch", "origin", base], cwd=home)
    _run(
        [
            "git", "worktree", "add", str(worktree_path),
            "-b", branch, f"origin/{base}",
        ],
        cwd=home,
    )
    return worktree_path


def remove_issue_worktree(cfg: Config, repo: str, issue_number: int) -> None:
    home = cfg.workdir / cfg.github_org / repo
    worktree_path = cfg.workdir / cfg.github_org / f"{repo}-issue-{issue_number}"
    if worktree_path.exists() and home.exists():
        _run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=home)
