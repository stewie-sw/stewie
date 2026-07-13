"""STEWIE viz2 pixel-streaming service (standalone).

The browser drives the REAL Godot sim live over a WebSocket:

    Browser  <-- JPEG frames / --> input twists  (WS /ws)
        |
    FastAPI stream server (this package, ``stewie.stream.app``)
        |  length-prefixed frames over a localhost TCP seam
    Godot ``viz2.tscn --live --stream``  <->  ``Viz2Runtime`` (the conserved mutator)

This package is INTENTIONALLY standalone from ``stewie.server`` (the cockpit): a new FastAPI
app, a new localhost frame seam, and a new minimal stream page. It REUSES the B2 runtime
(``stewie.runtime.viz2_runtime`` / ``viz2_serve``), the B3 Godot live-drive path
(``stewie/godot/viz2_root.gd --live``), and the procedural bundle generator
(``stewie.terrain.procedural_bundle``) unchanged.
"""
