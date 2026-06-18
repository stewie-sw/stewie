"""PO-13: a single exported version, a CHANGELOG, and a SemVer string -- kept honest by this test.
`stewie.__version__` MUST equal pyproject [project].version (no silent drift), be valid SemVer, and
the CHANGELOG must document the current version."""
import os
import re

import stewie

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")


def _pyproject_version() -> str:
    with open(os.path.join(_ROOT, "pyproject.toml"), encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\s*version\s*=\s*"([^"]+)"', line)
            if m:
                return m.group(1)
    raise AssertionError("no [project].version in pyproject.toml")


def test_exported_version_is_valid_semver():  # [REQ:PO-13]
    assert _SEMVER.match(stewie.__version__), f"{stewie.__version__!r} is not SemVer"


def test_version_matches_pyproject():
    assert stewie.__version__ == _pyproject_version()           # no drift between code and packaging


def test_changelog_exists_and_documents_the_version():
    path = os.path.join(_ROOT, "CHANGELOG.md")
    assert os.path.exists(path), "CHANGELOG.md missing (PO-13)"
    text = open(path, encoding="utf-8").read()
    assert "Semantic Versioning" in text and "Keep a Changelog" in text
    # the current version (or an Unreleased section feeding it) must be documented
    assert stewie.__version__ in text or "[Unreleased]" in text
