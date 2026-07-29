# Barrier 2 final systems review — `c28a74f3`

- **Reviewed commit:** `c28a74f3cd1877d4fb9486c564c6e0097f9933e9`
- **Review method:** clean `git archive`, read-only
- **Review role:** independent adversarial systems and package critic
- **Package verdict:** **PASS**
- **Barrier 2 verdict:** **ACCEPT**
- **Barrier 3 implementation smoke:** **PASS**
- **Barrier 3 project verdict:** **BLOCK**

No critical or major defect remained in the bounded package/authority scope.

Independent gates:

```text
clean wheel smoke: 7 passed
UltraBuild suite: 73 passed, 1 skipped
shadow/receipt/projection adversarial subset: 9 passed
UltraBuild validator: PASS
contract validator: PASS
Ruff: PASS
mypy: PASS — 17 files
```

Each duplicated indexed field was independently corrupted: `schema_version`, `world_id`, `site_id`,
`branch_id`, `valid_start`, and `valid_end`. Every mutation made `verify_integrity()` fail,
`rebuild_projections()` refuse with `StoreContractError`, and the branch head remain unchanged.

Deleting the append receipt for an observation produced an append-registry error. Deleting the
applied promotion operation produced a CAS-registry error. Both prevented projection rebuild.
Corrupting only `branch_heads` produced only the projection-difference error; deterministic rebuild
then restored integrity.

Supported within this review scope:

- clean root-wheel dependency resolution and the installed UltraBuild entry point;
- complete checking of the reviewed record shadow fields;
- exactly one durable append receipt per durable record;
- exactly one applied promotion receipt per authoritative promotion;
- rebuild refusal when immutable history or required registries are incomplete; and
- repair of projection-only corruption.

This review does not support distributed authority behavior, automatic quarantine, arbitrary crash
recovery, live robot integration, mission readiness, flight certification, or physical deployment.
Barrier 3 remains blocked by upstream lifecycle/evidence conditions and its unfulfilled
real-terrain acceptance contract.
