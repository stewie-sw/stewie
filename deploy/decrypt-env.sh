#!/usr/bin/env bash
# Decrypt the SOPS-encrypted deploy secrets into deploy/.env (gitignored) before `docker compose up`.
# Requires the age private key at ~/.config/sops/age/keys.txt (or SOPS_AGE_KEY_FILE). See deploy/DEPLOY.md.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
command -v sops >/dev/null || { echo "sops not found (go install github.com/getsops/sops/v3/cmd/sops@latest, add ~/go/bin to PATH)"; exit 1; }
sops -d --input-type dotenv --output-type dotenv "$here/.env.enc" > "$here/.env"
chmod 600 "$here/.env"
echo "decrypted -> $here/.env ($(grep -cE '^[A-Z_]+=' "$here/.env") vars)"
