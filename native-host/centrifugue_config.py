"""User configuration for Centrifugue.

The host owns ~/.centrifugue/config.json. A missing or broken file must
never fail a job -- callers always get a usable config back.
"""

import copy
import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "output_dir": "~/Downloads",
    "naming": {"style": "lowercase_ascii", "max_length": 80},
    "write_info_json": True,
}


def get_config_path():
    return Path.home() / ".centrifugue" / "config.json"


def _merge(base, overrides):
    merged = copy.deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config():
    """Return the effective config. Never raises."""
    try:
        raw = json.loads(get_config_path().read_text())
        if not isinstance(raw, dict):
            return copy.deepcopy(DEFAULT_CONFIG)
        return _merge(DEFAULT_CONFIG, raw)
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULT_CONFIG)


def get_output_dir(config=None):
    cfg = config if config is not None else load_config()
    raw = cfg.get("output_dir") or DEFAULT_CONFIG["output_dir"]
    return Path(os.path.expanduser(str(raw))).expanduser()


def _validate(candidate):
    out = candidate.get("output_dir")
    if out is not None and not isinstance(out, str):
        raise ValueError("output_dir must be a string")
    if out is not None:
        path = Path(os.path.expanduser(out))
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"output_dir is not writable: {exc}") from exc
        if not os.access(path, os.W_OK):
            raise ValueError(f"output_dir is not writable: {path}")


def save_config(updates):
    """Merge updates into the stored config and persist. Raises ValueError."""
    merged = _merge(load_config(), updates)
    _validate(merged)
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2) + "\n")
    return merged
