import json
import os

# Pane layout state (edge + width) persisted next to the repo root and restored
# on the next launch. It is machine-written and gitignored.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(_REPO_ROOT, "ui_state.json")


def load_state():
    """Read the persisted UI state, falling back to an empty dict."""
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    """Write the UI state, ignoring write failures."""
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass
