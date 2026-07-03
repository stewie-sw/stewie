# STEWIE §7 requirements status

Generated from the live traceability tools (`scripts/req_trace.py` + `scripts/release_gate.py`) by `scripts/gen_status.py`. Do NOT hand-edit -- `gen_status.py --check` fails CI if this file drifts from the tools.

- requirements (PRD §7 rows): **255**
- cited by >=1 test ([REQ:] marker): **185**
- V!=D flagged (FS-22 audit: cited but not yet V=D): **28**

## V!=D flagged rows (cited, awaiting promotion)

| ID | current V |
|----|-----------|
| AM-02 | P |
| AS-11 | P |
| AS-12 | P |
| AS-13 | P |
| AS-15 | P |
| CP-07 | P |
| FL-05 | P |
| FS-05 | P |
| FS-10 | P |
| FS-12 | P |
| FS-21 | P |
| FS-24 | P |
| FS-26 | P |
| GI-03 | N |
| ML-05 | P |
| ML-06 | P |
| MT-01 | P |
| MT-05 | P |
| PM-03 | P |
| PM-10 | P |
| PM-11 | P |
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
| BA | 5 | 11 |
| BP | 3 | 13 |
| CP | 10 | 10 |
| CT | 7 | 7 |
| DT | 5 | 5 |
| EP | 6 | 8 |
| FL | 7 | 7 |
| FR | 0 | 15 |
| FS | 28 | 30 |
| GI | 3 | 3 |
| ML | 9 | 9 |
| MO | 1 | 1 |
| MT | 2 | 5 |
| NV | 12 | 12 |
| PM | 11 | 19 |
| PO | 14 | 15 |
| RL | 1 | 1 |
| RS | 4 | 8 |
| SE | 1 | 2 |
| SF | 2 | 2 |
| SL | 1 | 1 |
| SN | 13 | 15 |
| TM | 0 | 1 |
| TW | 8 | 10 |
| VT | 5 | 10 |

## §25 autonomy track (AS-01..17)

- in matrix: 16/16
- cited: 16/16
- currently V=D: ['AS-01', 'AS-02', 'AS-03', 'AS-04', 'AS-05', 'AS-06', 'AS-07', 'AS-08', 'AS-09', 'AS-10', 'AS-14', 'AS-17']
- eligible for V=D: ['AS-01', 'AS-02', 'AS-03', 'AS-05', 'AS-06', 'AS-07', 'AS-08', 'AS-09', 'AS-10', 'AS-11', 'AS-14', 'AS-17']
