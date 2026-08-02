#!/usr/bin/env bash
# SG-01: refresh the off-DEVICE mirror and the off-HOST bundle, then verify the separation invariant.
#
# The 2026-07-28 review found the repo, the "canonical" gitea remote and every runtime volume on ONE
# disk (/dev/nvme0n1p1 on this host). That is not theoretical: this repo had a git corruption event on
# 2026-07-28, and on 2026-08-02 a P0 authority fix (dab8a5ce) was found to exist on ZERO remotes --
# working copy plus a stale local gitea, both on that same disk. One failure loses the work and its
# only backup together.
#
# Three tiers, deliberately on different failure domains:
#   1. working repo        /mnt/projects/stewie/code   (nvme0n1)
#   2. off-DEVICE mirror   ~/backups/stewie-mirror.git (sda -- survives losing nvme0n1)
#   3. off-HOST bundle     gdrive-personal:Backups/stewie/ (survives losing the machine)
#
# Idempotent; safe to re-run and to cron. Nothing here deletes anything.
#
#   scripts/backup_repo.sh            # refresh all tiers
#   scripts/backup_repo.sh --local    # skip the off-host upload (no network)
set -euo pipefail

REPO="${STEWIE_REPO:-/mnt/projects/stewie/code}"
MIRROR="${STEWIE_MIRROR:-$HOME/backups/stewie-mirror.git}"
BUNDLE_DIR="${STEWIE_BUNDLE_DIR:-$HOME/backups}"
REMOTE="${STEWIE_BACKUP_REMOTE:-gdrive-personal:Backups/stewie/}"
KEEP_BUNDLES="${STEWIE_KEEP_BUNDLES:-3}"
LOCAL_ONLY=0
[ "${1:-}" = "--local" ] && LOCAL_ONLY=1

echo "== SG-01 backup =="

# --- tier 2: off-device mirror -------------------------------------------------------------------
mkdir -p "$(dirname "$MIRROR")"
if [ ! -d "$MIRROR" ]; then
  git clone --mirror "$REPO" "$MIRROR"
else
  git -C "$MIRROR" remote update --prune
fi
echo "mirror : $MIRROR ($(git -C "$MIRROR" for-each-ref | wc -l) refs, $(du -sh "$MIRROR" | cut -f1))"

# --- tier 3: off-host bundle ---------------------------------------------------------------------
BUNDLE="$BUNDLE_DIR/stewie-$(date +%Y%m%d).bundle"
git -C "$REPO" bundle create "$BUNDLE" --all
# A bundle that does not verify is not a backup. Fail loudly rather than upload a broken one.
git -C "$REPO" bundle verify "$BUNDLE" >/dev/null
echo "bundle : $BUNDLE ($(du -h "$BUNDLE" | cut -f1), verified complete)"

if [ "$LOCAL_ONLY" -eq 0 ]; then
  rclone copy "$BUNDLE" "$REMOTE" --stats-one-line
  echo "offhost: $REMOTE"
else
  echo "offhost: SKIPPED (--local)"
fi

# Retain the most recent N bundles locally; the off-host copies are kept by the remote.
ls -1t "$BUNDLE_DIR"/stewie-*.bundle 2>/dev/null | tail -n +"$((KEEP_BUNDLES + 1))" | while read -r old; do
  echo "prune  : $old"; rm -f "$old"
done

# --- the invariant -------------------------------------------------------------------------------
python3 "$(dirname "$0")/check_backup_separation.py" --repo "$REPO" --backup "$MIRROR"
