#!/bin/bash
# STEWIE intern-beta acceptance (B4.4): from a running deploy (docker compose -f deploy/compose.yml
# up -d with STEWIE_API_KEY set), drive the operator training flow end-to-end and time it.
# The Day-28 KPT (<30 min WITH A HUMAN) needs a human; this script proves the MACHINE path.
set -e
BASE=${BASE:-http://localhost:8000}
KEY=${STEWIE_API_KEY:?set STEWIE_API_KEY}
T0=$(date +%s)
curl -sf $BASE/healthz >/dev/null
SCEN=$(python3 -c "import json,sys;print(json.dumps({**json.load(open('stewie/server/scenarios/nominal_traverse.json')),'profile':'mission_default'}))" )
SID=$(curl -sf -X POST $BASE/session/start -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
      -d "$SCEN" | python3 -c "import json,sys;d=json.load(sys.stdin);assert d['ok'],d;print(d['session_id'])")
curl -sf $BASE/session/$SID/operator | python3 -c "
import json,sys; d=json.load(sys.stdin)
assert d['legs'], 'operator received no legs'
assert all('true_J' not in l and 'slip' not in l for l in d['legs']), 'TRUTH LEAKED'
print('operator view OK:', len(d['legs']), 'legs · link', d['link']['stats'])"
curl -sf "$BASE/session/$SID/debrief?fast_forward=10" -H "X-API-Key: $KEY" | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('debrief OK: divergence %.0f J · missed %s' % (d['energy_divergence_J'], d['operator_missed_legs']))"
curl -sf $BASE/session/$SID/summary -H "X-API-Key: $KEY" | head -4
echo "BETA ACCEPT (machine path) PASSED in $(( $(date +%s) - T0 ))s"
