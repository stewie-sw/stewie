# Benchmark specification — state acceptance under agent-induced change

**Status:** fault probes and theorem-facing research harness implemented; the integrated,
two-domain, multi-robot D4 benchmark and frozen release artifact remain incomplete.
**Purpose:** this document exists to be written *before* the comparative runs, so that the fault
families swept are the families chosen in advance rather than the families that happened to favour
the rule. Changing it after comparative results exist requires recording the change and the reason.

The implemented rows below are component probes, not a claim that the complete benchmark has run.
In particular, they do not exercise the live `POST /twin/resync` ingestion path, which currently
bypasses the theorem-facing promotion rule.

## Why a new benchmark

No existing dataset supplies, together: an evolving reference state; per-agent action logs that
distinguish commanded from executed actions; asynchronous observations carrying declared uncertainty
and provenance; and controlled source failures. Each exists somewhere. The conjunction is what makes
action-linked evidence dependency measurable, and it is the conjunction that is missing.

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

Nine axes: the seven original families plus F6b and F8, which were added by
recorded amendment. All are implemented; limitations are stated in amendment 9.

| # | Family | Parameter | Status | Why it is in the set |
|---|---|---|---|---|
| F1 | Physical-model bias | bias $b$, metres | **implemented** | The channel the veto-only argument is about |
| F2 | Sensor fault | offset $d$, metres | **implemented** | The channel fixed precedence is blind to |
| F3 | **Sensor mis-calibration** | $\kappa$ = true $\sigma$ / declared $\sigma$ | **implemented** | The accepted state is now the two-source mean. For \(k\geq1\), symmetric and asymmetric detection-before-expected-harm order both reduce to $k\sigma<\sqrt{2}\tau$; an overconfidence-onset reading also needs \(\tau>\sigma/\sqrt2\). This is an effect-size crossover, not a guarantee |
| F4 | Shared-ground concurrency | overlap fraction $d$, source graph, common shift $S$ | **implemented** | A labelled common observation fault is injected on action-linked cells. Harm follows an exact noncentral chi-square under the stated fixed-shift model; graph components determine the aggregate variance bound |
| F5 | Delayed / out-of-order evidence | lag distribution | **implemented** | The gap was availability, not safety: the physics channel already caught a lone stale reading, but a stale reading present alongside a current one blocked it 100% of the time. Dating evidence against the action history restores availability at no cost in harm |
| F6 | Partial or misreported action execution | log fidelity (recall) | **implemented** | Under-reporting is the direction that causes *harm*, and the failure is a cliff at the support threshold, not a decay. Tolerated to 50\% fidelity; broken by 25\%. The row first called this "the dangerous direction"; see amendment 7 --- it is the *less* sensitive one |
| F8 | **Partial sensor coverage** | coverage fraction $\times$ graph geometry | **implemented** | NaN denotes an unobserved cell; support and residuals use actual pair coverage, and promotion returns an explicit patch mask |
| F6b | **Action log fabricates overlap** | log precision (false-positive rate) | **implemented** | The closed-form $d_{\mathrm{crit}}$ result is retained for the legacy global-mask scalar; it does not fully characterize the repaired graph decision |
| F7 | Duplicated evidence | duplication factor | **implemented** | Duplicate source identities are rejected. Relabelled duplication remains an upstream source-integrity assumption because it leaves no trace in the action graph |

### Amendment 2026-07-27 (1) — F3 condition corrected

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

### Amendment 2026-07-27 (2) --- F4 exposed a free parameter

The support threshold was chosen by hand (2.0). That leaves a window in which the accepted state is
already harmful but the support test has not yet fired, because the threshold was set independently
of $\tau$. Requiring the test to fire at the harm onset removes the freedom:

$$d_{\text{harm}} = \frac{\tau^2-\sigma_o^2}{\text{shared}^2}, \qquad
  \text{threshold} = \frac{m}{1 + d_{\text{harm}}(m-1)}$$

Measured at $m=3$, $\sigma_o=0.05$, $\tau=0.25$, shared error 0.6 m: the hand-picked 2.0 fires only
at $d=0.25$ and leaves **31** harmful acceptances across the sweep; the derived 2.25 fires at
$d=0.167$ and leaves **5**. The bound was never the problem.

