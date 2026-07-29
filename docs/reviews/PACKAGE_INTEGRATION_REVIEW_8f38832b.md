# Package and integration review — `8f38832b`

- **Reviewed commit:** `8f38832b0a6e7b5a1ac2a7a5c3b15c8c422108c6`
- **Review role:** independent backend, package, persistence, and integration reviewer
- **Review method:** read-only inspection and execution from an isolated detached worktree
- **Evidence boundary:** source tests, static analysis, package construction, clean-environment
  installation probes, persistence fault probes, and controlled synthetic CLI workflows
- **Claim boundary:** research prototype only; no live-robot, distributed, physical-deployment, or
  dissertation-effectiveness claim is accepted by this review

## Verdict

| Decision target | Decision | Reason |
|---|---|---|
| Architecture and typed contracts | **BLOCK** | A public append option can bypass graph validation while returning ordinary committed receipts and mutating the branch-head projection. |
| Source-tree controlled prototype | **ACCEPT — execution evidence only** | Focused tests, validators, static checks, and all valid CLI workflows execute successfully. |
| Runnable packaged prototype | **BLOCK** | The root wheel cannot execute its installed UltraBuild entry point with its declared extra alone. |
| Reproducible evidence package | **BLOCK** | Durable provenance records identify a historical baseline commit rather than the executing build. |
| Legacy/live integration | **BLOCK — explicitly out of current scope** | The authority gateway is not wired into legacy FastAPI, ROS, GIS, planner, or robot command paths. |
| Barrier 2 / Barrier 3 acceptance | **BLOCK** | Passing producer self-tests does not close the authority bypass, packaging failure, or independent evidence requirements. |

The source implementation is a substantial, executable single-node prototype. The two gate
decisions remain blocked because authority and packaging contracts must hold for every supported
public path, not only for the golden path.

## Blocking findings

### 1. Public append API can bypass the authoritative graph contract

`AuthoritativeStore.append_batch` exposes `validate_graph: bool = True`. Passing `False` skips
`record_set_errors` over durable plus staged records, but the method still:

- inserts canonical record bytes;
- advances `next_sequence`;
- initializes a branch-head projection for a Branch record;
- stores an idempotency receipt; and
- returns an append receipt with `durability.committed: true`.

A direct probe submitted a schema-valid accepted Branch with
`head_revision_id = "revision.nonexistent"` and `head_sequence = 9` through
`append_batch(..., validate_graph=False)`. The call returned a committed receipt and
`branch_head()` immediately returned the nonexistent revision. A later integrity check failed with:

```text
graph: head_revision_id: unresolved reference revision.nonexistent
```

This contradicts the architecture's claims that `AuthoritativeStore` is the only immutable append
gateway and that the complete durable-plus-staged graph is validated before acknowledgement.

Evidence:

- `8f38832b:stewie/ultrabuild/store.py:219-234`
- `8f38832b:stewie/ultrabuild/store.py:312-319`
- `8f38832b:stewie/ultrabuild/store.py:321-413`
- `8f38832b:SYSTEM_ARCHITECTURE.md:14-22`
- `8f38832b:SYSTEM_ARCHITECTURE.md:89-101`
- `8f38832b:SYSTEM_ARCHITECTURE.md:139-150`
- `8f38832b:RUNTIME_GRAPH.yaml:74-103`

Required closure:

1. Remove graph-validation bypasses from every public append API.
2. If an unsafe import or repair primitive is required, make it private and offline.
3. Prevent an unsafe primitive from advancing ordinary projections or issuing normal committed
   receipts.
4. Add negative tests proving every public append path rejects unresolved provenance, unresolved
   record links, and fabricated branch heads.

### 2. Root wheel is not independently runnable

The exact reviewed wheel was built successfully:

```text
stewie-0.1.0-py3-none-any.whl
sha256 ce0d613a0f529b3af683a11259932c9b5c880a994c194c80f12878c9ff09e04b
```

A clean virtual environment installed that wheel with its declared `ultrabuild` extra. Running
`stewie-ultrabuild --help` from outside the source tree exited 1:

```text
ModuleNotFoundError: No module named 'stewie_bodies'
```

The import is unconditional:

```text
stewie/__init__.py
  -> stewie.envs.registration
  -> stewie.specs.bodies
  -> stewie_bodies
```

The root wheel metadata declares neither `stewie-bodies` nor an equivalent bundled package. The
existing fresh-wheel server test builds and explicitly installs the workspace wheels alongside the
root wheel, masking the root metadata defect.

Evidence:

- `8f38832b:pyproject.toml:23-28`
- `8f38832b:pyproject.toml:40`
- `8f38832b:pyproject.toml:69-75`
- `8f38832b:stewie/__init__.py:2`
- `8f38832b:stewie/specs/bodies.py:9`
- `8f38832b:stewie/server/test_fresh_wheel.py:51-70`
- `8f38832b:KNOWN_LIMITATIONS.md:140`

Required closure:

1. Declare every unconditional import-time workspace distribution in root package metadata or
   bundle it in the root wheel.
