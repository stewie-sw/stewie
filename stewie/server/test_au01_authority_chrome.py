"""[REQ:AU-01] the global command-authority card is App-shell chrome: AuthorityChrome binds the same
/rc/eligibility gate set as the AuthorityPane and is rendered in the shell header, so command authority
(authorized/refused + refusal reason) is visible from EVERY view. Source-parsed against the committed frontend
(the behavioral proof is frontend/tests/authority-chrome.spec.ts across Plan + Release)."""
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _f(*p: str) -> str:
    with open(os.path.join(_ROOT, "frontend", "src", *p), encoding="utf-8") as fh:
        return fh.read()


def test_au01_chrome_binds_eligibility_and_is_global():  # [REQ:AU-01]
    auth = _f("panes", "Authority.tsx")
    # the chrome is a distinct exported component binding the REAL /rc/eligibility gate set
    assert "export function AuthorityChrome" in auth
    chrome = auth[auth.index("export function AuthorityChrome"):auth.index("export function AuthorityPane")]
    assert '"/rc/eligibility"' in chrome and 'data-testid="authority-chrome"' in chrome
    # it surfaces the refusal reason (AU-01: every refusal reason)
    assert "reason" in chrome


def test_au01_chrome_is_rendered_in_the_shell_header():  # [REQ:AU-01]
    app = _f("App.tsx")
    assert "AuthorityChrome" in app  # imported
    # rendered in the shell header chrome (the conops-spine), so it is present on every pane/view
    header = app[app.index('className="conops-spine"'):app.index("</header>")]
    assert "<AuthorityChrome" in header