This is the third parameter in this work that needed deriving rather than choosing, after the A5
gate width and the F3 fail-safe condition. Recorded as a pattern rather than three incidents.

### Amendment 2026-07-27 (3) --- F4 exposed a defect in the rule, not only in a parameter

The first F4 sweep modelled the physics channel as sharing the common error, so it agreed with the
biased sensors and was blind. That is one defensible reading. The other, and the physically apt one
for G-A --- whose mechanism is dependence among *observation* errors --- is that the common error is a
**sensing artefact**: every sensor mis-sees the disturbed surface the same way, so the model predicts
the true surface and disagrees with all of them.

Under that model the rule was **harmed in 9 to 13 trials of 20**, and named the model the outlier in
11 to 17. The cause was a single line. The physics branch tested `len(obs) >= 2`, a raw count, while
its own reason string claimed the observations were *independent*. Where agents share ground their
readings carry a common error and therefore agree while all being wrong, and the branch read that
counterfeit agreement as licence to overrule a correct model.

Requiring `len(obs) >= 2` **and** `m_eff >= threshold` closes it: 0 harmful and 0 wrongly-blamed from
the harm onset onward. Both conditions are needed --- effective support alone is insufficient, since
a single observation has $m_{\text{eff}}=1$ and would clear a threshold of 1.0.

**Consequence for the argument.** The dependency correction is not a safety check added on top of the
veto-only design; it is what licenses the design's central move. The authority to overrule the
physical model comes from independence, and $m_{\text{eff}}$ is the only thing that measures it.

Both physics models are now selectable in the sweep, because the choice changes the conclusion and
should not be silent.

### Note 2026-07-27 --- F5 gave the action history a second job

The temporal fix does not add a new source of information. The action history already records the
interval during which each cell was modified, so it can date the ground a reading describes. That
lets a stale reading be **dropped** rather than admitted as a contradiction.

The action history therefore does two distinct things in this design: it yields $D$, and through it
$m_{\text{eff}}$, which says how much of the agreement between readings is real; and it dates the
evidence, which says whether a reading is about the surface that currently exists. Both are cases of
the same claim --- that the record of what the machines did carries information the readings alone
do not.

One prediction was wrong and is recorded as such. I expected a lone stale reading to be accepted and
cause harm. It is not: the model predicts the current surface, disagrees with the stale one, and with
no corroboration the rule declines. **The temporal gap was never a safety gap.**

### Amendment 2026-07-28 (6) --- a regime the taxonomy did not name

The seven families all vary *what the evidence says*. None of them varies *whether the physical
model is present at all*, and that turns out to be a regime of its own rather than a corner of F4.

The acceptance rule reaches its agreeing branch two ways. Either the model was offered and the
residual test passed --- the case the derivation covers --- or no model was offered, the residual
test never ran, and `residual_rms` and `tolerance` are both a sentinel `0.0` indistinguishable from
perfect agreement. **A veto that cannot fire is not a veto**: in that regime the design degenerates
into the fusing baseline it exists to beat.

Measured, shared error injected across two agents on real Haworth terrain, $\tau = 0.25$ m:

| common error | no dependency mask | mask at $d = 0.25$ |
|---|---|---|
| 0.20 m | 0/20 harmful | 0/20 |
| 0.30 m | **20/20** | 0/20 |
| 0.90 m | **20/20** | 0/20 |
| 10.0 m | **20/20** | 0/20 |

Unprotected, the regime **does not degrade with the fault; it is indifferent to it.** A ten-metre
error is accepted as readily as a thirty-centimetre one, so harm is bounded by what was injected
rather than by anything the rule does.

**Why this is an amendment and not a new family.** It is not a fault in the evidence; it is a
deployment condition under which the mechanism under test is absent. It is added as a **negative
control on the harness**: every family must be swept with the model present, and the model-absent
sweep is what establishes that the measured protection comes from the veto rather than from the
harness. Any future family reporting a protective effect without the model present should be
suspected of measuring something else.

**Assumption A7 (veto availability)** --- a physical prediction is offered whenever a promotion is
evaluated --- is added to the theorem's hypotheses. It is **not enforced in the rule**.