2. Build all local dependency wheels into a test wheelhouse, but install only the root wheel and
   allow its metadata to resolve the rest.
3. Run `stewie-ultrabuild --help` and one payload-backed demo from outside the repository.

### 3. Evidence provenance misidentifies the executing code

`records.py` hard-codes:

```text
BASE_COMMIT = d1056d9deff4e540557b13c8cb78fc799330410e
```

Every generated provenance activity copies that value into `code_commit`, even when the executing
source is `8f38832b`. A demo produced from the reviewed wheel contained only the older commit in
durable provenance. The demo summary contained no actual installed-build identity.

Evidence:

- `8f38832b:stewie/ultrabuild/records.py:17-19`
- `8f38832b:stewie/ultrabuild/records.py:1110-1118`
- `8f38832b:stewie/ultrabuild/cli.py:29-48`

Required closure:

1. Inject or discover build identity at execution time.
2. Record source commit, dirty/clean state, and installed package version, or explicitly record
   `unavailable`.
3. Bind the actual identity to durable provenance records as well as report summaries.
4. Never substitute a historical baseline commit for unknown executing code.

## Material residual defects

### Payload integrity can be silently excluded from CLI verification

`verify --database` constructs an authority store without a payload store unless the optional
`--payloads` argument is supplied. On a database whose referenced payload files were deliberately
corrupted:

- `verify --database ...` returned `ok: true` and exit 0; and
- `verify --database ... --payloads ...` returned `ok: false` and exit 1 with five bad references.

Configured payload enforcement works correctly. The defect is the command's ambiguous success
surface: its help says it verifies an authority database, while the resulting JSON does not say that
payloads were unchecked.

Evidence:

- `8f38832b:stewie/ultrabuild/cli.py:85-96`
- `8f38832b:stewie/ultrabuild/cli.py:143-148`
- `8f38832b:KNOWN_LIMITATIONS.md:55-58`

The CLI must either require `--payloads` for a complete verification or report an explicit,
machine-readable `payload verification: not checked` scope. An unqualified `ok: true` is not
acceptable when content-addressed payloads were excluded.

### Projection rebuild is not fail-closed on invalid immutable history

`verify_integrity()` checks record schemas, hashes, graph semantics, receipts, payloads, sequence
metadata, and derived branch heads. `rebuild_projections()` is a separate public operation that reads
all record JSON and derives mutable heads without first validating that history.

Direct database corruption—or the public graph-validation bypass—can therefore feed invalid history
into a projection rebuild. Rebuild should refuse invalid history before deleting or replacing any
projection.

Evidence:

- `8f38832b:stewie/ultrabuild/store.py:524-619`
- `8f38832b:stewie/ultrabuild/store.py:659-692`

### Reusing a benchmark output can measure idempotent replay as durable append

`run_benchmarks` always starts `append_counter` at zero and reuses deterministic branch IDs and
idempotency tokens in `append-benchmark.sqlite3`. Running the benchmark twice into one output
directory left both the record and idempotency counts at 25 after the second run. The second report
still labelled the timing `durable_event_append`.

Evidence:

- `8f38832b:stewie/ultrabuild/benchmark.py:55-64`
- `8f38832b:stewie/ultrabuild/benchmark.py:99-124`

The benchmark must refuse a reused output directory, create a fresh run namespace, or explicitly
measure and label duplicate replay as a distinct operation.

### Invalid measured-run counts produce an internal traceback

The CLI parser accepts any integer for `--measured-runs`; `run_benchmarks` later raises
`ValueError("measured_runs must be at least 20")`. Consequently,
`benchmark --measured-runs 5` prints an uncaught traceback instead of a command-line usage error.

Evidence:

- `8f38832b:stewie/ultrabuild/cli.py:149-154`
- `8f38832b:stewie/ultrabuild/benchmark.py:55-61`

Argument validation should fail through `argparse` with exit code 2 and a concise lower-bound
message, before benchmark output is created.

## Positive evidence

### Transaction ownership

The normal authority path has strong prototype semantics:

- callers cannot supply `transaction_time`, `recorded_at`, or `content_hash`;
- the store assigns sequence, timestamp, and final canonical hash;
- exact idempotency compares canonical submission hashes;
- ordinary append rejects promotion decisions and accepted-state revisions;
- promotion appends decision and revision and advances the accepted head in one SQLite transaction;
- `BEGIN IMMEDIATE` rolls back on any exception;
- a two-connection concurrency test yields exactly one promotion winner; and
- a pending review leaves no partial promotion records.

Evidence:

- `8f38832b:schemas/ultrabuild/record_submission.schema.json`
- `8f38832b:stewie/ultrabuild/contracts.py:114-145`
- `8f38832b:stewie/ultrabuild/store.py:169-178`
- `8f38832b:stewie/ultrabuild/store.py:246-310`
- `8f38832b:stewie/ultrabuild/store.py:714-904`

### SQLite and payload durability

The SQLite store enables WAL, `synchronous=FULL`, foreign keys, and a bounded busy timeout. The
filesystem payload store:

