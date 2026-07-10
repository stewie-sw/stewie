"""[REQ:QG-02] QGIS-Server publishes the shared-core .qgz as OGC WMS/WMTS/WFS (one project, two clients).

Acceptance: a `docker compose --profile gis` GetMap on a site in IAU_2015:30135 returns a pole-truthful tile
matching QGIS Desktop. The qgis-server is opt-in (profile 'gis'), so it is NOT in CI — the RUNTIME evidence
is a live GetMap (verified 2026-07-10 against the :8082 container: Site01, IAU_2015:30135 ->
1400x1400 non-blank pole relief tile, 16709 unique colors; the byte-identical-to-QGIS-Desktop proof is
gate P1.8, gis/SERVER.md + the deploy/compose.yml comment). This python gate is the CI-runnable [REQ:QG-02]
citation: it asserts the SAME .qgz the WMS publishes declares the pole CRS + the STEWIE layers, and that the
compose service that serves it is wired — i.e. the one-project-two-clients contract holds at rest. A static
gate (mirrors test_gw10_request_guard.py); the render itself is the live GetMap, not fabricated here.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_QGZ = _ROOT / "gis" / "stewie_south_pole.qgz"
_COMPOSE = _ROOT / "deploy" / "compose.yml"


def _qgs_xml() -> str:
    assert _QGZ.exists(), f"QG-02 project missing: {_QGZ}"
    with zipfile.ZipFile(_QGZ) as z:
        qgs = [n for n in z.namelist() if n.endswith(".qgs")]
        assert qgs, ".qgz does not contain a .qgs project"
        return z.read(qgs[0]).decode("utf-8", "replace")


def test_the_published_qgz_declares_the_pole_crs():  # [REQ:QG-02]
    """The project the WMS GetMap renders is in the lunar south-polar-stereographic frame IAU_2015:30135 —
    the pole-truthful CRS (not an Earth datum). This is what makes a GetMap on a site pole-truthful."""
    xml = _qgs_xml()
    assert "IAU_2015:30135" in xml, "the .qgz does not declare the pole CRS IAU_2015:30135"
    # it is the project's working frame, not an incidental mention: many references across layers/canvas.
    assert xml.count("30135") >= 10, "IAU_2015:30135 is not the project's pervasive working CRS"


def test_the_published_qgz_carries_the_stewie_layers():  # [REQ:QG-02]
    """The one shared project QGIS Desktop opens and QGIS-Server publishes carries the real STEWIE layer set
    (site DEM/hillshade/slope + Artemis site vectors) — the same layers the GetMap LAYERS= parameter names."""
    import re
    xml = _qgs_xml()
    names = re.findall(r"<layername>([^<]+)</layername>", xml)
    assert len(names) >= 20, f"expected the full STEWIE layer set, found {len(names)}"
    # the real lunar terrain layers a pole GetMap renders.
    assert any("Haworth" in n for n in names), "Haworth DEM/hillshade layer missing"
    assert any("Site" in n for n in names), "Artemis Site layers missing"
    assert any("Hillshade" in n for n in names), "a hillshade layer (the shaded relief) missing"


def test_the_compose_service_publishes_the_qgz_as_wms():  # [REQ:QG-02]
    """QGIS-Server serves the SAME .qgz as OGC WMS/WMTS/WFS via the opt-in 'gis' profile. Assert the service
    that produces the live GetMap is wired: the qgis/qgis-server image (pinned 3.34 for PROJ 9.4 / the IAU
    registry), the 'gis' profile, and the mount that carries the .qgz into the container."""
    assert _COMPOSE.exists(), "deploy/compose.yml missing"
    compose = _COMPOSE.read_text(encoding="utf-8")
    assert "qgis-server:" in compose, "no qgis-server service"
    assert "qgis/qgis-server:3.34" in compose, "qgis-server image not pinned to 3.34 (PROJ 9.4 / IAU registry)"
    assert 'profiles: [ "gis" ]' in compose, "qgis-server is not opt-in via the 'gis' profile"
    # the .qgz is mounted into the container at the MAP= path the GetMap URL uses.
    assert "/io/data/code/gis" in compose, "the .qgz project directory is not mounted into qgis-server"
