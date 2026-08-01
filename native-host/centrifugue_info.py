"""Builds the info.json sidecar describing how a render was produced."""

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


def probe_environment():
    """Best-effort version probe. Never raises; unknowns are None."""
    return {
        "centrifugue_version": CENTRIFUGUE_VERSION,
        "python": platform.python_version(),
        "platform": f"{platform.system()}-{platform.release()}-{platform.machine()}",
        "device": _torch_device(),
        "demucs": _module_version("demucs"),
        "audio_separator": _module_version("audio-separator"),
        "torch": _module_version("torch"),
        "yt_dlp": _binary_version("yt-dlp"),
    }


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
