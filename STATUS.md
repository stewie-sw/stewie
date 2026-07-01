# STEWIE §7 requirements status

Generated from the live traceability tools (`scripts/req_trace.py` + `scripts/release_gate.py`) by `scripts/gen_status.py`. Do NOT hand-edit -- `gen_status.py --check` fails CI if this file drifts from the tools.

- requirements (PRD §7 rows): **188**
- cited by >=1 test ([REQ:] marker): **124**
- V!=D flagged (FS-22 audit: cited but not yet V=D): **38**

## V!=D flagged rows (cited, awaiting promotion)

| ID | current V |
|----|-----------|
| AM-02 | P |
| AS-01 | N |
| AS-02 | N |
| AS-03 | N |
| AS-04 | N |
| AS-05 | N |
| AS-06 | N |
| AS-07 | P |
| AS-08 | P |
| AS-09 | P |
| AS-10 | P |
| AS-11 | P |
| AS-12 | P |
| AS-13 | P |
| AS-14 | N |
| AS-15 | P |
| CP-07 | P |
| DT-01 | N |
| EP-01 | P |
| FL-04 | P |
| FL-05 | P |
| FS-05 | P |
| FS-10 | P |
| FS-11 | P |
| FS-15 | P |
| FS-18 | N |
| FS-19 | P |
| FS-21 | P |
| GI-03 | N |
| ML-02 | N |
| ML-03 | N |
| ML-04 | P |
| PO-01 | N |
| PO-04 | P |
| PO-05 | N |
| SL-01 | P |
| SN-12 | N |
| VT-06 | P |

## Per-family rollup (cited / total)

| family | cited | total |
|--------|-------|-------|
| AG | 8 | 8 |
| AM | 2 | 9 |
| AS | 16 | 18 |
| CP | 10 | 10 |
| CT | 7 | 7 |
| DT | 2 | 2 |
| EP | 6 | 8 |
| FL | 6 | 7 |
| FS | 12 | 24 |
| GI | 1 | 3 |
| ML | 4 | 9 |
| MO | 1 | 1 |
| NV | 11 | 12 |
| PM | 5 | 16 |
| PO | 9 | 14 |
| RL | 0 | 1 |
| SE | 0 | 1 |
| SF | 1 | 1 |
| SL | 1 | 1 |
| SN | 11 | 15 |
| TM | 0 | 1 |
| TW | 7 | 10 |
| VT | 4 | 10 |

## §25 autonomy track (AS-01..17)

- in matrix: 16/16
- cited: 16/16
- currently V=D: ['AS-17']
- eligible for V=D: ['AS-17']
