"""[REQ:IN-02] The raw/derived/belief/world/mission layer-tier taxonomy + its enforcement (extends LY-01 +
GW-03 + EG-08).

The LY-01 catalog already declares each layer's ``source_class`` (WHERE the data came from: observed / prior /
derived / forecast / belief / ...). IN-02 adds a second, ORTHOGONAL axis -- a closed ``tier`` in
{raw, derived, belief, world, mission} (WHAT the layer may be used for) -- and the gates that keep the two
honest. Design of record: ``design/STEWIE_autodig_ingest_design_2026-07-08.md`` ss5.2-5.3.

The tier is DERIVED from the layer's declared ``domain`` + ``source_class`` -- a faithful classification of the
REAL declared provenance (the same pattern as ``routers.world.layer_confidence``), never a fabricated field, so
it stays in sync with the committed catalog with no second source of truth to drift. It is served BESIDE
``source_class`` (never replacing it) by ``routers.world.layer_catalog``.

The five tiers (design ss5.2):
  * ``raw``     -- an unprocessed sensor / truth stream (images, IMU, odom, motor current, sim-truth). Raw
                   streams are NEVER planning- or release-eligible; they must be estimated-through first.
  * ``derived`` -- a deterministic transform of the world with no independent epistemic uncertainty.
  * ``belief``  -- an estimate carrying declared uncertainty (terrain confidence, traversability, terramechanics
                   estimates, robot-pose belief, observed-with-uncertainty maps).
  * ``world``   -- the approved authoritative terrain state (the base DEM/CRS + reconciled truth).
  * ``mission`` -- intent: plans, design/build orders, executed excavation changes.

Enforcement (``validate_layer`` / ``validate_catalog``):
  * a ``raw``-tier layer marked planning- or release-eligible FAILS validation (the acceptance kill condition);
  * a ``belief``-tier layer that IS planning/release eligible must carry DECLARED uncertainty.

Promotion (``promote_tier``): a tier advances only FORWARD, one rung along the ladder
``raw -> derived -> belief -> world``, and only carrying an EG-08 ACCEPTED reconciliation proposal
(``stewie.contracts.reconciliation.Proposal`` in state ACCEPTED/APPLIED). A belief->world promotion without an
accepted proposal is refused; ``mission`` is intent and is not on the estimation ladder.

Scope note (honest): the design's ss5.3 aspiration is that eligibility become fully *derivable* from the tier
("planning requires world/mission, or belief-with-uncertainty"). The current LY-01 catalog legitimately exposes
deterministic ``derived`` layers (e.g. ``terrain.slope``, ``physics.traction_margin``) to planning -- exactly as
design ss5.2 itself lists ``physics.sinkage`` under ``/derived`` while it stays planning-eligible -- so the ONLY
tier this row hard-forbids from planning is ``raw``. Tightening the remaining eligibility flags to the tier is a
separate LY-01/GW-03 re-derivation, not this governance row.
"""
from __future__ import annotations

from stewie.contracts.reconciliation import Proposal, ReconcileState

#: the closed tier set. A tier value outside this set is a taxonomy violation.
TIERS: frozenset[str] = frozenset({"raw", "derived", "belief", "world", "mission"})

#: the estimation ladder promotion advances along (mission is intent, deliberately off-ladder).
PROMOTION_LADDER: tuple[str, ...] = ("raw", "derived", "belief", "world")

#: the reconcile states that count as an "EG-08 accepted proposal" for a promotion (ACCEPTED, or already APPLIED).
_ACCEPTED_STATES: frozenset[ReconcileState] = frozenset({ReconcileState.ACCEPTED, ReconcileState.APPLIED})

#: every provenance token GW-03 (``routers.world._CONF_RANK``) recognizes -- a layer whose source_class carries
#: any of these DECLARES its provenance (=> declared uncertainty). Mirrored here (not imported) so this CORE
#: module stays a sink and never depends on the ``world`` service (EG-09); the ``test_layer_tier_enforcement``
#: drift guard asserts this set stays consistent with ``layer_confidence`` over the real catalog.
_RECOGNIZED_PROVENANCE: frozenset[str] = frozenset({
    "live", "observed", "measured", "reconciled", "sim_truth", "released", "derived", "estimated",
    "learned", "forecast", "belief", "prior", "user", "sim", "replay", "evidence"})

#: source_class provenance tokens that carry epistemic uncertainty (=> a belief the world model holds).
_BELIEF_TOKENS: frozenset[str] = frozenset({"belief", "forecast", "estimated", "learned", "prior", "observed"})
#: source_class provenance tokens of a pure, unprocessed sensor / truth stream.
_RAW_TOKENS: frozenset[str] = frozenset({"live", "replay", "sim", "sim_truth", "measured"})
#: intent domains -- plans + design/build orders.
_MISSION_DOMAINS: frozenset[str] = frozenset({"mission", "design"})
#: catalog ids that record an EXECUTED terrain change (design ss5.2 lists these under /mission).
_MISSION_CHANGE_IDS: frozenset[str] = frozenset({"map.changed_terrain", "evidence.before_after_dem"})


class LayerTierError(Exception):
    """Raised when a layer's declared eligibility contradicts its tier (e.g. a raw layer marked planning-valid)."""


