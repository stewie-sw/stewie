"""[GATE6] Provenance- and physics-gated promotion of a candidate terrain state.

The baseline this must beat is ``stewie.twin.terrain_view`` layer 2, which is one line:

    z[m] = oh[m]

An observation overwrites as-built, which overwrites the pristine base. Fixed lexicographic
precedence, no uncertainty in the decision, no provenance weighting, no physical check, and no way
to decline. That is the single-authoritative-map control condition.

This module replaces the precedence rule with a DECISION. A candidate update carries its evidence,
and the gate returns one of:

    PROMOTE   accept the candidate as the operationally authoritative state
    REJECT    refuse it; the prior state stands
    ABSTAIN   the evidence cannot settle it; defer and gather more (NOT the same as reject --
              rejecting says "this is wrong", abstaining says "I cannot tell", and conflating them
              is what makes a binary gate fail under model misspecification)

Three inputs decide it, and the third is the one no charted work in the scoping review uses:

1. **Declared uncertainty.** Each evidence item carries a sigma. A disagreement inside the combined
   band is not a disagreement.
2. **Source reliability.** Per-source, and discounted over the action-induced correlation set from
   ``stewie.twin.shared_terrain``: two vehicles that both dug a cell do not supply independent
   evidence about it, so their agreement there is worth less than their agreement elsewhere.
3. **Terramechanics residual as contestable evidence (gap G-B).** The conserved authority predicts a
   deformation; the sensor observes one. The residual between them is evidence about BOTH. Crucially
   the physics is fallible: a large residual may mean a bad observation OR a misspecified model, and
   the gate must not resolve that ambiguity by trusting physics. When the residual is large and the
   physics cannot be corroborated, the gate ABSTAINS rather than rejecting a possibly-good
   observation. Treating the model as truth is exactly the failure this is built to avoid.

Scope: this is the decision procedure only. It does not merge fields, prune branches, or prove
anything. It exists to test one claim: that a gated promotion measurably beats fixed precedence on
harmful acceptance, without paying for it in false rejections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from stewie.twin.effective_support import conservative_effective_support


class Decision(str, Enum):
    PROMOTE = "promote"
    REJECT = "reject"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class Evidence:
    """One typed, uncertain, source-tagged claim about a set of cells.

    ``kind`` is the evidence class: "observation" (a sensor reading), "physics" (the conserved
    authority's predicted deformation), or "action" (a reported executed action). ``sigma_m`` is the
    declared 1-sigma height uncertainty [m]; it is what makes a disagreement meaningful or not.
    ``reliability`` in (0, 1] is the prior trust in this source.

    ``observed_at`` is when the reading was TAKEN, which is neither when it arrived nor when it is
    being judged. Without it, a reading describing a surface that has since been dug away is
    indistinguishable from one describing the surface as it is now. Optional, because evidence
    predating the temporal model still has to be judged; where it is absent no staleness check runs.
    """

    source: str
    kind: str
    values: np.ndarray            # per-cell height [m] over the candidate region
    sigma_m: float
    reliability: float = 1.0
    observed_at: float | None = None   # when the reading was taken, not when it arrived

    def __post_init__(self) -> None:
        if self.kind not in ("observation", "physics", "action"):
            raise ValueError(f"unknown evidence kind {self.kind!r}")
        if not (self.sigma_m > 0.0):
            raise ValueError(f"{self.source}: sigma_m must be > 0 (got {self.sigma_m})")
        if not (0.0 < self.reliability <= 1.0):
            raise ValueError(f"{self.source}: reliability must be in (0, 1] (got {self.reliability})")
        if not np.all(np.isfinite(np.asarray(self.values, dtype=float))):
            raise ValueError(f"{self.source}: values must be finite")


@dataclass
class PromotionResult:
    decision: Decision
    reason: str
    residual_rms_m: float = 0.0
    tolerance_m: float = 0.0
    n_correlated: int = 0
    effective_n: float = 0.0
    detail: dict = field(default_factory=dict)


def _combined_tolerance(a: Evidence, b: Evidence, k: float) -> float:
    """Disagreement is only real beyond the two declared uncertainties added in quadrature."""
    return k * float(np.hypot(a.sigma_m, b.sigma_m))


def stale_sources(evidence: list[Evidence], last_modified_at: float | None) -> list[str]:
    """[F5] Sources whose reading predates the last action on the ground it describes.

    Such a reading is not wrong. It is a correct description of a surface that no longer exists, and
    the distinction matters: admitted as contradicting evidence it makes the rule decline while a
    correct current reading sits unused, which is safe and useless. Recognised as stale, it is
    dropped and the current reading gets through.

    Returns the empty list when the modification time or the observation times are unknown, so that
    absent temporal information changes nothing rather than being guessed at.
    """
    if last_modified_at is None:
        return []
    return [e.source for e in evidence
            if e.observed_at is not None and e.observed_at < last_modified_at]


def evaluate(candidate: np.ndarray,
             evidence: list[Evidence],
             *,
             prior: np.ndarray | None = None,
             correlation_mask: np.ndarray | None = None,
             last_modified_at: float | None = None,
             k_sigma: float = 3.0,
             min_effective_support: float = 1.0,
             support_model: str = "c3") -> PromotionResult:
    """Decide whether ``candidate`` may become the authoritative state.

    ``prior`` is the state that stands if the candidate is refused. ``correlation_mask`` marks cells
    where evidence is action-correlated (from ``shared_terrain.correlation_mask``); support over
    those cells is discounted rather than counted independently.

    ``support_model`` selects how that discount is computed: ``"c3"`` is the conservative bound and
    the default; ``"linear"`` reinstates the superseded discount and ``"none"`` disables correction
    entirely. The latter two exist so the ablation ladder can isolate what the bound actually buys,
    and should not be used to decide anything.
    """
    cand = np.asarray(candidate, dtype=float)
    if not np.all(np.isfinite(cand)):
        return PromotionResult(Decision.REJECT, "candidate contains non-finite heights")

    # [FIX 2026-07-28] The candidate was previously read for its SHAPE and finiteness and for
    # nothing else. Every branch below reasons about the evidence -- observation against physics,
    # observation against observation -- and none of them ever looked at the thing being promoted.
    # A flat plane at zero, 1559 m from the surface, was accepted on three good readings of real
    # terrain, because the readings agreed with each other and with the model and nobody asked what
    # the candidate was.
    #
    # The theorem's whole structure is "every accepted state is an observation", which is what makes
    # its error governed by sigma_o and independent of the model bias. That sentence was true of the
    # experiments, which all pass obs[0].values, and false of the function they call. Enforced here
    # rather than assumed: the candidate must BE one of the offered observations.
    _observations = [e for e in evidence if e.kind == "observation"]
    if _observations and not any(
            np.asarray(e.values, dtype=float).shape == cand.shape
            and np.array_equal(np.asarray(e.values, dtype=float), cand)
            for e in _observations):
        return PromotionResult(
            Decision.REJECT,
            "candidate is not any of the offered observations: the rule promotes an observation, "
            "and a state assembled from something else is outside what it can vouch for")
    if not evidence:
        return PromotionResult(Decision.ABSTAIN, "no evidence offered")

    # [F5] Drop readings taken before the last action on this ground. They are correct about a
    # surface that is gone, and admitting them as contradicting evidence makes the rule decline
    # while a current reading sits unused.
    stale = set(stale_sources(evidence, last_modified_at))
    if stale:
        evidence = [e for e in evidence if e.source not in stale]
        if not evidence:
            return PromotionResult(Decision.ABSTAIN,
                                   "all evidence predates the last action on this ground")

    obs = [e for e in evidence if e.kind == "observation"]
    phys = [e for e in evidence if e.kind == "physics"]
    if not obs:
        return PromotionResult(Decision.ABSTAIN, "no observation among the evidence")

    # --- effective support: correlated cells do not count as independent corroboration ----------
    mask = (np.asarray(correlation_mask, dtype=bool) if correlation_mask is not None
            else np.zeros(cand.shape, dtype=bool))
    n_corr = int(mask.sum())
    d = (n_corr / cand.size) if cand.size else 0.0
    # [C3] Conservative effective support: rho=1 on the shared cells, no correlation model assumed.
    # Replaces a linear-in-area discount that was optimistic below d=(m-2)/(m-1) for m>=3, i.e. that
    # overstated independent support in exactly the many-agent regime this gate exists for.
    mean_reliability = sum(e.reliability for e in obs) / len(obs)
    if support_model == "c3":
        raw_support = conservative_effective_support(len(obs), d)
    elif support_model == "linear":                 # the superseded discount, for ablation only
        raw_support = len(obs) * (1.0 - d)
    elif support_model == "none":                   # ablation 6: no dependency correction at all
        raw_support = float(len(obs))
    else:
        raise ValueError(f"unknown support_model {support_model!r}")
    effective_n = raw_support * mean_reliability
    frac_independent = 1.0 - d

    # --- physics as CONTESTABLE evidence (G-B) --------------------------------------------------
    residual_rms = 0.0
    tol = 0.0
    physics_disagrees = False
    # [FIX 2026-07-28] Only phys[0] was consulted, so a second physical model was silently ignored
    # and which one that was depended on list order. Physics may only veto, so the conservative
    # composition is that ANY model disagreeing is a veto: reading fewer models can only ever miss
    # an objection, never manufacture one, which keeps the veto-only property intact.
    if phys:
        o = obs[0]
        worst = None
        for p in phys:
            resid = np.asarray(o.values, dtype=float) - np.asarray(p.values, dtype=float)
            rms = float(np.sqrt(np.mean(resid ** 2)))
            this_tol = _combined_tolerance(o, p, k_sigma)
            if rms > this_tol:
                physics_disagrees = True
            if worst is None or rms - this_tol > worst[0] - worst[1]:
                worst = (rms, this_tol)
        residual_rms, tol = worst

    # --- corroboration among observations --------------------------------------------------------
    # [FIX 2026-07-28] This compared obs[0] against obs[1] only, so the verdict depended on the
    # ORDER of a list with no defined order. Measured on [bad, bad, good]: two of six permutations
    # promoted a 0.900 m error, because the two faulty readings happened to be adjacent and agreed
    # with each other. Every pair is compared now, and a single dissenting source is enough to
    # withhold corroboration -- which is what "the observations corroborate each other" has to mean
    # if the sentence is to bear the weight the override branch puts on it.
    obs_disagrees = False
    for i in range(len(obs)):
        for j in range(i + 1, len(obs)):
            a, b = obs[i], obs[j]
            gap = float(np.sqrt(np.mean(
                (np.asarray(a.values, float) - np.asarray(b.values, float)) ** 2)))
            if gap > _combined_tolerance(a, b, k_sigma):
                obs_disagrees = True
                break
        if obs_disagrees:
            break

    # Which regime the call is in, and it matters for what any soundness claim covers. A veto that
    # cannot fire is not a veto: with no physics prediction offered, the residual test below never
    # runs and the rule degenerates to "accept what corroborated observations say", which is the
    # fusing baseline this design exists to beat. Reported rather than silently folded into the
    # agreeing case, because the branch-4 derivation assumes the residual test PASSED, not that it
    # was skipped.
    veto_available = bool(phys)
    detail = {"n_obs": len(obs), "n_physics": len(phys), "frac_independent": frac_independent,
              "physics_disagrees": physics_disagrees, "obs_disagrees": obs_disagrees,
              "veto_available": veto_available}

    # --- the decision ----------------------------------------------------------------------------
    if obs_disagrees:
        # two sensors contradict each other beyond their declared bands: nothing here settles it
        return PromotionResult(Decision.ABSTAIN, "observations contradict each other beyond their declared uncertainty",
                               residual_rms, tol, n_corr, effective_n, detail)

    if physics_disagrees:
        # The residual is real. It means EITHER the observation is wrong OR the model is misspecified,
        # and this gate deliberately refuses to settle that by trusting the model. Corroboration is
        # what breaks the tie -- but only INDEPENDENT corroboration.
        #
        # [FIX 2026-07-27] This branch previously tested ``len(obs) >= 2``, a raw count, while its own
        # reason string claimed the observations were independent. Where several agents have modified
        # the same ground, their readings carry a common error and therefore AGREE WHILE ALL BEING
        # WRONG. The old test read that counterfeit agreement as grounds to overrule a correct model,
        # promoting the bad reading and blaming the physics: measured 9-13 harmful acceptances in 20
        # trials, with the model wrongly named the outlier in 11-17 of them.
        #
        # Requiring effective rather than raw support closes it. This is also what makes m_eff
        # load-bearing for the veto-only argument itself, rather than an extra safety check bolted on
        # afterwards: the authority to overrule the model comes from independence, and m_eff is the
        # only thing that measures it.
        # BOTH conditions, and the pair matters. The count alone was the original defect; effective
        # support alone is not enough either, because a single observation has m_eff = 1 and would
        # clear a threshold of 1.0, letting one unchallenged reading dismiss the model. Overruling
        # the physics requires more than one source AND those sources being effectively independent.
        if len(obs) >= 2 and effective_n >= min_effective_support and not obs_disagrees:
            return PromotionResult(Decision.PROMOTE,
                                   "physics residual exceeds tolerance, but independent observations "
                                   "corroborate: the model is the outlier, not the observation",
                                   residual_rms, tol, n_corr, effective_n, detail)
        return PromotionResult(Decision.ABSTAIN,
                               "physics residual exceeds the combined declared uncertainty and no "
                               "independent observation corroborates: cannot distinguish a bad "
                               "observation from a misspecified model, and effective support is "
                               "insufficient to overrule it",
                               residual_rms, tol, n_corr, effective_n, detail)

    if effective_n < min_effective_support:
        return PromotionResult(Decision.ABSTAIN,
                               f"effective independent support {effective_n:.2f} below required "
                               f"{min_effective_support:.2f} (action-correlated cells discounted)",
                               residual_rms, tol, n_corr, effective_n, detail)

    # [FIX 2026-07-28] This return is reachable in TWO regimes and previously reported both with the
    # same sentence. Either the physical model was offered and agreed -- the case the safety argument
    # covers -- or no model was offered at all, in which case nothing was checked against anything
    # and ``residual_rms``/``tolerance`` are both a sentinel 0.0 indistinguishable from perfect
    # agreement. Saying "consistent within declared uncertainty" of the second case asserted a check
    # that never ran. The decision is unchanged; only the claim made about it is now accurate.
    if veto_available:
        return PromotionResult(Decision.PROMOTE, "evidence consistent within declared uncertainty",
                               residual_rms, tol, n_corr, effective_n, detail)
    return PromotionResult(Decision.PROMOTE,
                           "observations corroborate and support is sufficient, but NO physical "
                           "model was offered: nothing vetoed this and nothing could have",
                           residual_rms, tol, n_corr, effective_n, detail)


def baseline_fixed_precedence(prior: np.ndarray, observation: np.ndarray,
                              mask: np.ndarray | None = None) -> np.ndarray:
    """The control condition, reproducing ``terrain_view`` layer 2: the observation overwrites,
    unconditionally. No uncertainty, no provenance, no physical check, no way to decline."""
    z = np.array(prior, dtype=float, copy=True)
    o = np.asarray(observation, dtype=float)
    m = np.ones(z.shape, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    z[m] = o[m]
    return z
