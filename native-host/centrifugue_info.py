"""Builds the info.json sidecar describing how a render was produced."""

import json
import platform
import subprocess

SCHEMA_VERSION = 1
CENTRIFUGUE_VERSION = "1.0"

_SONG_KEYS = ("title", "slug", "url", "video_id", "duration_seconds")
_AUDIO_KEYS = ("format", "codec", "sample_rate", "channels", "bit_depth")
_TIMING_KEYS = ("started_at", "completed_at", "download_seconds",
                "separation_seconds", "total_seconds")


def _fill(source, keys):
    """Every key present; absent values become None."""
    src = source or {}
    return {key: src.get(key) for key in keys}


def _module_version(name):
    try:
        import importlib.metadata as md
        return md.version(name)
    except Exception:
        return None


def _binary_version(binary):
    try:
        out = subprocess.run([binary, "--version"], capture_output=True,
                             text=True, timeout=10)
        return (out.stdout or out.stderr).strip().splitlines()[0] or None
    except Exception:
        return None


def _torch_device():
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return None


_VENV_PROBE = (
    "import json\n"
    "out = {}\n"
    "try:\n"
    "    import importlib.metadata as md\n"
    "    for name in ('demucs', 'audio-separator', 'torch'):\n"
    "        try: out[name] = md.version(name)\n"
    "        except Exception: out[name] = None\n"
    "except Exception:\n"
    "    pass\n"
    "try:\n"
    "    import torch\n"
    "    if torch.backends.mps.is_available(): out['device'] = 'mps'\n"
    "    elif torch.cuda.is_available(): out['device'] = 'cuda'\n"
    "    else: out['device'] = 'cpu'\n"
    "except Exception:\n"
    "    out['device'] = None\n"
    "print(json.dumps(out))\n"
)


def parse_venv_probe(stdout):
    """Turn the probe's JSON into our key names. Never raises."""
    try:
        raw = json.loads(stdout)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for src, dest in (("demucs", "demucs"), ("torch", "torch"),
                      ("audio-separator", "audio_separator"),
                      ("device", "device")):
        if src in raw:
            out[dest] = raw[src]
    return out


def _run_venv_probe(venv_python):
    """Ask the Demucs venv about itself. Never raises."""
    try:
        result = subprocess.run([str(venv_python), "-c", _VENV_PROBE],
                                capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return {}
        return parse_venv_probe(result.stdout)
    except Exception:
        return {}


def probe_environment(venv_python=None):
    """Best-effort version probe. Never raises; unknowns are None.

    demucs, torch, audio-separator and the compute device live in the
    Demucs venv, not in the interpreter running this host -- which is the
    system python when the browser spawns us, and cannot import any of
    them. Probing through the venv is the only way to record real values.
    """
    env = {
        "centrifugue_version": CENTRIFUGUE_VERSION,
        "python": platform.python_version(),
        "platform": f"{platform.system()}-{platform.release()}-{platform.machine()}",
        "device": _torch_device(),
        "demucs": _module_version("demucs"),
        "audio_separator": _module_version("audio-separator"),
        "torch": _module_version("torch"),
        "yt_dlp": _binary_version("yt-dlp"),
    }
    if venv_python:
        env.update(_run_venv_probe(venv_python))
    return env


def build_info(song, separation, audio, files, timing, environment=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "song": _fill(song, _SONG_KEYS),
        "separation": separation if separation else None,
        "audio": _fill(audio, _AUDIO_KEYS),
        "files": list(files or []),
        "timing": _fill(timing, _TIMING_KEYS),
        "environment": environment if environment is not None else probe_environment(),
    }
