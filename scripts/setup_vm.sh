#!/usr/bin/env bash
# Run this ON the GCP VM (after SSHing in via IAP) to provision everything the
# bot needs: Node (for the Claude Code CLI), Python venv, gh CLI, and a
# non-root service user.
set -euo pipefail

# ---- EDIT THIS ----
AGENT_REPO_URL="<YOUR_MAIN_AGENT_REPO_URL>"   # e.g. https://github.com/your-org/telegram-claude-agent.git
# -------------------

echo "== Updating system packages =="
sudo apt-get update -y
sudo apt-get upgrade -y

echo "== Installing base tools =="
sudo apt-get install -y curl git build-essential python3 python3-venv python3-pip

echo "== Installing Node.js 20 =="
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

echo "== Installing Claude Code CLI =="
sudo npm install -g @anthropic-ai/claude-code

echo "== Installing GitHub CLI (gh) =="
type -p curl >/dev/null
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt-get update -y
sudo apt-get install -y gh

echo "== Creating service user 'agent' =="
if ! id agent &>/dev/null; then
  sudo useradd -m -s /bin/bash agent
fi

echo "== Creating working directories =="
sudo mkdir -p /srv/agent/repos
sudo chown -R agent:agent /srv/agent

echo "== Cloning the main agent repo (bot code + CLAUDE.md) =="
sudo -u agent git clone "$AGENT_REPO_URL" /srv/agent/app || \
  (cd /srv/agent/app && sudo -u agent git pull)

echo "== Setting up Python venv for the bot =="
sudo -u agent python3 -m venv /srv/agent/app/.venv
sudo -u agent /srv/agent/app/.venv/bin/pip install --upgrade pip
sudo -u agent /srv/agent/app/.venv/bin/pip install -r /srv/agent/app/requirements.txt

echo
echo "== Provisioning done =="
echo "Next steps (see README.md):"
echo "  1. Generate a fine-grained GitHub PAT and put it in /etc/agent-bot.env"
echo "  2. Run 'claude setup-token' on your LAPTOP and copy the token into /etc/agent-bot.env"
echo "  3. Copy this repo's .env.example to /etc/agent-bot.env and fill in every value"
echo "  4. sudo cp systemd/agent-bot.service /etc/systemd/system/"
echo "  5. sudo systemctl daemon-reload && sudo systemctl enable --now agent-bot"
