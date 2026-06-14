# STEWIE.space on archimedes — setup + hardening runbook

A concise, practical path from a GoDaddy domain to a live, hardened `https://stewie.space`
served from archimedes (a home host). It builds on the existing, already-hardened
`deploy/compose.yml` (nginx frontend :8000 → uvicorn backend :8770, internal-only).

## Architecture (recommended)

```
GoDaddy (registrar)  ->  Cloudflare DNS + Tunnel  ->  archimedes
                                                       └─ docker compose:
                                                            nginx :8000  ──>  backend uvicorn :8770 (internal)
Admin / SSH:  Tailscale only (never public)
```

A **Cloudflare Tunnel** is the key choice for a home host: it makes an OUTBOUND connection,
so you open **no inbound ports**, your residential IP stays hidden, and TLS is free + automatic.
Port-forwarding 443 to a home box is the fallback, not the default.

---

## 1. Publish the stack (archimedes)

```bash
cd /mnt/projects/stewie/code
# deploy/.env (gitignored) — REQUIRED knobs:
#   STEWIE_API_KEY=<long random>          # fail-closed: privileged routes need auth (audit C-01)
#   STEWIE_CORS_ORIGINS=https://stewie.space   # NOT '*'
#   STEWIE_REGISTRATION=1                  # 1 = public request-access -> director approves (#117)
docker compose -f deploy/compose.yml up -d --build
curl -fsS http://localhost:8000/healthz   # expect {"status":"ok",...}
```

The backend port (8770) is **internal-only** (not published) — keep it that way; only nginx :8000
is local, and only the tunnel reaches it.

## 2. DNS + public TLS — Cloudflare Tunnel

1. **Move stewie.space to Cloudflare DNS**: in Cloudflare add the site, then in **GoDaddy →
   Nameservers** set the two Cloudflare nameservers it gives you. (Keeps GoDaddy as registrar.)
2. **Install + auth cloudflared on archimedes**, create a tunnel, point the hostname at the local
   frontend, and run it as a service:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create stewie
   # ~/.cloudflared/config.yml:
   #   tunnel: <id>
   #   credentials-file: /home/<user>/.cloudflared/<id>.json
   #   ingress:
   #     - hostname: stewie.space
   #       service: http://localhost:8000
   #     - service: http_status:404
   cloudflared tunnel route dns stewie stewie.space
   sudo cloudflared service install     # systemd; survives reboot
   ```
3. In Cloudflare: SSL/TLS mode **Full**, **Always Use HTTPS** on. Result: `https://stewie.space`
   → tunnel → nginx → backend.

**Fallback without Cloudflare** (more exposure, needs static IP or DDNS): GoDaddy `A` record →
your public IP, router port-forward 443 → archimedes, and run Caddy in front of :8000 for
auto-HTTPS (`stewie.space { reverse_proxy localhost:8000 }`).

## 3. Auth posture (already built — just configure)

- `STEWIE_API_KEY` set ⇒ **fail-closed**; operators sign in with their own password (#117), the
  shared key never enters a browser. Founding director: sign in once via the bootstrap key, then
  "set password".
- `STEWIE_CORS_ORIGINS=https://stewie.space` (never `*` in prod).
- Leave `STEWIE_DEV_OPEN` **unset** — the `_is_loopback` guard already prevents remote dev-open
  behind the proxy, but don't tempt it.
- Invitation-only = `STEWIE_REGISTRATION=1` + director approval (public can request, not self-admit).

## 4. Harden archimedes (host)

- **SSH**: key-only (`PasswordAuthentication no`, `PermitRootLogin no`), non-root admin user,
  `fail2ban`. Keep SSH reachable **only over Tailscale**, never on the public internet.
- **Firewall (UFW)**: `default deny incoming`, `default allow outgoing`. With the Cloudflare Tunnel
  you need **zero public inbound ports** (the tunnel is outbound). Allow Tailscale's interface.
- **Tailscale**: all admin/SSH over the tailnet; the public only ever reaches the tunnel.
- **Patching**: `unattended-upgrades` for security updates; reboot window scheduled.
- Run the compose stack as a **non-root** user.

## 5. Docker hardening

- The compose already applies `cap_drop: ALL`, `no-new-privileges`, `read_only` rootfs, `tmpfs`
  for writables, and pins the backend internal — keep all of it.
- Prefer **rootless Docker** (membership in the `docker` group ≈ root). If using rootful, restrict
  the deploy user and never run untrusted images.
- Pin base images by digest where practical; scan periodically (`trivy image` / `docker scout`).
- Do not add `ports:` to the backend service.

## 6. Mail — do NOT self-host SMTP on archimedes

Self-hosting outbound mail from a residential connection is a losing battle: ISPs block port 25,
home IPs sit on blocklists, and you'd still need a static IP, correct **PTR/rDNS**, plus
**SPF + DKIM + DMARC** — and deliverability would remain poor. Recommended instead:

- **Inbound** (`you@stewie.space`): **Cloudflare Email Routing** (free) → forward to a real mailbox.
- **Outbound** (any future cockpit notifications): a **transactional relay** (a provider's SMTP API
  / smarthost), never direct from archimedes. If you must self-host, put the mail server on a small
  **cloud VPS** (static IP, proper rDNS) and relay to it — never the home box.
- Note: STEWIE's #117 access flow needs **no email** (request-access → director approves in-panel),
  so mail is not on the launch critical path.

## 7. Bug-proofing / ops

- **Health**: backend `/healthz` (compose healthcheck) + frontend `depends_on: healthy`;
  `restart: unless-stopped` already set. Add an external uptime check on `https://stewie.space/healthz`.
- **Backups**: the `stewie-data` volume holds `operators.json`, missions, the twin journal, and
  reports — back it up. Use the built-in `/admin/backup/replicate` (set `STEWIE_BACKUP_DIR` to a
  second disk/host) on a cron, or `docker run --rm --volumes-from` + `tar` nightly off-box.
- **Logs**: `docker compose logs` + the server request log; ship to journald or a file with rotation.
- **Metrics**: `/metrics` (request counters + uptime) for a simple scrape.

## Launch checklist

- [ ] `deploy/.env`: strong `STEWIE_API_KEY`, `STEWIE_CORS_ORIGINS=https://stewie.space`, registration policy
- [ ] `docker compose up -d --build`; `localhost:8000/healthz` green
- [ ] Cloudflare nameservers set at GoDaddy; tunnel routes `stewie.space` → `:8000`; HTTPS loads
- [ ] Founding director: bootstrap sign-in → set password; test an operator request → approve
- [ ] SSH key-only + Tailscale-only; UFW deny-inbound; no public 22/8770
- [ ] `stewie-data` backup scheduled + restore tested
- [ ] Inbound mail via Cloudflare Email Routing; no self-hosted SMTP
```
