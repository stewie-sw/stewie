"""STEWIE QGIS Processing provider (P-A #46) — registers STEWIE analyses as QGIS Processing algorithms that
call the live STEWIE FastAPI backend, so a scientist/planner can run them from the QGIS GUI, the qgis_process
CLI, batch, or a Model. QGIS imports are LAZY (only inside classFactory) so the pure stewie_backend logic and
its pytest gate import cleanly in CI WITHOUT a QGIS runtime.

Load in QGIS: symlink/copy this dir into the QGIS plugins dir, or set QGIS_PLUGINPATH. Headless: see the
provider registration in stewie_provider.StewieProvider.
"""


def classFactory(iface):   # noqa: N802  (QGIS calls this exact name when it loads the plugin)
    from .stewie_provider import StewiePlugin   # lazy -> pulls qgis.core only under a real QGIS runtime
    return StewiePlugin(iface)