**And it is false on this platform.** Checked by running the resolver, not by reading it:
`resolve_live_backend` **refuses** to supply a physics model for a LIVE mission when the model has
no validated profile for the body --- confirmed refusing `bennu` and `phobos`, resolving `moon`.
That refusal is deliberate and correct: an unvalidated model must not drive real hardware.

So two components, each individually sound, compose into a system that is not:

| component | on an unvalidated body | correctness |
|---|---|---|
| `resolve_live_backend` | supplies no model | fails **closed** --- right |
| `evaluate` | accepts whatever is corroborated | fails **open** --- wrong |

**The refusal meant to protect the mission is exactly what removes the veto**, and it does so on the
least familiar terrain.

**The obvious repair loses.** Enforcing A7 --- abstain when no model is available --- was recommended
and then measured. Forty sequential promotions on terrain that genuinely moves because the agents
excavate it:

| policy | harmful | abstained | mean map error |
|---|---|---|---|
| accept on corroboration, log unread | 12 | 0/40 | 0.271 m |
| **enforce A7** | **0** | 40/40 | **1.718 m** |
| **require the mask** | **0** | 12/40 | **0.067 m** |

Enforcement is safe and useless: never harmful because it never accepts, and its map ends seven times
worse than the policy it replaced. **Requiring the mask rather than the model wins on both axes**,
and enforcement wins only below a dig rate near one promotion in twenty --- the regime where the twin
has nothing to do.

**Harness consequence.** The model-absent sweep must be run as a *policy* comparison, not a single
system, or it will read as "the rule is unsafe without a model" when the measured statement is "the
rule is unsafe without a model *or* a faithful action log, and the log is the cheaper requirement."

The reason it went unnoticed is worth recording for the harness: across the whole twin suite only
5 of 6,129 rule evaluations omitted the physical model, and 3 of those accepted. **A path exercised
0.08% of the time carried an unbounded failure**, and every one of those 5 calls came from tests
written to probe the support mechanism in isolation, which is exactly the setting that made the
omission look deliberate.

### Amendment 2026-07-28 (7) --- F6 covered one direction and called it the dangerous one

F6 sweeps a log that **omits** real shared ground. It never makes the log report an overlap that did
not happen, so nothing in the family could contradict its own docstring's claim that under-reporting
is "the dangerous direction". That claim was a scoping assumption, and on sensitivity it is wrong.

**F6b** adds the missing direction. The evidence is genuinely independent and entirely within its
declared sigma; only the record of what produced it is wrong.

| fabricated overlap | abstained | harmful |
|---|---|---|
| 0% | 0/20 | 0 |
| 10% | 0/20 | 0 |
| 20% | **20/20** | 0 |
| 50% | 20/20 | 0 |
| 100% | 20/20 | 0 |

**Roughly four times more sensitive than omission** --- 20% against 50% --- and it fails to refusal
rather than to harm. That is not the same as harmless: total abstention leaves a twin that never
learns the ground moved, which the A7 repair comparison measured as the worst map error of the
available policies on a worked site.

**Both cliffs are the same constant, and it is closed form.** Solving
$m/(1 + d(m-1)) = \text{threshold}$ gives

$$d_{\text{crit}} = \frac{m/\text{threshold} - 1}{m - 1}$$

and the decision flips there exactly --- verified per trial to within one cell for $m$ from 2 to 8
(`effective_support.log_error_tolerance`). The constant reads two ways at once: how much fabrication
the rule tolerates, *and* how much real dependency it accepts. **Raising the threshold to buy safety
against an omitting log lowers $d_{\text{crit}}$ and buys fragility against a fabricating one, in
exact proportion.** No setting is robust to both; there is only a choice about which way to fail.

**Why this is an amendment rather than a new family.** It is the same fault --- an inaccurate action
log --- swept along the axis the original family fixed at zero. Recorded here because it corrects a
claim the specification itself made, which the specification's own rule requires.

**Method note for the harness.** A first pass swept the fabrication *probability* and read every
cliff about two percentage points high, consistently. A Bernoulli mask makes the realized fraction a
random variable, so requiring all trials to abstain measures the upper tail rather than the
boundary. Sweep the realized fraction when the quantity under test is a threshold.

