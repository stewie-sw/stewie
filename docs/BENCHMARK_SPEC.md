# Benchmark specification — state acceptance under agent-induced change

**Status:** specification, pre-registered 2026-07-27. Implementation follows.
**Purpose:** this document exists to be written *before* the comparative runs, so that the fault
families swept are the families chosen in advance rather than the families that happened to favour
the rule. Changing it after comparative results exist requires recording the change and the reason.

## Why a new benchmark

No existing dataset supplies, together: an evolving reference state; per-agent action logs that
distinguish commanded from executed actions; asynchronous observations carrying declared uncertainty
and provenance; and controlled source failures. Each exists somewhere. The conjunction is what makes
action-induced evidence dependency measurable, and it is the conjunction that is missing.

The benchmark is designed to outlive the rule it was built to test. A different acceptance rule, a
different dependency model, or a different domain must be substitutable without touching the harness.

---

## 1. Evaluation integrity

The reference state is structurally unavailable to the system under evaluation. Estimates are frozen
to disk before the reference is opened. An executable attestation records that displacing the
reference by a large constant leaves every frozen estimate bit-identical; a dependence of the
estimate on the reference is therefore a test failure rather than a reviewer's inference.

This apparatus exists and is reused rather than rebuilt.

**Scenarios are content-addressed.** A reported number names the scenario hash that produced it. A
scenario whose content changes gets a new hash, so a result cannot silently drift onto different
inputs.

---

## 2. Pre-registered fault taxonomy

Seven families. The first two are implemented and swept; the third is added on the committee's
condition C4; the remainder are specified here and built in order.

| # | Family | Parameter | Status | Why it is in the set |
|---|---|---|---|---|
| F1 | Physical-model bias | bias $b$, metres | **implemented** | The channel the veto-only argument is about |
| F2 | Sensor fault | offset $d$, metres | **implemented** | The channel fixed precedence is blind to |
| F3 | **Sensor mis-calibration** | $\kappa$ = true $\sigma$ / declared $\sigma$ | **implemented** | Mis-calibration converts into abstention, not harm, provided $\sqrt{2k^2-1}\,\sigma_{\text{declared}} < \tau$. See the amendment below: the first version of this row gave the weaker symmetric condition and was wrong |
| F4 | Shared-ground concurrency | overlap fraction $d=\lvert D\rvert/n$, agent count $m$ | **partial, next** | The condition the dissertation exists for. Currently exercised via the correlation mask; needs sweeping as a first-class axis, especially at $m\ge 3$ where the superseded placeholder was optimistic |
| F5 | Delayed / out-of-order evidence | lag distribution | specified | Observation time, validity time and ingestion time must be distinguishable for acceptance to be well defined |
| F6 | Partial or misreported action execution | executed / commanded ratio | specified | $S(a)$ is itself uncertain when a commanded action was only partly performed |
| F7 | Duplicated evidence | duplication factor | specified | One reading counted twice is the degenerate case of dependency; a rule that cannot catch it cannot catch the general case |

### Amendment 2026-07-27 — F3 condition corrected

This document requires that a change made after results exist be recorded with its reason. One has
been made.

F3 was first reported with the fail-safe condition $k\,\sigma_{\text{declared}} < \tau$, noted as the
A5 resolvability inequality with its physics term removed. That governs only the **symmetric** case,
where every source is equally over-confident. Where a single source is over-confident and its
corroborator is honest, disagreement grows as $\sqrt{\kappa^2+1}$ rather than as $\kappa$, so
detection is deferred to $\kappa=\sqrt{2k^2-1}$ while the harm threshold is unmoved --- the reading
that gets accepted is the bad one.

The binding condition is therefore $\sqrt{2k^2-1}\,\sigma_{\text{declared}} < \tau$. At $k=4$,
$\sigma_{\text{declared}}=0.05$, $\tau=0.25$ the superseded condition certifies safety ($0.20<0.25$)
while the gate is measured harmed in **12 of 20** trials. The safety margin also narrows with gate
width and inverts before $k=4$, so a wide gate is not merely conservative.

Found by checking a doubt recorded in the previous iteration's journal rather than by a new result,
which is the intended use of that journal.

**Adversarial variants.** F1 and F3 have adversarial forms in which the parameter is chosen with
knowledge of the rule rather than fixed in advance. For a rule whose branches are published this is
the realistic threat model. Scheduled, not an extension.

**Abstention under adversarial input** is a distinct measurement, not a fault family: an adversary
who can inject one contradicting observation can hold the rule in abstention indefinitely without
ever causing a harmful acceptance. Safety and availability are separate properties and this
benchmark measures both.

---

## 3. Metrics

