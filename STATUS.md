# STEWIE §7 requirements status

Generated from the live traceability tools (`scripts/req_trace.py` + `scripts/release_gate.py`) by `scripts/gen_status.py`. Do NOT hand-edit -- `gen_status.py --check` fails CI if this file drifts from the tools.

- requirements (PRD §7 rows): **199**
- cited by >=1 test ([REQ:] marker): **163**
- V!=D flagged (FS-22 audit: cited but not yet V=D): **40**

## V!=D flagged rows (cited, awaiting promotion)

| ID | current V |
|----|-----------|
| AM-02 | P |
| AS-01 | P |
| AS-04 | P |
| AS-07 | P |
| AS-09 | P |
| AS-10 | P |
| AS-11 | P |
| AS-12 | P |
| AS-13 | P |
| AS-15 | P |
| CP-07 | P |
| FL-05 | P |
| FS-03 | P |
| FS-05 | P |
| FS-10 | P |
| FS-11 | P |
| FS-12 | P |
| FS-14 | P |
| FS-15 | P |
| FS-18 | P |
| FS-21 | P |
| FS-24 | P |
| GI-01 | P |
| GI-03 | N |
| ML-05 | P |
| ML-06 | P |
| ML-09 | P |
| PM-01 | P |
| PM-03 | P |
| PM-07 | P |
| PM-10 | P |
| PM-11 | P |
| PO-04 | P |
| PO-05 | P |
| PO-09 | P |
| PO-11 | P |
| SE-01 | P |
| SL-01 | P |
| SN-12 | P |
| VT-06 | P |

## Per-family rollup (cited / total)

| family | cited | total |
|--------|-------|-------|
| AG | 8 | 8 |
| AM | 2 | 9 |
| AS | 17 | 18 |
| CP | 10 | 10 |
| CT | 7 | 7 |
| DT | 2 | 5 |
| EP | 6 | 8 |
| FL | 7 | 7 |
| FS | 24 | 28 |
| GI | 3 | 3 |
| ML | 9 | 9 |
| MO | 1 | 1 |
| NV | 12 | 12 |
| PM | 11 | 17 |
| PO | 14 | 15 |
| RL | 1 | 1 |
| SE | 1 | 2 |
| SF | 1 | 2 |
| SL | 1 | 1 |
| SN | 13 | 15 |
| TM | 0 | 1 |
| TW | 8 | 10 |
| VT | 5 | 10 |

## §25 autonomy track (AS-01..17)

- in matrix: 16/16
- cited: 16/16
- currently V=D: ['AS-02', 'AS-03', 'AS-05', 'AS-06', 'AS-08', 'AS-14', 'AS-17']
- eligible for V=D: ['AS-02', 'AS-03', 'AS-05', 'AS-06', 'AS-07', 'AS-08', 'AS-11', 'AS-14', 'AS-17']
