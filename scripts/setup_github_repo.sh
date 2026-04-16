#!/usr/bin/env bash
# Створює репозиторій c55bot-web/<REPO>, додає origin і пушить main.
# Потрібен GitHub Personal Access Token (classic) з scope "repo" або fine-grained з доступом до репозиторіїв.
#
# Варіант A (одноразово):  GITHUB_TOKEN=ghp_xxxx bash scripts/setup_github_repo.sh
# Варіант B: echo 'ghp_xxxx' > ~/.config/c55_github_token && chmod 600 ~/.config/c55_github_token && bash scripts/setup_github_repo.sh
#
# Інше ім’я репо:  GITHUB_REPO_NAME=my_repo bash scripts/setup_github_repo.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REPO_NAME="${GITHUB_REPO_NAME:-c55_bot}"
OWNER="${GITHUB_OWNER:-c55bot-web}"
TOKEN_FILE="${GITHUB_TOKEN_FILE:-$HOME/.config/c55_github_token}"

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [[ -z "$TOKEN" && -f "$TOKEN_FILE" ]]; then
  TOKEN="$(tr -d ' \n\r\t' < "$TOKEN_FILE")"
fi
if [[ -z "$TOKEN" ]]; then
  echo "Немає токена."
  echo "1) GitHub → Settings → Developer settings → Personal access tokens → Generate (classic), увімкніть scope: repo"
  echo "2) Запустіть:  GITHUB_TOKEN=ghp_... bash scripts/setup_github_repo.sh"
  echo "   або збережіть токен у $TOKEN_FILE (chmod 600)"
  exit 1
fi

export GH_TOKEN="$TOKEN"
printf '%s\n' "$GH_TOKEN" | gh auth login --hostname github.com --with-token
gh auth status

REMOTE_URL="git@github.com:${OWNER}/${REPO_NAME}.git"

if gh repo view "${OWNER}/${REPO_NAME}" &>/dev/null; then
  echo "Репозиторій ${OWNER}/${REPO_NAME} уже є — лише remote і push."
  git remote remove origin 2>/dev/null || true
  git remote add origin "$REMOTE_URL"
  git push -u origin main
else
  echo "Створюю ${OWNER}/${REPO_NAME} (private) і push..."
  git remote remove origin 2>/dev/null || true
  gh repo create "${REPO_NAME}" --private \
    --description "C55 Telegram bot + GitHub Pages (ZV Mini App)" \
    --source "$ROOT" \
    --remote origin \
    --push
fi

PAGES_URL="https://${OWNER}.github.io/${REPO_NAME}/zv_dorm_form.html"
echo ""
echo "Готово. Після першого деплою Pages:"
echo "  1) GitHub → repo → Settings → Pages → Build: GitHub Actions"
echo "  2) Actions → дочекайтесь успішного «GitHub Pages — ZV Mini App»"
echo "  3) У .env на VPS:  ZV_DORM_WEBAPP_URL=${PAGES_URL}"
echo "  4) Перезапустіть бота"
