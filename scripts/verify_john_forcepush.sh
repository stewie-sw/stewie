#!/bin/bash
# John's dustgym/dustgym force-push -> verify content parity with the monorepo, port any deltas.
# Per John: hashes all change, files should be identical. TRUST BUT VERIFY file-by-file.
set -e
W=$(mktemp -d)
git clone --depth 1 https://github.com/dustgym/dustgym "$W/john" 2>/dev/null
echo "== file-level diff vs our import base (archive/dustgym_repo_frozen_2026-06-09) =="
diff -rq --exclude=.git --exclude=__pycache__ --exclude=.tools --exclude=out --exclude=build \
     --exclude=dist --exclude='*.egg-info' \
     /mnt/projects/stewie/archive/dustgym_repo_frozen_2026-06-09 "$W/john" | tee /tmp/john_diff.txt | head -40
N=$(grep -c . /tmp/john_diff.txt || true)
echo "== $N differing/unique paths (full list /tmp/john_diff.txt) =="
echo "If N==0: content identical -> John can archive; nothing to port."
echo "If N>0: each 'Only in john' file needs a mapped port into stewie/code (M1 map applies);"
echo "        each differing file needs a content diff + a ported edit. Do NOT bulk-copy."
rm -rf "$W"