**Primary.** Harmful-acceptance rate: the share of trials in which a state is accepted whose error
against the withheld reference exceeds a stated tolerance $\tau$.

Reported as a **curve over $\tau$**, never as a rate at a single $\tau$. $\tau$ is a property of the
downstream physical operation and is declared per scenario; a single-threshold result is one the
author chose.

**Always reported alongside.** Abstention rate. A reduction in harmful acceptance bought by
abstaining more often is not a result, and the two numbers must appear together or neither is
meaningful.

**Secondary.** Accepted-state error; false-rejection rate; time to correction after a harmful
acceptance; rollback correctness; calibration error of the declared uncertainties; and, for the
scaling questions, storage, latency, and their growth in region size, agent count, and
action-history length.

---

## 4. Ablation ladder

Each condition removes exactly one element, so that any degradation attributes to that element.

1. No dependency correction — observations treated as conditionally independent
2. Dependency derived from communication topology only — the covariance-intersection position
3. No physical-consistency channel — physics never consulted
4. Physics treated as truth — the failure mode the abstain/reject distinction exists to prevent
5. Abstain collapsed into reject — three outcomes reduced to two
6. **Effective support fixed at $m$** — the C3 bound disabled, isolating what the bound buys

---

## 5. Negative controls

Controls test whether the *mechanism* produced the result, rather than extra information, extra
computation, or an implementation difference. Each has a predicted direction, stated here in advance;
a control that degrades the rule in an unpredicted direction is a finding about the rule.

| Control | Manipulation | Predicted effect |
|---|---|---|
| Provenance scramble | Randomise source labels | Effective support becomes uninformative; harmful acceptance rises toward the no-correction ablation |
| Prediction scramble | Replace the physical prediction with noise of the same scale | Physical-consistency branch fires at its false-positive rate; abstention rises, harmful acceptance does **not** |
| Evidence duplication | Present one observation twice as two sources | A rule that cannot detect this reports inflated support; C3 with a correct correlation mask should not |
| Action-log shuffle | Permute the action history while holding observations fixed | $D$ becomes wrong; if harmful acceptance is unchanged, the action history was not load-bearing and the central claim is in trouble |

The last is the strongest control in the set: it tests the dissertation's premise directly rather
than the rule's implementation.

---

## 6. Baselines

Substitutable through one interface, so an external group can add a ninth without touching the
harness.

Last-write-wins · timestamp priority · confidence-weighted fusion · probabilistic elevation fusion ·
inverse-variance fusion (physics as pseudo-measurement) · covariance intersection, the closest
competitor · trust-aware fusion · multi-hypothesis estimation without persistent candidates ·
the deployed fixed-precedence rule.

**Provenance is recorded per baseline.** Fixed precedence is a prior deliverable built for
operations before this question was posed. The inverse-variance comparator was built for this study.
Both are legitimate; what keeps the second honest is the withheld reference, not its provenance, and
the distinction is recorded rather than elided.

---

## 7. Domains

**Lunar.** Publicly available polar elevation products across several south-pole sites, differing in
relief and roughness. Real terrain at documented resolution and uncertainty.

**Terrestrial.** Public national lidar elevation products, with soil response from measured
pressure-sinkage and shear parameters in the published terramechanics literature. Gravity is a fixed
constant, not a fitted one.

Both are required. A result obtained in one leaves open whether the mechanism or the terrain produced
it. Neither requires a field site, testbed, industrial partner, or proprietary data.

---

## 8. Statistical treatment

Repeated trials with fixed seeds under each condition. Every trial within a level must differ — a
regression guard enforces this, because an earlier comparison held its injected fault constant across
twenty "trials" and varied only a channel the baseline never read, making its headline number a
restatement of a definition rather than a measurement.

Effect sizes with confidence intervals rather than significance alone. Correction for multiple
comparisons. The harmful-acceptance criterion is fixed before comparative runs.

---

## 9. Release

Open licence. Content-addressed release identity, so a published number names the exact state that
produced it. Baselines ship implemented against the interface, so the cost to an external group of
adding a method is bounded and small. Submitted to artifact-evaluation tracks; a failed artifact
evaluation is itself informative and would be reported.

---

## 10. What this specification does not yet fix

Stated so that later choices are visible as choices.

- **The scaling axes.** Region size, agent count and action-history length are named; their ranges
  are not, and should be set from what the terrain products actually support.
- **The lag distribution for F5.** Requires a defensible model of when observations arrive, which
  the current record does not contain.
- **Whether $\tau$ can be given a physical derivation** rather than being declared per scenario. If
  it can be tied to the tolerance a downstream operation actually requires, the primary metric
  becomes less author-dependent.
