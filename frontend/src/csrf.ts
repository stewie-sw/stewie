// [dispatch-audit R7a] SEC-01 double-submit CSRF. A state-changing request authenticated by the browser
// SESSION COOKIE must echo the readable `stewie_csrf` cookie in the `X-CSRF-Token` header, or the backend
// guard (deps.py `_enforce_csrf`) refuses it with 403. The cookie is intentionally NOT HttpOnly so the page
// can read it here. Returns {} when the cookie is absent (header/api-key auth, or dev-open loopback where the
// guard is bypassed), so it is SAFE to spread into every state-changing fetch's headers unconditionally.
export function csrfHeader(): Record<string, string> {
  const m = document.cookie.match(/(?:^|;\s*)stewie_csrf=([^;]+)/);
  return m ? { "X-CSRF-Token": decodeURIComponent(m[1]) } : {};
}
