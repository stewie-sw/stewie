# STEWIE §7 requirements status

Generated from the live traceability tools (`scripts/req_trace.py` + `scripts/release_gate.py`) by `scripts/gen_status.py`. Do NOT hand-edit -- `gen_status.py --check` fails CI if this file drifts from the tools.

- requirements (PRD §7 rows): **397**
- cited by >=1 test ([REQ:] marker): **280**
- V!=D flagged (FS-22 audit: cited but not yet V=D): **21**

## V!=D flagged rows (cited, awaiting promotion)

| ID | current V |
|----|-----------|
| AM-02 | P |
| AS-04 | P |
| AS-12 | P |
| AS-13 | P |
| CP-07 | P |
| EV-01 | P |
| FL-05 | P |
| FS-05 | P |
| FS-10 | P |
| FS-12 | P |
| FS-21 | P |
| FS-24 | P |
| GI-03 | P |
| MT-01 | P |
| PM-03 | P |
| PM-10 | P |
| PM-11 | P |
| PO-09 | P |
| SD-03 | N |
| SN-12 | P |
| TW-11 | N |

## Per-family rollup (cited / total)

| family | cited | total |
|--------|-------|-------|
| AC | 1 | 2 |
| AD | 0 | 3 |
| AG | 8 | 8 |
| AM | 6 | 9 |
| AP | 1 | 1 |
| AS | 17 | 18 |
| AU | 1 | 1 |
| BA | 8 | 11 |
| BD | 4 | 4 |
| BP | 7 | 13 |
| BR | 0 | 2 |
| CF | 0 | 1 |
| CG | 0 | 1 |
| CP | 10 | 10 |
| CR | 0 | 1 |
| CT | 7 | 7 |
| DA | 0 | 6 |
| DE | 1 | 1 |
| DT | 5 | 6 |
| DW | 0 | 2 |
| EG | 11 | 12 |
| EP | 7 | 8 |
| EV | 1 | 1 |
| FL | 7 | 8 |
| FR | 14 | 21 |
| FS | 28 | 32 |
| GI | 3 | 3 |
| GL | 0 | 2 |
| GW | 8 | 13 |
| HF | 0 | 1 |
| IN | 0 | 2 |
| LY | 5 | 7 |
| MG | 1 | 4 |
| MI | 0 | 1 |
| ML | 9 | 10 |
| MO | 1 | 1 |
| MP | 7 | 9 |
| MT | 3 | 5 |
| NV | 12 | 12 |
| OF | 0 | 1 |
| PD | 0 | 1 |
| PG | 0 | 1 |
| PH | 2 | 2 |
| PM | 11 | 19 |
| PO | 17 | 18 |
| PX | 5 | 7 |
| QB | 0 | 1 |
| QG | 0 | 4 |
| QW | 0 | 1 |
| RF | 3 | 3 |
| RL | 1 | 1 |
| RO | 0 | 1 |
| RS | 4 | 8 |
| RT | 1 | 6 |
| SC | 0 | 2 |
| SD | 2 | 3 |
| SE | 2 | 2 |
| SF | 2 | 2 |
| SL | 1 | 1 |
| SN | 15 | 15 |
| SV | 0 | 1 |
| TF | 0 | 1 |
| TM | 3 | 4 |
| TP | 0 | 4 |
| TS | 0 | 1 |
| TT | 0 | 1 |
| TU | 0 | 1 |
| TW | 9 | 12 |
| VT | 9 | 10 |
| WS | 0 | 4 |

## §25 autonomy track (AS-01..17)

- in matrix: 16/16
- cited: 16/16
- currently V=D: ['AS-01', 'AS-02', 'AS-03', 'AS-05', 'AS-06', 'AS-07', 'AS-08', 'AS-09', 'AS-10', 'AS-11', 'AS-14', 'AS-15', 'AS-17']
- eligible for V=D: ['AS-01', 'AS-02', 'AS-03', 'AS-05', 'AS-06', 'AS-07', 'AS-08', 'AS-09', 'AS-10', 'AS-11', 'AS-14', 'AS-15', 'AS-17']