### Amendment 2026-07-28 (8) --- coverage is a fault axis and the taxonomy has no row for it

Found by asking what the real ingest path would hand the rule, rather than by extending an existing
family.

**The perception path emits partial fields by design.** `runtime/replay_loop.py:88` computes
`valid = np.isfinite(z).mean()` and carries it as `coverage_fraction`, because parts of the field
are never observed. **The promotion rule cannot represent that**: the `Evidence` guard raises on any
non-finite value, so a realistic reading cannot be constructed. The subsystems do not connect.

That is the A7 shape again --- each component internally consistent, incompatible at the seam --- and
it means every measurement in this benchmark uses fully covered observations, which no real sensor
produces. **The coverage regime of every result so far is 100%, and it was never stated.**

**The failure is not only availability.** The rule computes $d = n_{\text{corr}}/\lvert
\text{candidate}\rvert$, over the whole array. The denominator that matters is the number of cells
actually observed, since those are the only cells corroboration was computed over.

| coverage | $m_{\text{eff}}$, full grid | $m_{\text{eff}}$, observed cells | verdict |
|---|---|---|---|
| 100% | 2.31 | 2.31 | agree |
| 50% | 2.31 | **1.88** | **accepts what it should refuse** |
| 35% | 2.31 | 1.62 | accepts what it should refuse |
| 25% | 2.31 | 1.37 | accepts what it should refuse |

*(three agents, threshold 2.0, true dependency 15% of the grid)*

**The correlation that causes this is the default, not an adversarial choice.** Coverage and
disturbance have the same cause: where the machines are. They churn the ground they stand on and
they see the ground they stand on, so a sensor preferentially observes exactly the cells its own
vehicle disturbed. Under coverage *uncorrelated* with dependency the two denominators agree, so the
finding is about the correlation rather than about partial coverage as such.

**Status: latent, not live.** The rule fails closed. It becomes live the moment the perception path
is connected. The corrected denominator is implemented and measured as
`effective_support.coverage_aware_support` and is deliberately **not wired in**: doing so requires
admitting observations with unobserved cells, which changes what inputs the rule accepts rather than
how it weighs them, and that is a design decision.

**Open beyond the denominator.** With partial coverage the residual and corroboration comparisons
must run over the *jointly* observed cells of each pair, and different pairs then have different
support sets. Whether a scalar $m_{\text{eff}}$ can survive that is the same
scalar-versus-structure question, arriving from a third direction.

### Amendment 2026-07-28 (10) --- the theorem's premise needed a gate, not a sentence

The rebuilt result rests on R1: the accepted value is a function of the observations alone. The Lean
proof encodes R1 in the candidate's *type*, so it establishes that the conclusion follows from the
premise and cannot establish that the code satisfies it.

Checked by mutating the live rule:

| violation | caught by the suite? |
|---|---|
| blend 1% of the physics prediction into the accepted value | **yes**, 8 tests |
| use physics to **fill cells no sensor observed** | **no**, 302/302 passed |

The second is the tempting mistake, it lives on the partial-coverage path that F8 established is the
only path a real sensor produces, and it was already forbidden in writing twice --- "unobserved
cells are not silently filled", "never fill missing cells as part of the theorem" --- with nothing
testing either sentence.

`test_r1_enforcement.py` closes it and is itself mutation-tested: 8 of its 14 fail under the
violation while the rest of the suite still passes. **A gate that has not been shown to fail against
the defect it targets is not evidence of anything**, and this benchmark should hold its own tests to
that standard from here.

**Design point surfaced while building it.** The override branch requires two distinct dependency
components at *every* promoted cell, so one cell with a single observer makes the whole patch
un-overridable. Correct and conservative, but it means override availability is set by the
worst-covered cell in the patch rather than the average, and it is easy to walk into by accident.

### Amendment 2026-07-27 (5) --- F7 establishes where the mechanism stops

All seven families are now implemented. The last one draws a boundary rather than adding a defence,
and the boundary is sharp: a faulty reading presented once is declined in every trial; the same
reading relabelled as a second source is accepted in every trial and harmful in all of them.

