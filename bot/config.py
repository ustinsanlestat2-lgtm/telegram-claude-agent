"""
Loads and validates configuration from environment variables.
All secrets are expected to be injected at process start (systemd EnvironmentFile,
or `export`'d before running manually) ? never hardcoded here.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


@dataclass
class Config:
    telegram_bot_token: str
    allowed_telegram_user_ids: set[int]
    github_token: str
    github_org: str
    repos: list[str]                # repo names under github_org the agent may touch
    workdir: Path                   # e.g. /srv/agent/repos
    claude_binary: str = "claude"
    max_turns: int = 40
    job_timeout_seconds: int = 1800  # 30 min per job, hard cap
    agent_config_path: Path = Path("/srv/agent/config/CLAUDE.md")


def load_config() -> Config:
    allowed_ids_raw = _require("TELEGRAM_ALLOWED_USER_IDS")
    allowed_ids = {int(x.strip()) for x in allowed_ids_raw.split(",") if x.strip()}

    repos_raw = _require("AGENT_REPOS")
    repos = [r.strip() for r in repos_raw.split(",") if r.strip()]

    return Config(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        allowed_telegram_user_ids=allowed_ids,
        github_token=_require("GITHUB_TOKEN"),
        github_org=_require("GITHUB_ORG"),
        repos=repos,
        workdir=Path(os.environ.get("AGENT_WORKDIR", "/srv/agent/repos")),
        claude_binary=os.environ.get("CLAUDE_BINARY", "claude"),
        max_turns=int(os.environ.get("AGENT_MAX_TURNS", "40")),
        job_timeout_seconds=int(os.environ.get("AGENT_JOB_TIMEOUT_SECONDS", "1800")),
        agent_config_path=Path(
            os.environ.get("AGENT_CONFIG_PATH", "/srv/agent/config/CLAUDE.md")
        ),
    )