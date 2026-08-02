"""The test suite must render headlessly: no GUI matplotlib backend, ever.

STEWIE renders real report figures (lode/mission_planner, planner_acceptance, planner_views), and under
a FastAPI TestClient those sync routes run in a THREADPOOL -- `services.py` keeps a `report_lock`
precisely because "matplotlib/pyplot is process-global + thread-unsafe". With PyQt6 installed (it is,
via the QGIS tooling) matplotlib auto-selects the GUI backend `qtagg`, which turns every one of those
renders into a Qt call from a non-main thread: undefined behaviour.

Measured directly: three figures rendered from a worker thread under `qtagg` emit

    GLib-CRITICAL: g_main_context_pop_thread_default: assertion 'stack != NULL' failed

-- Qt's thread-context stack popped from the wrong thread -- while the identical probe under `Agg` is
clean. A full-suite run segfaulted (exit 139, no Python traceback) inside `lode/test_mission_planner.py`,
the heaviest PDF-rendering file. It did NOT reproduce on a quieter machine, which is exactly how
undefined behaviour behaves: it faults on timing, not on command. So these tests pin the *precondition*
(a non-interactive backend), which is deterministic, rather than trying to pin the crash, which is not.

`deploy/compose.yml` already sets MPLBACKEND=Agg for the containers, so production was never exposed --
only the test environment was, because nothing pinned it there.

Run: <venv>/bin/python -m pytest scripts/test_headless_render_backend.py -q
"""
from __future__ import annotations

import threading

import matplotlib


def _interactive_backends() -> set[str]:
    """Matplotlib's OWN list of GUI backends -- never a hand-maintained one, which would drift."""
    try:                                              # matplotlib >= 3.9
        from matplotlib.backends import BackendFilter, backend_registry
        names = backend_registry.list_builtin(BackendFilter.INTERACTIVE)
    except ImportError:                               # matplotlib < 3.9
        names = matplotlib.rcsetup.interactive_bk
    return {n.lower() for n in names}


def test_backend_is_non_interactive():
    """The precondition, checked against matplotlib's own registry of GUI backends."""
    backend = matplotlib.get_backend()
    assert backend.lower() not in _interactive_backends(), (
        f"tests are using the GUI backend {backend!r}; report rendering happens on worker threads, so a "
        "GUI backend is undefined behaviour (see the module docstring). Pin MPLBACKEND=Agg.")


def test_pyplot_renders_from_a_worker_thread_without_touching_a_gui():
    """The actual operation that crashed: a figure rendered off the main thread must complete cleanly."""
    import matplotlib.pyplot as plt

    errors: list[str] = []

    def render():
        try:
            fig = plt.figure()
            ax = fig.add_subplot(111)
            ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 4.0])
            fig.canvas.draw()
            plt.close(fig)
        except BaseException as e:                    # noqa: BLE001 -- any failure here is the defect
            errors.append(repr(e))

    t = threading.Thread(target=render)
    t.start()
    t.join(timeout=60)
    assert not t.is_alive(), "off-main-thread render hung"
    assert not errors, f"off-main-thread render failed: {errors}"
