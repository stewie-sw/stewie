# STEWIE Frontend — Full UI/UX Audit (2026-06-09)

**Method.** Drove the PRODUCTION stack (nginx frontend :8000 → FastAPI backend) headless-Chrome via
playwright: all 8 panes (Plan / Perception / Metrics / Report / Validation / API / Server / Config),
sidebar top-to-bottom, a real Tutorial-1 plan → PDF round-trip, 1440×900 + 420×900 viewports.
Screenshots: `validation/ui_audit_2026-06-09/`. Audited against the STEWIE goals: the Day-28 KPT
("operator completes a simulated traverse in <30 min with NO technical assistance"), P21/P22
(telemetry + operator/director split), and the Year-1 phase deliverables.

## 1. What already works (keep)
- **Real product loop**: queue → plan → 3-page mission-control PDF in-pane; Plan IR export; profiles
  save/load; algorithm compare; execute-and-watch with live phase/battery; sample missions.
- **Grounded numbers everywhere**: the build estimate ("40 m³ ≈ 52.0 t … 215.9 MJ ≈ 45.0 charges")
  is the product's voice — physics, not decoration.
- **Honest empty states**: the Perception pane explicitly says the live SLAM map is open work, not a
  faked feed. This honesty discipline is a differentiator — preserve it through every redesign.
- **Engineer panes** (Validation figures, Swagger, health/metrics JSON) — right content for the
  intern/dev persona; cheap and real.
- **Layer system** (imagery/DEM/topology/hazard/excavation/lander) + click-to-place authoring.
- Mobile single-column degrades better than expected (sidebar stacks cleanly at 420 px).

## 2. Findings (severity-ordered)

### P0 — blocks the Day-28 operator KPT
| # | Finding | Evidence | Recommendation |
|---|---|---|---|
| P0-1 | **WebGL failure puts a raw error modal center-screen and leaves the main viewport BLACK.** On locked-down ops machines (no GPU) the first impression is a dead app, even though the 2-D PLAN VIEW + work-area DEM render fine. | plan.png | Catch the Cesium init failure → auto-fall back to a full-size 2-D site map (the PLAN VIEW canvas promoted to the main viewport) with a dismissible info chip, never a modal. |
| P0-2 | **No operator/director split.** Everything (truth layers, full telemetry, all panes) is visible to anyone; STEWIE's training premise is the operator sees ONLY the constrained link. | all panes | Implement the P22 session-mode toggle: `?mode=operator` hides truth layers/panes + routes data through the telemetry layer; director mode (auth'd) gets everything + debrief. This is also the #1 architectural UI change — design it before adding more panes. |
| P0-3 | **No guided flow / onboarding.** The sidebar is a single 12-section engineering stack (Body→Fleet→Estimate→Queue→Algorithm→Precedence→Keep-outs→Sample→Plan→Export→Profiles→Compare→Layers). A new intern cannot find the happy path unaided. | sidebar_bottom.png, mobile.png | Group into 3 collapsible steps — **1 SITE** (body/imagery/lat-lon), **2 MISSION** (fleet/queue/constraints), **3 PLAN & RUN** (algorithm/plan/execute/report) — with the current state badge ("2 orders · no plan yet"). Add a first-run coach-mark tour (5 stops, dismiss forever). |
| P0-4 | **No execution controls.** Execute-and-watch runs at fixed 60× with no pause/speed/step/abort, and ends without a debrief artifact link. | metrics.png | Add pause/play, speed (1×/10×/60×/max), abort; on completion surface "Mission summary →" (the B4.2 artifact). |

