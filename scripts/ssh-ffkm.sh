#!/usr/bin/env bash
# SSH на production ffkm-consent.
# Те же секреты, что и у scripts/deploy-production.sh
set -euo pipefail

HOST="${FFKM_SSH_HOST:-46.173.17.188}"
PORT="${FFKM_SSH_PORT:-2222}"
USER_NAME="${FFKM_SSH_USER:-root}"
KEY_PATH="${FFKM_SSH_KEY_PATH:-$HOME/.ssh/ffkm_consent_ed25519}"

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

if [[ -n "${FFKM_SSH_PRIVATE_KEY:-}" ]]; then
  KEY_PATH="$HOME/.ssh/ffkm_consent_ed25519"
  printf '%s\n' "${FFKM_SSH_PRIVATE_KEY//$'\r'/}" | sed 's/\\n/\n/g' > "$KEY_PATH"
  chmod 600 "$KEY_PATH"
fi

if [[ ! -f "$KEY_PATH" ]]; then
  echo "ERROR: SSH key not found. Set FFKM_SSH_PRIVATE_KEY or FFKM_SSH_KEY_PATH." >&2
  exit 1
fi

exec ssh -i "$KEY_PATH" -p "$PORT" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new \
  "${USER_NAME}@${HOST}" "$@"