$m_{\text{eff}}$ is a function of the action history. Duplication changes the evidence set and not
the action history, so the correction is identical in both cases while the real independent support
has halved. The two copies then agree perfectly --- they are the same numbers --- so corroboration is
satisfied by construction and the duplicated reading overrules a correct model.

**This is a scope statement, not a defect to be fixed inside $m_{\text{eff}}$.**
This amendment originally called the relation action-induced dependency;
Amendment 9 corrects that causal wording to action-derived
possible dependency. Detecting duplication requires source-identity integrity,
a different guarantee supplied by the evidence pipeline rather than by a
dependency measure derived from actions. It was recorded as assumption A6 in
the superseded theorem sketch; source integrity is R3 in the repaired theorem.

**Adversarial variants.** F1 and F3 have adversarial forms in which the parameter is chosen with
knowledge of the rule rather than fixed in advance. For a rule whose branches are published this is
the realistic threat model. Scheduled, not an extension.

**Abstention under adversarial input** is a distinct measurement, not a fault family: an adversary
who can inject one contradicting observation can hold the rule in abstention indefinitely without
ever causing a harmful acceptance. Safety and availability are separate properties and this
benchmark measures both.

### Amendment 2026-07-28 (9) — accepted-state and theorem rebuild

This amendment supersedes the mathematical interpretation, but not the audit
history, of amendments 1–8.

**Accepted object.** The old rule selected one observation while `m_eff`
described the mean. The repaired rule has no external candidate slot. After
metadata filtering it constructs the plain mean of every admitted observation,
and every promotion returns that mean plus its coverage mask. Physics may veto
but cannot select a source subset, assign weights, fill cells, or alter values.

**Why A-prime was rejected.** The all-pairs rule has no unique
“corroborating subset.” A largest-clique interpretation can choose two agreeing
bad readings over an honest dissent. On real Haworth terrain, 400 controlled
trials with a one-source alternating-sign 0.03 m offset near the pair threshold
gave RMS 0.0305 m for the plain mean, 0.0362 m
for the selected mean, and 0.0350 m from the selected-subset variance formula.
Value-dependent selection made the identity inexact and discontinuous.

**Graph support.** Pairwise per-cell source edges are converted into connected
components. Component sizes \(q_\ell\) give

\[
m_{\mathrm{eff},j}=m_j^2/\sum_\ell q_\ell^2.
\]

For unequal declared sigmas the implemented variance bound is

\[
v_j=m_j^{-2}\sum_C\left(\sum_{i\in C}\sigma_{ij}\right)^2.
\]

This requires calibrated marginal variances and zero cross-component
covariance. Dependence inside a component is unrestricted. The action history
is conservative provenance for possible dependency; shared physical action
does not itself correlate sensor noise conditional on the actual post-action
surface.

The analytic expression permits cell-varying \(\sigma_{ij}\). The current
`Evidence` representation supplies one scalar \(\sigma_i\) per source and
therefore implements the special case \(\sigma_{ij}=\sigma_i\) on that
source's observed cells. Per-cell uncertainty fields are not yet accepted.

The graph restores source-pair structure, not spatial geometry. The regional
harmonic support and \(V=n^{-1}\sum_jv_j\) are unchanged by permuting cells
with the same component-size multiset. A geometry-sensitive tail requires
spatial covariance or neighbourhood structure; the old shuffle limitation
therefore remains.

**Repaired bound.** Every successful return contains the observation mean
\(c\), so for arbitrary physics bias \(b\),

\[
\{\text{promote and harmful}\}\subseteq\{c\text{ is harmful}\}.
\]

With \(V=n^{-1}\sum_jv_j\), Markov gives

\[
\Pr(\text{harmful promotion})\le\min(1,V/\tau^2).
\]

The old branch-4 proof was invalid: a realised residual contains arbitrary
\(b\), which can cancel a harmful observation error. The old A5
resolvability condition is neither required for this theorem nor sufficient
against arbitrary bias.