### P1 — required for the Year-1 product (gaps to INCLUDE)
| # | Missing piece | STEWIE ref | UI shape |
|---|---|---|---|
| P1-1 | **Telemetry/link HUD** — bandwidth, latency, drop %, frames dropped, link budget profile name | P21/B2 | persistent status strip (top bar, right of tabs); red when constrained ops bite |
| P1-2 | **Replay/debrief view** — side-by-side "what the operator saw" vs truth trajectory, slip events flagged | B3.3/B3.4 | a DEBRIEF pane (director-only), timeline scrubber + 2 synchronized canvases |
| P1-3 | **Charging-gap ensemble panel** — ranked candidate plans w/ predicted battery / coverage / risk, streaming in | P2.3/P2.4 | director-side drawer: "12 candidates evaluated — pick one" cards |
| P1-4 | **Acquisition coverage + uncertainty + downlink-queue overlays** | P3.1–P3.4 | three new LAYERS checkboxes + a queue list w/ per-item ETA at current kbps |
| P1-5 | **Science-targeting overlay** — ranked high-uncertainty reachable regions | P3.5 | annotated pins on the site map + a ranked list |
| P1-6 | **Scenario library picker** — nominal / battery emergency / shadowed traverse / comm dropout | P1.4 | replace the lone "tutorial mission" dropdown with a scenario gallery (cards: thumbnail, duration, difficulty) |
| P1-7 | **FORGE/certified-infrastructure view** — built artifacts w/ slope/bearing/sinter verification state | P4.2/P4.3 | a "Built" layer + an inspector card per certified record |
| P1-8 | **Mission summary artifact** at run end (route, energy, drops, seen-vs-actual divergence) | B4.2 | auto-generated, linked from Metrics + Report panes |

### P2 — polish / coherence
| # | Finding | Recommendation |
|---|---|---|
| P2-1 | **Stale branding**: header "LUNAR BUILD PLANNER" (Mars exists in Body picker!), Swagger title "dustgym planet browser", docs iframe dustgym-branded | Rename surface strings to **STEWIE** ("IPEx builds the Moon. STEWIE plans the build" as the header tagline); FastAPI `title=`; keep `dustgym` only as the physics-package name |
| P2-2 | Raw float coordinates in the queue ("(-7.063048203434806,0)") | format to 0.1 m: "(-7.1, 0.0)" |
| P2-3 | Tabs are flat + persona-less; Validation/API/Server/Config are engineer-only noise for operators | group tabs by persona: OPERATE (Plan·Metrics·Report) / PERCEIVE (Perception) / ENGINEER (Validation·API·Server·Config, collapsed behind one "Eng" tab); ties into P0-2 modes |
| P2-4 | Metrics rectangles unlabeled (which is pad vs berm?), battery bar unlabeled, elapsed "0h 3m / 762h 49m" unexplained | order labels on shapes, axis/legend, "elapsed / estimated total" caption |
| P2-5 | No loading/progress states on Plan (PDF render can take seconds through the proxy) | button → spinner + "rendering report…" |
| P2-6 | Accessibility: 11-px gray-on-dark labels, small hit targets, no keyboard shortcuts, no focus rings | contrast pass to WCAG AA, 44-px touch targets on the queue arrows, `?` shortcut overlay |
| P2-7 | No version/build stamp in the UI chrome (traceability for training sessions) | footer: version + git short-hash + active profile |
| P2-8 | Perception pane is an empty page with instructions that reference ANOTHER tab | embed the click-target (mini work-area DEM) directly in the pane |

## 3. Information-architecture recommendation (one diagram)
```
TOP BAR  [STEWIE]  [link HUD: ▂▄ 256kbps · 1.2s RTT · 0.5% drop]      [mode: OPERATOR ▾] [v0.1.0+sha]
TABS     OPERATE: Site · Mission · Run · Report     DIRECTOR(+auth): Debrief · Ensemble · Truth
         ENGINEER: Validation · API · Server · Config
SIDEBAR  (3 collapsible steps with state badges; current step auto-expanded)
MAIN     globe OR promoted 2-D site map (P0-1 fallback) with the full LAYERS set incl.
         coverage/uncertainty/downlink/built (P1-4/P1-7)
```

## 4. Suggested sequencing
1. **Now (pre-beta, days):** P0-1 fallback · P2-1 branding · P2-2/P2-4/P2-5 labels+spinners · P0-4 run controls.
2. **Beta weeks 2–3 (with B2/B3):** P0-2 modes + P1-1 HUD + P1-2 debrief (these are literally the
   telemetry-injection and split-view work items — the UI and backend land together).
3. **Beta week 4:** P0-3 guided flow + P1-6 scenario gallery + P1-8 summary (the Day-28 KPT package).
4. **Year-1 phases:** P1-3 (Ph.2), P1-4/P1-5 (Ph.3), P1-7 (Ph.4) ride their backend phases.

**Bottom line.** The bones are genuinely good — a real plan→physics→report loop with honest,
grounded numbers that most "mission planning UIs" fake. What it is today is an ENGINEER'S cockpit.
The Day-28 bet needs an OPERATOR'S instrument: one happy path, a constrained-link HUD, a director
who can see everything and debrief, and zero dead screens on a GPU-less laptop.