- keys objects by SHA-256;
- writes and fsyncs a temporary file;
- atomically replaces the final target;
- fsyncs the containing directory; and
- verifies both digest and optional byte length.

With `require_local_payloads=True`, append rejects missing, corrupt, or wrong-size local payloads.
Payload and SQLite commits remain separate transactions, so orphan payloads are possible; this
limitation is accurately documented.

Evidence:

- `8f38832b:stewie/ultrabuild/store.py:56-92`
- `8f38832b:stewie/ultrabuild/store.py:415-480`
- `8f38832b:stewie/ultrabuild/payloads.py:19-132`
- `8f38832b:KNOWN_LIMITATIONS.md:36-58`

### Projection, snapshot, and reopen

Deliberate branch-head projection corruption is detected by integrity verification. Rebuilding from
valid immutable history restores the projection, and a SQLite backup reopened cold preserves
canonical bytes and accepted-head state. This is good evidence for the valid-history path, but does
not remove the invalid-history rebuild defect above.

### Runtime graph and integration boundary

The runtime graph registers typed payload, submission, append, CAS, and projection receipts. The
golden flow durably binds query lens, exact map revision, planning decision, and planned action.

The architecture also accurately discloses that:

- the new gateway is not wired into legacy FastAPI, ROS, GIS, planner, or robot execution paths;
- reconciliation, query, plan, and action are deterministic builders rather than a live dispatcher;
- only branch heads have a rebuild path;
- temporal query behavior is revision-level, not complete claim-level bitemporal semantics;
- payload and SQLite commits are separate; and
- concurrency evidence is single-host.

Repository search found no legacy/live import of `stewie.ultrabuild` or `AuthoritativeStore`. The
multi-robot and conflict demos are controlled, centralized synthetic workflows. They must not be
used as evidence for distributed synchronization, a live single-robot loop, or a live multi-robot
loop.

Evidence:

- `8f38832b:RUNTIME_GRAPH.yaml:1-20`
- `8f38832b:SYSTEM_ARCHITECTURE.md:118-135`
- `8f38832b:KNOWN_LIMITATIONS.md:28-102`

## Packaging warnings distinguished from failures

| Observation | Classification | Rationale |
|---|---|---|
| Missing `stewie_bodies` after installing the root wheel with `[ultrabuild]` | **Failure** | The import is unconditional and the distribution is absent from wheel metadata. |
| Missing `jsonschema` when the wheel is installed without `[ultrabuild]` | **Warning / expected optional-extra behavior** | The dependency is correctly declared by the named extra, although the raw traceback is poor UX. |
| UltraBuild test modules are included in the wheel | **Warning** | This increases artifact size but does not prevent execution or alter authority semantics. |
| Legacy/live systems are not wired to the gateway | **Declared scope limitation** | It blocks integrated/live claims but is not hidden as a completed capability. |
| Payload and SQLite commits are separate | **Declared durability limitation** | The configured path prevents dangling committed references but can leave orphan payloads. |

## Verification performed

All review commands and fault probes were run against an isolated detached worktree at the exact
reviewed commit.

```text
PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q stewie/ultrabuild
  PASS — 42 tests

.venv/bin/python scripts/validate_ultrabuild.py
  PASS

.venv/bin/python scripts/validate_ultrabuild_contracts.py
  PASS

.venv/bin/ruff check stewie/ultrabuild
  PASS

.venv/bin/mypy stewie/ultrabuild
  PASS — 15 source files

python -m pip wheel . --no-deps --no-build-isolation
  PASS — root wheel and 25 UltraBuild schemas produced

clean-venv: pip install stewie-0.1.0-py3-none-any.whl[ultrabuild]
clean-venv: stewie-ultrabuild --help
  FAIL — ModuleNotFoundError: stewie_bodies
```

After manually installing the missing workspace package, the exact wheel successfully ran from
outside the source tree:

- `--help`;
- `demo`, including an idempotent rerun;
- `verify`, with and without a payload path;
- `multi-demo`;
- `conflict-demo`;
- `evaluate`, with 1,728 controlled synthetic trials;
- `benchmark --measured-runs 20`;
- `fault-inject`, with eight passing probes; and
- `perturb`.

The wheel contains the UltraBuild modules and all registered schemas, and installed-schema fallback
works. This isolates the package failure to root dependency metadata/importability rather than the
UltraBuild module or schema-data layout.

## Gate reopening criteria

Re-review in this order:

1. eliminate the public graph-validation bypass and add rejection tests;
2. make the root wheel resolve all unconditional import-time dependencies through metadata and pass
   a clean installed-entry-point smoke;
3. bind the executing build identity into durable provenance;
4. make payload-verification scope explicit;
5. make projection rebuild fail closed on invalid history;
6. prevent benchmark-output reuse from being reported as fresh durable append; and
7. validate CLI argument bounds before execution.

Only then should architecture/contracts and the packaged runnable prototype return to independent
review. Legacy/live integration and dissertation effectiveness remain separate future gates.
