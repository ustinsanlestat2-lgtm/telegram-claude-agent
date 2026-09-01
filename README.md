# Telegram → Claude Code agent, step by step

This repo is the "main agent repository": it holds the Telegram bot that receives your
messages, the orchestration code that checks out a git worktree per issue and runs Claude
Code headlessly against it, and `CLAUDE.md`, which is read by the agent on every job and
sets its working rules (branching, PR discipline, when to stop and ask you).

Architecture:

```
Telegram  →  bot.py (long polling)  →  job queue  →  claude -p (headless)  →  git/GitHub
```

Auth: GitHub access uses a fine-grained Personal Access Token (PAT), scoped to just the
repos the agent should touch. Claude Code auth uses your Pro/Max subscription via
`claude setup-token` (an OAuth token), not a pay-per-token API key — see step 5 for why that
matters and how it works.

---

## 0. Prerequisites

- A GCP project with billing enabled and the `gcloud` CLI installed on your laptop.
- A GitHub org you're an owner/admin of, with the repos you want the agent to work on.
- A Telegram account.
- A Claude Pro or Max subscription (for `claude setup-token`).

---

## 1. Push this repo to your GitHub org

This repo is the thing the VM will clone to get the bot code and `CLAUDE.md`. Push it
somewhere the agent VM can reach, e.g. `https://github.com/<your-org>/telegram-claude-agent`.

```bash
cd telegram-claude-agent
git init
git add .
git commit -m "Initial agent bot setup"
git remote add origin https://github.com/<your-org>/telegram-claude-agent.git
git push -u origin main
```

`CLAUDE.md` in this repo is what you'll iterate on most over time — it's read on every job.

---

## 2. Create a fine-grained GitHub PAT

1. GitHub → your avatar → **Settings** → **Developer settings** → **Personal access tokens**
   → **Fine-grained tokens** → **Generate new token**.
2. **Resource owner**: your org.
3. **Repository access**: "Only select repositories" → pick exactly the repos the agent
   should be able to touch (keep this list tight — it should match `AGENT_REPOS` later).
4. **Permissions** → Repository permissions:
   - Contents: Read and write
   - Issues: Read and write
   - Pull requests: Read and write
   - Metadata: Read-only (auto-selected)
5. **Expiration**: set one (e.g. 90 days or 1 year). Fine-grained tokens can't be set to
   never expire when scoped this way in most orgs — that's a good thing. Put a calendar
   reminder to rotate it before it lapses.
6. Generate, and **copy the token now** (`github_pat_...`) — you won't see it again.

If your org requires approval for fine-grained tokens, an org owner will need to approve
the request before it becomes active.

---

## 3. Create the GCP VM

From your laptop, with `gcloud` authenticated and pointed at the right project:

```bash
chmod +x scripts/create_gcp_instance.sh
# edit PROJECT_ID inside the script first
./scripts/create_gcp_instance.sh
```

This creates a small VM (`e2-small`) with **no public IP**. You'll always reach it through
IAP tunneling, so there's no open SSH port to the internet:

```bash
gcloud compute ssh agent-bot --zone=us-central1-a --tunnel-through-iap
```

---

## 4. Provision the VM

SSH in (command above), then from your laptop copy this repo's URL into the script and run
it on the VM:

```bash
# on the VM
curl -fsSL https://raw.githubusercontent.com/<your-org>/telegram-claude-agent/main/scripts/setup_vm.sh -o setup_vm.sh
# or: scp the whole repo up, or just clone it once git/curl are available
chmod +x setup_vm.sh
./setup_vm.sh
```

This installs Node, the `claude` CLI, Python + venv, the `gh` CLI, creates a non-root
`agent` service user, and clones this repo to `/srv/agent/app`.

---

## 5. Authenticate Claude Code (OAuth token, not an API key)

Do this part **on your laptop**, not the VM — it needs a browser for the OAuth flow:

```bash
claude setup-token
```

Follow the browser prompt. It prints a long-lived token that looks like
`sk-ant-oat01-...` (valid roughly a year, tied to your Pro/Max subscription quota rather
than metered API billing).

Why OAuth token and not `ANTHROPIC_API_KEY` here: you're invoking the `claude` CLI itself
as a subprocess (`claude -p ...`) — that's still "Claude Code," so subscription auth is the
supported path. (If you ever rewrite this to use the Claude Agent SDK library directly
instead of shelling out to the CLI, that's a different product surface and should use an
API key instead — not the case for this setup.)

Copy the printed token — you'll paste it into `/etc/agent-bot.env` in the next step.

One thing worth a quick sanity check once it's on the VM: some CLI versions have been
reported to want API credits even with a valid OAuth token in `-p` mode. Test it (step 8)
before assuming it's wired correctly.

