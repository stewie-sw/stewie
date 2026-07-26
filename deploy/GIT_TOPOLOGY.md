# Git topology: private canonical (Gitea) + public mirror (GitHub) + local serving

**Set up 2026-07-26.** Replaces the single-remote arrangement in which `origin` (public GitHub) was
the only place the work lived.

## Remotes

| Remote | URL | Visibility | Role |
|---|---|---|---|
| `gitea` | `http://127.0.0.1:3000/aaron/stewie.git` (public URL `https://git.stewie.space/aaron/stewie.git`) | **PRIVATE** | Canonical. Everything goes here, including research branches and agent worktrees. |
| `origin` | `https://github.com/stewie-sw/stewie.git` | **PUBLIC** | Curated mirror. Only branches deliberately intended for publication. |

Gitea runs as the `gitea` container on this host, bound to `127.0.0.1:3000`, reverse-proxied by
cloudflared at `git.stewie.space`. Serving is therefore local; the public URL is a tunnel, not a
second copy.

## The rule

**Push everything to `gitea`. Push to `origin` deliberately, per branch, never with `--all`.**

`gitea` currently holds 90 branches, including ~60 `worktree-agent-*` and `worktree-wf-*` branches
left by agent fan-out runs. Those are working state, not publications. Pushing them to a public
mirror would expose scratch work and make the public history unreadable.

```bash
# routine: private canonical, everything
git push gitea <branch>
git push --all gitea

# publication: explicit, one branch at a time, after a secret scan
git push origin <branch>
```

## Before ANY push to origin

`origin` is public. Run this first, every time:

```bash
# 1. no secret files tracked
for f in deploy/.env deploy/artemis-api-key.conf deploy/artemis-htpasswd \
         deploy/gis-anon-key.conf deploy/artemis-gis-anon-key.conf; do
  git ls-files --error-unmatch "$f" 2>/dev/null && echo "TRACKED - STOP: $f"
done

# 2. no embedded credentials in tracked source
git grep -InE "(api[_-]?key|secret|password|token)[\"'[:space:]]*[:=][\"'[:space:]]*[A-Za-z0-9/+_-]{24,}" \
  -- ':!*test*' ':!*.md'

# 3. no bare 64-hex key blobs (the artemis-api-key.conf shape).
#    Docker image digests and pip lock hashes are expected hits; anything else is not.
git grep -InE "\b[0-9a-f]{64}\b" -- ':!*.md' ':!*test*' ':!*.json'
```

Scan of 2026-07-26 on `gate3/world-state-prereqs`: **clean on all three.**

## Credential

A Gitea access token was minted for this setup:

- user `aaron`, token name **`stewie-setup-20260726`**, scopes `write:repository,write:user`
- it is embedded in the `gitea` remote URL in `.git/config`, which is **not** tracked by git

To rotate or revoke:

```bash
docker exec -u git gitea gitea admin user generate-access-token \
  --username aaron --scopes "write:repository,write:user" --token-name <new-name>
# then update the remote:
git remote set-url gitea http://aaron:<NEW_TOKEN>@127.0.0.1:3000/aaron/stewie.git
```

Revoke the old one from the Gitea web UI under Settings, Applications.

## History-rewrite prohibition

**Never rewrite, force-push, split, or privatise the history on `origin`.** Commit `dd6a700`
anchors a pre-registered criterion cited in a submitted paper, in the dissertation appendix, and in
a citable deposit bundle. It is reachable from `origin/main`. Rewriting that history makes a
published pre-registration unverifiable.

The same prohibition does not bind `gitea`, but there is no reason to rewrite there either.
