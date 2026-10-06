# -*- coding: utf-8 -*-
"""Per-user state for B_Dare95 tools.

Rule: tools never write inside the extension folder. Auto-update resets that
folder to exactly what is on GitHub, so anything written there is lost - and
any tracked file a tool modified used to block updates entirely.

State lives in %APPDATA%\\B_Dare95\\ instead, one file per tool, per user.
"""

import json
import os

STATE_DIR = os.path.join(os.getenv('APPDATA') or os.path.expanduser('~'),
                         'B_Dare95', 'toggle_states')


def toggle_state_path(key):
    if not os.path.isdir(STATE_DIR):
        os.makedirs(STATE_DIR)
    return os.path.join(STATE_DIR, '{0}.json'.format(key))


def _read(path):
    try:
        with open(path) as handle:
            return bool(json.load(handle)['toggle_state'])
    except Exception:
        return None


def flip_toggle(key, legacy_path=None):
    """Return the stored state, then store its opposite (same contract as the
    old read_toggle_config()). legacy_path is the old toggle_state.json in the
    bundle folder, read once so nobody's state flips during the move."""
    path = toggle_state_path(key)
    state = _read(path)
    if state is None and legacy_path:
        state = _read(legacy_path)
    if state is None:
        state = False
    with open(path, 'w') as handle:
        json.dump({'toggle_state': not state}, handle)
    return state
