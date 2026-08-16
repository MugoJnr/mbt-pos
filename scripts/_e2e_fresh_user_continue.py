"""Continue Phase 2-3 for already-registered fresh user."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

STATE_FILE = ROOT / 'logs' / '_e2e_fresh_user_state.json'
state = json.loads(STATE_FILE.read_text(encoding='utf-8'))

# Patch module globals then run steps
import _e2e_fresh_user_portal as e2e  # noqa: E402

e2e.NEW_EMAIL = state['email']
e2e.NEW_PASSWORD = state['password']
e2e.NEW_BUSINESS = state['business']

print('CONTINUE', e2e.NEW_EMAIL)
verify = e2e.verify_via_action_link()
print('VERIFY', json.dumps(verify))
if not verify.get('ok'):
    state['verify'] = verify
    state['failed'] = True
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    raise SystemExit(1)

lic = e2e.admin_login_and_assign()
print('LICENSE', json.dumps(lic))
state['verify'] = verify
state['license'] = lic
state['completed_phases'] = ['2', '3']
state['failed'] = not lic.get('ok')
STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')
raise SystemExit(0 if lic.get('ok') else 1)
