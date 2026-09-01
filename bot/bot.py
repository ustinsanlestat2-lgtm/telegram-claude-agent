"""
Telegram <-> Claude Code bridge.

Commands:
    /repos                      - list repos this agent is allowed to touch
    /work <repo> <issue_number> - queue a job: check out a worktree for the issue
                                   and run Claude Code headlessly against it
    /status                     - show what's currently running / queued
    /cancel                     - cancel the currently running job

Only Telegram user IDs listed in TELEGRAM_ALLOWED_USER_IDS may interact with the bot;
everyone else is silently ignored (with a log line).
"""
import asyncio
import logging
from dataclasses import dataclass

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from config import load_config, Config
from git_ops import create_issue_worktree, ensure_home_clone
from claude_runner import run_job

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("agent-bot")


@dataclass
class Job:
    repo: str
    issue_number: int
    chat_id: int


class JobRunner:
    """Single-worker queue: one job runs at a time, others wait. Keeps this simple
    and avoids multiple `claude` processes fighting over the same OAuth rate limit."""

    def __init__(self, cfg: Config, app: Application):
        self.cfg = cfg
        self.app = app
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.current: Job | None = None
        self._task: asyncio.Task | None = None

    def start(self):
        self._task = asyncio.create_task(self._worker_loop())

    async def enqueue(self, job: Job):
        await self.queue.put(job)

    async def _worker_loop(self):
        while True:
            job = await self.queue.get()
            self.current = job
            try:
                await self._run(job)
            except Exception:
                log.exception("Job failed: %s#%s", job.repo, job.issue_number)
                await self.app.bot.send_message(
                    job.chat_id,
                    f"❌ Internal error running {job.repo}#{job.issue_number}. Check server logs.",
                )
            finally:
                self.current = None
                self.queue.task_done()

    async def _run(self, job: Job):
        bot = self.app.bot
        await bot.send_message(
            job.chat_id, f"🔧 Starting {job.repo}#{job.issue_number}…"
        )

        worktree = create_issue_worktree(self.cfg, job.repo, job.issue_number)

        last_sent = ""
        async for update in run_job(self.cfg, worktree, job.repo, job.issue_number):
            if update.startswith("RESULT:"):
                await bot.send_message(job.chat_id, update[len("RESULT:"):])
            else:
                # Throttle progress pings so we don't spam the chat.
                if update != last_sent:
                    last_sent = update
                    # Comment out the next line if progress pings are too noisy;
                    # a silent run that only posts the final RESULT is also fine.
                    # await bot.send_message(job.chat_id, update)
                    pass


def _is_allowed(cfg: Config, update: Update) -> bool:
    user = update.effective_user
    if user is None or user.id not in cfg.allowed_telegram_user_ids:
        log.warning("Rejected message from unauthorized user: %s", user)
        return False
    return True


async def cmd_repos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg: Config = context.bot_data["cfg"]
    if not _is_allowed(cfg, update):
        return
    await update.message.reply_text(
        "Repos this agent can touch:\n" + "\n".join(f"- {r}" for r in cfg.repos)
    )


async def cmd_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg: Config = context.bot_data["cfg"]
    runner: JobRunner = context.bot_data["runner"]
    if not _is_allowed(cfg, update):
        return

    args = context.args or []
    if len(args) != 2 or not args[1].isdigit():
        await update.message.reply_text("Usage: /work <repo> <issue_number>")
        return

    repo, issue_number = args[0], int(args[1])
    if repo not in cfg.repos:
        await update.message.reply_text(
            f"'{repo}' isn't in the allowed repo list. See /repos."
        )
        return

    job = Job(repo=repo, issue_number=issue_number, chat_id=update.effective_chat.id)
    await runner.enqueue(job)
    await update.message.reply_text(
        f"Queued {repo}#{issue_number} (position {runner.queue.qsize()})."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg: Config = context.bot_data["cfg"]
    runner: JobRunner = context.bot_data["runner"]
    if not _is_allowed(cfg, update):
        return

    if runner.current:
        msg = f"Running: {runner.current.repo}#{runner.current.issue_number}"
    else:
        msg = "Idle."
    msg += f"\nQueued: {runner.queue.qsize()}"
    await update.message.reply_text(msg)


def main():
    cfg = load_config()

    for repo in cfg.repos:
        log.info("Priming clone for %s...", repo)
        ensure_home_clone(cfg, repo)

    app = Application.builder().token(cfg.telegram_bot_token).build()
    app.bot_data["cfg"] = cfg

    runner = JobRunner(cfg, app)
    app.bot_data["runner"] = runner

    app.add_handler(CommandHandler("repos", cmd_repos))
    app.add_handler(CommandHandler("work", cmd_work))
    app.add_handler(CommandHandler("status", cmd_status))

    async def _post_init(application: Application):
        runner.start()

    app.post_init = _post_init

    log.info("Starting bot (long polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
