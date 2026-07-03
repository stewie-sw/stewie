# Knowledge graph

An interactive, navigable map of the STEWIE codebase, generated with [graphify](https://github.com/safishamsi/graphify) from the source tree. Nodes are files, classes, and functions; edges are the `contains` / `calls` / `imports` relationships extracted directly from the code (AST). Communities are detected automatically and colored, so tightly-coupled subsystems cluster together.

<iframe src="../knowledge-graph.html" title="STEWIE codebase knowledge graph" style="width:100%; height:70vh; border:1px solid #444; border-radius:6px;"></iframe>

If the embed does not load, open it full-screen: [**knowledge-graph.html**](../knowledge-graph.html).

## What the graph covers

| | |
|---|---|
| Nodes | **17,098** (files, classes, functions) |
| Edges | **32,779** (`contains` / `calls` / `imports`) |
| Communities | **741** (auto-detected, module-labeled) |
| Source | **1,143 code files** across `stewie/`, `dart/`, `lode/`, `leap/`, `forge/`, `scripts/`, `ros2_ws/`, `benchmarks/` |

Above 5,000 nodes the interactive view auto-aggregates to a **community-level map** (741 community nodes, 1,827 cross-community edges) so it stays navigable in the browser.

## God nodes (the most-connected abstractions)

- **`ColumnState`** (230 edges) — the conserved-physics terrain state; the true cross-subsystem hub bridging `stewie/physics`, `stewie/twin`, `stewie/terrain`, `stewie/runtime`, `dart`, `lode`, and `leap`.
- **`S3liReader` / `S3liDem`** — the S3LI lunar DEM readers feeding the navigation and terrain stacks.
- **`log_event()`** (85 edges) — the audit/event spine threaded through the server routers and bridge.

## Scope and honesty

- This is the **code-structure graph** (deterministic AST extraction). The documentation-semantic layer (docs → concept → code cross-references) is not included in this build; regenerating it needs a paid Gemini key, since the free tier's per-minute token quota can't process the corpus.
- The graph is rebuilt on a schedule and reflects the `main` branch at build time.
