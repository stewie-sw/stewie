"""N15 externalized config overlay (area O): env / STEWIE_CONFIG override module constants.

Every module-level scalar in constants.py / ipex_specs.py is overridable without editing
source, via STEWIE_<NAME> env vars or a STEWIE_CONFIG TOML file (env wins). Derived values
recompute from their (possibly overridden) inputs.
"""
import importlib
import os
import textwrap

import pytest

from stewie.specs import config, constants, ipex_specs


@pytest.fixture
def clean_reload():
    """After each test, strip STEWIE_* env and reload the constant modules to defaults so an override
    cannot leak into the rest of the suite. Up front, strip the suite-wide vars the repo conftest
    injects -- STEWIE_DEV_OPEN (an auth control) and STEWIE_DATA_DIR (the #122 per-test data-dir
    isolation) -- since get_overrides() scans all STEWIE_* vars, so the 'no env -> identity' overlay
    test must not see either."""
    for var in ("STEWIE_DEV_OPEN", "STEWIE_DATA_DIR"):
        os.environ.pop(var, None)
    yield
    for var in [v for v in os.environ if v.startswith("STEWIE_")]:
        del os.environ[var]
    importlib.reload(constants)
    importlib.reload(ipex_specs)


def test_no_env_is_identity(clean_reload):
    importlib.reload(constants)
    assert constants.RHO_SURFACE == 1300.0
    assert constants.RHO_SPOIL == 1300.0           # derived
    assert constants.RHO_GRAIN == 3100.0           # derived
    assert config.get_overrides() == {}


def test_env_override_scalar_recomputes_derived(clean_reload, monkeypatch):
    monkeypatch.setenv("STEWIE_RHO_SURFACE", "1250")
    importlib.reload(constants)
    assert constants.RHO_SURFACE == 1250.0
    assert constants.RHO_SPOIL == 1250.0           # RHO_SPOIL tracks the loose surface -> recomputed


def test_env_override_grain_inputs_recompute(clean_reload, monkeypatch):
    monkeypatch.setenv("STEWIE_G_s", "3.0")
    importlib.reload(constants)
    assert constants.G_s == 3.0
    assert constants.RHO_GRAIN == 3.0 * constants.RHO_WATER   # 3000, recomputed


def test_toml_file_override(clean_reload, monkeypatch, tmp_path):
    cfg = tmp_path / "dust.toml"
    cfg.write_text(textwrap.dedent("""
        RHO_SURFACE = 1200.0
        ROVER_MASS_DRY_KG = 25.0
    """))
    monkeypatch.setenv("STEWIE_CONFIG", str(cfg))
    importlib.reload(constants)
    assert constants.RHO_SURFACE == 1200.0
    assert constants.ROVER_MASS_DRY_KG == 25.0


def test_toml_section_table(clean_reload, monkeypatch, tmp_path):
    cfg = tmp_path / "dust.toml"
    cfg.write_text("[constants]\nCOHESION = 200.0\n")
    monkeypatch.setenv("STEWIE_CONFIG", str(cfg))
    importlib.reload(constants)
    assert constants.COHESION == 200.0


def test_env_wins_over_file(clean_reload, monkeypatch, tmp_path):
    cfg = tmp_path / "dust.toml"
    cfg.write_text("RHO_SURFACE = 1200.0\n")
    monkeypatch.setenv("STEWIE_CONFIG", str(cfg))
    monkeypatch.setenv("STEWIE_RHO_SURFACE", "1100")
    importlib.reload(constants)
    assert constants.RHO_SURFACE == 1100.0


def test_unknown_key_not_injected(clean_reload, monkeypatch):
    monkeypatch.setenv("STEWIE_NOT_A_REAL_CONSTANT", "5")
    importlib.reload(constants)
    assert not hasattr(constants, "NOT_A_REAL_CONSTANT")    # a typo cannot create a global


def test_ipex_specs_override_recomputes_functions(clean_reload, monkeypatch):
    base = ipex_specs.battery_energy_j()
    monkeypatch.setenv("STEWIE_BATTERY_SERIES_CELLS", "14")
    importlib.reload(ipex_specs)
    assert ipex_specs.BATTERY_SERIES_CELLS == 14
    # battery_energy_j reads the constant live -> a 14S pack stores more than 12S
    assert ipex_specs.battery_energy_j() > base
    assert ipex_specs.battery_energy_j() == 14 * ipex_specs.LIION_NOMINAL_V_PER_CELL * 30.0 * 3600.0


def test_describe_reports_applied(clean_reload, monkeypatch):
    monkeypatch.setenv("STEWIE_RHO_SURFACE", "1234")
    importlib.reload(constants)
    d = config.describe()
    assert d["overrides"]["RHO_SURFACE"] == 1234.0
    assert d["applied"]["stewie.specs.constants"]["RHO_SURFACE"][1] == 1234.0


def test_describe_clears_when_default(clean_reload, monkeypatch):
    monkeypatch.setenv("STEWIE_RHO_SURFACE", "1234")
    importlib.reload(constants)
    assert "stewie.specs.constants" in config.describe()["applied"]
    monkeypatch.delenv("STEWIE_RHO_SURFACE")
    importlib.reload(constants)
    # a clean reload must clear the stale applied record (no leak into describe)
    assert "stewie.specs.constants" not in config.describe()["applied"]


def test_data_dir_env_then_dustgym_fallback(monkeypatch, tmp_path):
    """#125: STEWIE_DATA_DIR wins; the legacy DUSTGYM_DATA_DIR env is still honored (rename back-compat)."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path / "explicit"))
    monkeypatch.setenv("DUSTGYM_DATA_DIR", str(tmp_path / "old_env"))
    assert config.data_dir() == str(tmp_path / "explicit")
    monkeypatch.delenv("STEWIE_DATA_DIR")
    assert config.data_dir() == str(tmp_path / "old_env")   # back-compat env fallback (was dead)


def test_data_dir_serves_legacy_dustgym_dir_only_when_new_absent(monkeypatch, tmp_path):
    """#125: with no env, serve an existing ~/.local/share/dustgym (legacy) until the stewie dir exists."""
    monkeypatch.delenv("STEWIE_DATA_DIR", raising=False)
    monkeypatch.delenv("DUSTGYM_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    (tmp_path / "dustgym").mkdir()
    assert config.data_dir() == str(tmp_path / "dustgym"), "legacy dustgym data not served (dead branch)"
    (tmp_path / "stewie").mkdir()
    assert config.data_dir() == str(tmp_path / "stewie"), "should prefer the new dir once it exists"


def test_describe_redacts_secret_env_values(monkeypatch):
    """SEC-1 [REQ:FS-11]: describe() (and thus /config) must NEVER return key/token/secret VALUES."""
    monkeypatch.setenv("STEWIE_API_KEY", "supersecret-master-key")
    monkeypatch.setenv("STEWIE_DIRECTOR_KEY", "another-secret")
    d = config.describe()
    blob = str(d)
    assert "supersecret-master-key" not in blob and "another-secret" not in blob
    # the KEYS may appear (so an operator sees a key IS set) but redacted
    assert d["overrides"].get("API_KEY") == "[REDACTED]"