class TierPromotionError(Exception):
    """Raised on an illegal tier promotion (a skip, a downgrade, an off-ladder move, or a missing/unaccepted
    EG-08 proposal)."""


def _tokens(layer: dict) -> set[str]:
    return {t for t in str(layer.get("source_class", "") or "").split("/") if t}


def layer_tier(layer: dict) -> str:
    """Classify one LY-01 catalog layer into its closed tier in :data:`TIERS`, from its declared ``domain`` +
    ``source_class``. Deterministic, total (always returns a valid tier), and a faithful reading of the REAL
    declared provenance -- no fabricated field.

    Precedence (strongest intent / strongest epistemic claim first, design ss5.2):
      1. an intent layer (mission/design domain, or an executed-terrain-change record) -> ``mission``;
      2. the approved authoritative terrain state (base DEM/CRS domain, or a reconciled product) -> ``world``;
      3. a robot-state layer, or any layer carrying an uncertainty token -> ``belief``;
      4. a deterministic transform (``derived`` token) -> ``derived``;
      5. a pure sensor/truth stream (only raw tokens) -> ``raw``;
      6. anything else (an evidence record with no provenance token) -> ``derived`` (a report product).
    """
    dom = str(layer.get("domain", "") or "")
    lid = str(layer.get("id", "") or "")
    toks = _tokens(layer)
    if dom in _MISSION_DOMAINS or lid in _MISSION_CHANGE_IDS:
        return "mission"
    if dom == "base" or "reconciled" in toks:
        return "world"
    # robot-state layers are the world model's BELIEF about the vehicle (pose/covariance/footprint/frustums),
    # even when their raw provenance is a live/sim stream -- they are consumed as belief, never as raw truth.
    if dom == "robot" or (toks & _BELIEF_TOKENS):
        return "belief"
    if "derived" in toks:
        return "derived"
    if toks and toks <= _RAW_TOKENS:
        return "raw"
    return "derived"


def carries_uncertainty(layer: dict) -> bool:
    """True iff the layer declares a recognizable provenance token (equivalently, a non-``unknown`` GW-03
    confidence class) -- i.e. it carries DECLARED uncertainty. An empty/unrecognized ``source_class`` reads
    honestly as ``False``."""
    return bool(_tokens(layer) & _RECOGNIZED_PROVENANCE)


def validate_layer(layer: dict) -> str:
    """Enforce the IN-02 tier gates on one layer; return its tier, or raise :class:`LayerTierError`.

    * a ``raw``-tier layer may NOT be planning- or release-eligible (raw streams are never planning-valid);
    * a ``belief``-tier layer that IS planning/release eligible must carry DECLARED uncertainty.
    """
    tier = layer_tier(layer)
    if tier not in TIERS:                                                     # defensive; layer_tier is total
        raise LayerTierError(f"{layer.get('id')!r}: tier {tier!r} not in closed set {sorted(TIERS)}")
    eligible = bool(layer.get("planning_eligible")) or bool(layer.get("release_execute_eligible"))
    if tier == "raw" and eligible:
        raise LayerTierError(
            f"{layer.get('id')!r}: a raw-tier layer is planning/release eligible -- raw sensor streams must be "
            f"estimated through to at least 'belief' before they can drive planning")
    if tier == "belief" and eligible and not carries_uncertainty(layer):
        raise LayerTierError(
            f"{layer.get('id')!r}: a belief-tier layer is planning/release eligible but declares no uncertainty")
    return tier


def validate_catalog(layers: list[dict]) -> dict[str, str]:
    """Validate every LY-01 catalog layer; return ``{id: tier}``. Raises :class:`LayerTierError` on the first
    layer whose eligibility contradicts its tier."""
    return {str(ly.get("id")): validate_layer(ly) for ly in layers}


def _is_accepted(proposal: Proposal | None) -> bool:
    return isinstance(proposal, Proposal) and proposal.state in _ACCEPTED_STATES


def promote_tier(current: str, target: str, proposal: Proposal | None) -> str:
    """Promote ``current`` -> ``target`` one rung forward along :data:`PROMOTION_LADDER`, carrying an EG-08
    ACCEPTED reconciliation proposal. Returns ``target``, or raises :class:`TierPromotionError`.

    A promotion is legal iff: both tiers are on the ladder (``mission`` is off-ladder intent), ``target`` is the
    single next rung above ``current`` (no skip, no downgrade, no self-loop), AND ``proposal`` is an EG-08
    proposal in state ACCEPTED/APPLIED. A belief->world promotion with no accepted proposal is therefore refused.
    """
    if current not in PROMOTION_LADDER:
        raise TierPromotionError(f"{current!r} is not on the promotion ladder {PROMOTION_LADDER}")
    if target not in PROMOTION_LADDER:
        raise TierPromotionError(f"{target!r} is not on the promotion ladder {PROMOTION_LADDER}")
    ci, ti = PROMOTION_LADDER.index(current), PROMOTION_LADDER.index(target)
    if ti != ci + 1:
        raise TierPromotionError(
            f"promotion {current!r} -> {target!r} is not a single forward rung along {PROMOTION_LADDER}")
    if not _is_accepted(proposal):
        state = proposal.state.value if isinstance(proposal, Proposal) else None
        raise TierPromotionError(
            f"promotion {current!r} -> {target!r} requires an EG-08 ACCEPTED proposal (got state={state!r})")
    return target