**Gate calibration.** Production RMS comparisons use chi-square quantiles
with a Bonferroni family-wise correction. At \(n=1024\) and family error
\(10^{-3}\), the one-comparison multiplier is approximately 1.0687. A
separately named effect-size multiplier is retained for controlled sweeps.
The false-alarm interpretation requires independent Gaussian standardised
residual cells and a correct residual covariance model, including
observation--physics cross-covariance. These are gate-calibration assumptions,
not assumptions of the arbitrary-bias theorem.

**Registered-sweep recalibration result.** Re-running the same 20 seeds at
model biases \(0,0.5,1,2,4\) m changed neither harm nor availability: both
threshold modes produced 0 harmful and 0 abstentions at every level. At sensor
offsets \(0,0.20,0.30\) m, both modes again produced 0 harmful; the legacy
\(k=3\) effect-size gate abstained \(0,0,20\) times, while the chi-square gate
abstained \(0,20,20\) times. The headline harm separation survives, but the
availability curve does not remain unchanged.

**C7.** For a deterministic common shift \(S\) on \(n_D\) cells and aggregate
independent Gaussian noise variance \(s^2\),

\[
n\,\mathrm{RMS}^2/s^2\sim\chi'^2_n(n_D S^2/s^2).
\]

The former square-root expression is expected MSE, not a sharp onset. If the
common amplitude is one Gaussian latent variable, the unconditional law is a
weighted chi-square.

**C8.** The common magnitude is not observable from mutually agreeing
readings. The threshold mapping now requires an explicitly assumed
`shared_error_bound_m` and is labelled offline sensitivity analysis. Deployment
needs a justified bound, an independent reference, or abstention on
single-component cells. The mapping refuses a configuration whose independent
observation mean already reaches the harm threshold in expected MSE, because
no support cutoff can repair that baseline regime.

**Coverage and ordering.** NaN is an unobserved cell. Support uses the sources
present per cell; comparisons use pairwise overlap; a promoted patch never
fills a missing cell. Shapes, source identities and dependency edges are
validated; nonfinite validity times and support thresholds are refused.
Dependency edges incident to a stale source are removed with that source before
the aggregate is built. Floating reductions and decisions are invariant to
evidence order.

**Formal boundary.** The Lean project in `dissertation/formal` kernel-checks
accepted-value noninterference, event inclusion and measure monotonicity,
component arithmetic, the harmonic special case, crossover roots and
direction, and the algebraic counterexamples. Distribution-specific tails
remain analytic dependencies.

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
| Action-log shuffle | Permute the action history while holding observations fixed | **Run 2026-07-27. Outcome identical to an accurate log --- but see the amendment: the manipulation is one $m_{\text{eff}}$ is blind to by construction, so this control currently verifies the cardinality path only** |

The last was intended as the strongest control in the set, testing the premise rather than the
implementation. **It cannot currently do that**, and the reason is itself a finding --- see the
amendment below.

### Amendment 2026-07-27 (4) --- the shuffle control cannot yet refute the premise

Permuting the action log while preserving its size leaves the outcome bit-identical. That is not
because the action history is inert: the fidelity sweep shows harmful acceptance rising sharply once
the log under-reports past the support threshold, so the history is load-bearing.

It is because $m_{\text{eff}}$ consumes only $\lvert D\rvert/n$. Three masks of identical size and
completely different geometry --- contiguous, scattered, blocked --- give the same effective support
to six decimal places. The region-aggregate bound is derived by mean squared error over cells treated
symmetrically, so geometry cannot enter. The shuffle is a manipulation the quantity is blind to by
construction.

**Two consequences, and the second is the substantive one.**

The pre-registration must not be read as satisfied. This control verifies the cardinality path and
nothing more, and testing whether the history's *structure* matters needs a dependency
representation that carries structure.

And this is direct empirical support for the open question of whether a scalar is the right shape of
object for $m_{\text{eff}}$ at all --- recorded in the proposal as the deepest unresolved item. The
question was raised on statistical grounds; the shuffle control now answers it from the other
direction, by showing exactly what the scalar form discards.

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
- **Whether graph components are genuinely separated.** Action overlap is a
  provenance signal, not a covariance measurement. Independent-reference
  residual data are required.
- **The spatial covariance needed for a useful sharp tail.** The Markov bound
  does not require it; chi-square calibration does.