---

## 6. Create your Telegram bot

1. Message **@BotFather** on Telegram → `/newbot` → follow the prompts → copy the bot
   token (`123456789:AA...`).
2. Message **@userinfobot** to get your own numeric Telegram user ID — this is what
   restricts the bot to only you.

---

## 7. Fill in the environment file (on the VM)

```bash
sudo cp /srv/agent/app/.env.example /etc/agent-bot.env
sudo chmod 600 /etc/agent-bot.env
sudo chown agent:agent /etc/agent-bot.env
sudo nano /etc/agent-bot.env
```

Fill in every value:

- `TELEGRAM_BOT_TOKEN` — from BotFather (step 6)
- `TELEGRAM_ALLOWED_USER_IDS` — your Telegram user ID (step 6), comma-separated if more
  than one person should be able to use it
- `GITHUB_TOKEN` — the fine-grained PAT (step 2)
- `GITHUB_ORG` — your org name
- `AGENT_REPOS` — comma-separated repo names the agent may touch (must match the PAT's
  repo scope from step 2)
- `CLAUDE_CODE_OAUTH_TOKEN` — from `claude setup-token` (step 5)

Then authenticate `gh` as the `agent` user so headless Claude can read issues and open PRs:

```bash
sudo -u agent bash -c '
  source /etc/agent-bot.env
  echo "$GITHUB_TOKEN" | gh auth login --with-token
  git config --global user.name "agent-bot"
  git config --global user.email "agent-bot@your-org.example"
'
```

---

## 8. Smoke-test Claude Code on the VM before wiring up the bot

```bash
sudo -u agent bash -c '
  source /etc/agent-bot.env
  export CLAUDE_CODE_OAUTH_TOKEN
  claude -p "hello" --output-format json
'
```

You should get a JSON response back with no auth errors. If it complains about missing API
credits despite the OAuth token being set, stop here and check your Claude Code CLI version
(`claude --version`) — update it (`sudo npm update -g @anthropic-ai/claude-code`) before
continuing.

---

## 9. Install and start the systemd service

```bash
sudo cp /srv/agent/app/systemd/agent-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agent-bot
sudo systemctl status agent-bot
journalctl -u agent-bot -f   # watch logs
```

`Restart=on-failure` means the bot comes back up automatically if it crashes or the VM
reboots.

---

## 10. Try it from Telegram

Message your bot:

```
/repos
/work backend 482
/status
```

`/work backend 482` will:

1. Check out (or reuse) a worktree at `/srv/agent/repos/<org>/backend-issue-482` on branch
   `agent/issue-482`.
2. Run `claude -p` headlessly in that worktree, with `CLAUDE.md`'s rules in effect.
3. Post the final result — a PR link, or a question if the agent hit a stop-and-ask
   condition — back to your chat.

---

## Safety rails already in place

- Bot only responds to the Telegram user IDs you listed.
- PAT is scoped to specific repos only, with an expiration date.
- Agent never pushes to `main`/`master` — always a branch + PR; you merge.
- `--max-turns` caps a confused run instead of letting it loop forever.
- `AGENT_JOB_TIMEOUT_SECONDS` hard-kills a stuck job.
- VM has no public IP; you reach it only via IAP tunneling.
- Secrets live in `/etc/agent-bot.env` (mode 600), never in `CLAUDE.md`, prompts, git
  history, or logs.
- One job runs at a time (simple queue) — avoids parallel `claude` processes racing on
  the same subscription rate limit.

## Iterating

- **Repo conventions, review requirements, extra guardrails** → edit `CLAUDE.md`, commit,
  push, then `git pull` on the VM (or re-run `setup_vm.sh`'s clone step) — no restart
  needed, it's read fresh on every job.
- **Bot behavior (commands, queueing, message formatting)** → edit files under `bot/`,
  push, pull on the VM, `sudo systemctl restart agent-bot`.
- **Rotating the PAT** → generate a new one before the old one expires, update
  `GITHUB_TOKEN` in `/etc/agent-bot.env`, re-run the `gh auth login --with-token` step,
  `sudo systemctl restart agent-bot`.
- **Adding a repo** → add it to `AGENT_REPOS` in `/etc/agent-bot.env` *and* to the PAT's
  repository access list on GitHub, then restart the service.

## Later upgrade path

If you outgrow a single PAT (e.g. you want short-lived, per-repo, or org-wide tokens with
a tighter audit trail), a GitHub App with installation-token refresh is a reasonable next
step — it's more setup than a PAT but doesn't require rotating a long-lived secret by hand.
Not needed to get started.
