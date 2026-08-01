# Configurable Stem Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users choose where stems land, name folders/files from a normalized song slug, and write an `info.json` sidecar describing how each render was produced.

**Architecture:** Pure logic (slug, collision, config, info-building) moves into three new small modules beside the host, each unit-tested with pytest. `centrifugue_host.py` keeps orchestration only and calls into them. Stems are assembled in a hidden temp dir and published with a single atomic `os.rename` so Ableton never sees a half-written folder.

**Tech Stack:** Python 3.9+, pytest, stdlib only (`unicodedata`, `re`, `json`, `os`, `shutil`). No new runtime dependencies.

## Global Constraints

- Spec: `specs/configurable-stem-output/spec.md`. Read it before starting.
- No new runtime dependencies. pytest is a dev-only dependency.
- Backward compatible: absent/malformed config falls back to `~/Downloads`; never fail a job over config problems.
- `info.json` keys are always present; unknown values are `null`, never omitted.
- Version probing must never fail a job — a missing tool records `null`.
- Commit messages follow `.claude/rules.md`: imperative subject ≤72 chars, body containing only `Co-Authored-By: Claude <noreply@anthropic.com>`, one responsibility per commit, no AI attribution.
- Both extensions must stay in sync: any popup change lands in `extension-firefox/` **and** `extension-chrome/`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `native-host/centrifugue_naming.py` | **Create.** `slugify()`, `resolve_output_folder()`. Pure, no I/O except `.exists()` via injected callbacks. |
| `native-host/centrifugue_config.py` | **Create.** Load/save/validate `~/.centrifugue/config.json`. |
| `native-host/centrifugue_info.py` | **Create.** Build the `info.json` dict; probe tool versions. |
| `native-host/centrifugue_host.py` | **Modify.** Use the modules; atomic publish; two new actions. |
| `extension-*/popup/popup.html` | **Modify.** Settings section with output-folder field. |
| `extension-*/popup/popup.js` | **Modify.** Load/save config. |
| `extension-*/background.js` | **Modify.** Relay `get_config`/`set_config`. |
| `tests/` | **Create.** pytest suite + `conftest.py`. |
| `README.md` | **Modify.** Configuration + `info.json` reference. |

---

### Task 1: Test scaffolding and the slug function

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_naming.py`
- Create: `native-host/centrifugue_naming.py`
- Create: `pytest.ini`

**Interfaces:**
- Consumes: nothing.
- Produces: `slugify(title: str, max_length: int = 80, video_id: str | None = None) -> str`

- [ ] **Step 1: Install pytest into the venv**

```bash
./venv-demucs/bin/pip install pytest
```

- [ ] **Step 2: Create pytest config**

`pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

- [ ] **Step 3: Make `native-host/` importable from tests**

`tests/conftest.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "native-host"))
```

- [ ] **Step 4: Write the failing tests**

`tests/test_naming.py`:

```python
import pytest
from centrifugue_naming import slugify


@pytest.mark.parametrize("title,expected", [
    ("RockHard - Foolio", "rockhard_foolio"),
    ("Café Tacvba — Éres (Official)", "cafe_tacvba_eres_official"),
    (
        "Linkin ParkLimp BizkitSlipknot Style-FFO; "
        "Aggressive NU Metal- encore - Isokuici",
        "linkin_parklimp_bizkitslipknot_style-ffo_aggressive_nu_metal_encore_isokuici",
    ),
])
def test_slugify_examples(title, expected):
    assert slugify(title) == expected


def test_internal_hyphen_survives_but_separator_hyphen_does_not():
    assert slugify("Style-FFO - Live") == "style-ffo_live"


def test_non_latin_title_falls_back_to_video_id():
    assert slugify("米津玄師 - アイドル", video_id="AMxCPVRUKQo") == "video_AMxCPVRUKQo"


def test_non_latin_title_without_video_id_falls_back_to_untitled():
    assert slugify("米津玄師") == "untitled"


def test_only_punctuation_falls_back():
    assert slugify("!!! ??? ***") == "untitled"


def test_only_spaces_falls_back():
    assert slugify("     ") == "untitled"


def test_empty_and_none_fall_back():
    assert slugify("") == "untitled"
    assert slugify(None) == "untitled"


def test_truncation_respects_max_length_and_never_ends_in_separator():
    out = slugify("a" * 50 + " " + "b" * 50, max_length=51)
    assert len(out) <= 51
    assert not out.endswith(("_", "-"))


def test_collapses_repeated_separators():
    assert slugify("a   ---   b") == "a_b"
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'centrifugue_naming'`

- [ ] **Step 6: Implement `slugify`**

`native-host/centrifugue_naming.py`:

```python
"""Filename and folder naming for Centrifugue output.

Pure functions: no filesystem writes, no network. Kept separate from
centrifugue_host.py so the rules can be unit-tested without a browser,
a model, or a download.
"""

import re
import unicodedata

DEFAULT_MAX_LENGTH = 80


def slugify(title, max_length=DEFAULT_MAX_LENGTH, video_id=None):
    """Normalize a video title into a lowercase ASCII path component.

    A hyphen between word characters is meaningful ("style-ffo") and is
    kept; a hyphen acting as a separator (" - ") collapses to a single
    underscore. Any run containing an underscore becomes one underscore,
    which handles both cases without special-casing.
    """
    text = unicodedata.normalize("NFKD", title or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()

    text = re.sub(r"[^a-z0-9_-]", "_", text)
    text = re.sub(r"[_-]*_[_-]*", "_", text)
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("_-")

    if max_length and len(text) > max_length:
        text = text[:max_length].rstrip("_-")

    if not text:
        return f"video_{video_id}" if video_id else "untitled"
    return text
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_naming.py -v`
Expected: PASS (12 tests)

- [ ] **Step 8: Commit**

```bash
git add pytest.ini tests/conftest.py tests/test_naming.py native-host/centrifugue_naming.py
git commit -m "Add slug normalization for output folder names"
```

---

### Task 2: Folder collision resolution

**Files:**
- Modify: `native-host/centrifugue_naming.py`
- Modify: `tests/test_naming.py`

**Interfaces:**
- Consumes: `slugify` from Task 1.
- Produces: `resolve_output_folder(output_dir: Path, slug: str, genre: str, quality: str, read_info: Callable[[Path], dict | None]) -> tuple[Path, bool]` returning `(target_path, is_overwrite)`.

`read_info` is injected so tests need no real files. Production passes a reader that loads `<folder>/info.json` and returns `None` if absent or unparseable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_naming.py`:

```python
from pathlib import Path
from centrifugue_naming import resolve_output_folder


def _info(genre, quality):
    return {"separation": {"genre_mode": genre, "quality_preset": quality}}


def test_fresh_slug_uses_base_folder(tmp_path):
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra", read_info=lambda p: None)
    assert target == tmp_path / "song"
    assert overwrite is False


def test_matching_settings_overwrites_in_place(tmp_path):
    (tmp_path / "song").mkdir()
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra",
        read_info=lambda p: _info("rock", "ultra"))
    assert target == tmp_path / "song"
    assert overwrite is True


def test_different_settings_get_variant_folder(tmp_path):
    (tmp_path / "song").mkdir()
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra",
        read_info=lambda p: _info("full", "fast"))
    assert target == tmp_path / "song_rock_ultra"
    assert overwrite is False


def test_folder_without_info_json_is_never_overwritten(tmp_path):
    (tmp_path / "song").mkdir()
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra", read_info=lambda p: None)
    assert target == tmp_path / "song_rock_ultra"
    assert overwrite is False


def test_variant_collision_appends_counter(tmp_path):
    (tmp_path / "song").mkdir()
    (tmp_path / "song_rock_ultra").mkdir()
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra",
        read_info=lambda p: _info("full", "fast"))
    assert target == tmp_path / "song_rock_ultra_2"
    assert overwrite is False


def test_variant_with_matching_settings_overwrites(tmp_path):
    (tmp_path / "song").mkdir()
    (tmp_path / "song_rock_ultra").mkdir()

    def reader(p):
        return _info("full", "fast") if p.name == "song" else _info("rock", "ultra")

    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra", read_info=reader)
    assert target == tmp_path / "song_rock_ultra"
    assert overwrite is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_naming.py -k resolve -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_output_folder'`

- [ ] **Step 3: Implement `resolve_output_folder`**

Append to `native-host/centrifugue_naming.py`:

```python
def _settings_match(info, genre, quality):
    if not info:
        return False
    sep = info.get("separation") or {}
    return sep.get("genre_mode") == genre and sep.get("quality_preset") == quality


def resolve_output_folder(output_dir, slug, genre, quality, read_info):
    """Pick the folder for this render.

    Returns (path, is_overwrite). A folder with no readable info.json is
    treated as foreign and never overwritten -- it may be hand-made or
    from an older Centrifugue.
    """
    base = output_dir / slug
    if not base.exists():
        return base, False
    if _settings_match(read_info(base), genre, quality):
        return base, True

    variant = output_dir / f"{slug}_{genre}_{quality}"
    if not variant.exists():
        return variant, False
    if _settings_match(read_info(variant), genre, quality):
        return variant, True

    n = 2
    while True:
        candidate = output_dir / f"{slug}_{genre}_{quality}_{n}"
        if not candidate.exists():
            return candidate, False
        if _settings_match(read_info(candidate), genre, quality):
            return candidate, True
        n += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_naming.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
git add native-host/centrifugue_naming.py tests/test_naming.py
git commit -m "Add output folder collision resolution"
```

---

### Task 3: Config module

**Files:**
- Create: `native-host/centrifugue_config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DEFAULT_CONFIG: dict`
  - `get_config_path() -> Path`
  - `load_config() -> dict` (never raises)
  - `save_config(updates: dict) -> dict` (raises `ValueError` on invalid input)
  - `get_output_dir(config: dict | None = None) -> Path`

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
import json
import pytest
import centrifugue_config as cc


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "get_config_path", lambda: tmp_path / "config.json")
    return tmp_path


def test_missing_config_returns_defaults():
    assert cc.load_config() == cc.DEFAULT_CONFIG


def test_malformed_config_falls_back_to_defaults(isolated_home):
    (isolated_home / "config.json").write_text("{not json")
    assert cc.load_config() == cc.DEFAULT_CONFIG


def test_partial_config_merges_over_defaults(isolated_home):
    (isolated_home / "config.json").write_text(json.dumps({"output_dir": "/tmp/x"}))
    cfg = cc.load_config()
    assert cfg["output_dir"] == "/tmp/x"
    assert cfg["naming"]["max_length"] == 80
    assert cfg["write_info_json"] is True


def test_output_dir_expands_tilde():
    out = cc.get_output_dir({"output_dir": "~/Music/Centrifugue"})
    assert str(out).startswith("/")
    assert "~" not in str(out)


def test_save_config_writes_and_returns_merged(isolated_home):
    result = cc.save_config({"output_dir": str(isolated_home)})
    assert result["output_dir"] == str(isolated_home)
    on_disk = json.loads((isolated_home / "config.json").read_text())
    assert on_disk["output_dir"] == str(isolated_home)


def test_save_config_rejects_non_writable_dir():
    with pytest.raises(ValueError, match="not writable|cannot"):
        cc.save_config({"output_dir": "/proc/nonexistent/nope"})


def test_save_config_rejects_non_string_output_dir():
    with pytest.raises(ValueError):
        cc.save_config({"output_dir": 42})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'centrifugue_config'`

- [ ] **Step 3: Implement the config module**

`native-host/centrifugue_config.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add native-host/centrifugue_config.py tests/test_config.py
git commit -m "Add user config file for output directory"
```

---

### Task 4: `info.json` builder

**Files:**
- Create: `native-host/centrifugue_info.py`
- Create: `tests/test_info.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `build_info(song: dict, separation: dict | None, audio: dict, files: list[dict], timing: dict, environment: dict | None = None) -> dict` and `probe_environment() -> dict`.

`build_info` is pure and fully tested. `probe_environment` shells out for versions and is exercised only for its never-raise contract.

- [ ] **Step 1: Write the failing tests**

`tests/test_info.py`:

```python
from centrifugue_info import build_info, probe_environment, SCHEMA_VERSION

SONG = {"title": "RockHard - Foolio", "slug": "rockhard_foolio",
        "url": "https://y.t/x", "video_id": "x", "duration_seconds": 256.14}
AUDIO = {"format": "flac", "codec": "flac", "sample_rate": 44100,
         "channels": 2, "bit_depth": 16}
FILES = [{"stem": "vocals", "filename": "vocals.flac", "bytes": 1}]
TIMING = {"started_at": "2026-08-01T17:04:03Z",
          "completed_at": "2026-08-01T17:09:14Z",
          "download_seconds": 12.4, "separation_seconds": 289.7,
          "total_seconds": 311.2}


def test_includes_schema_version():
    info = build_info(SONG, None, AUDIO, FILES, TIMING, environment={})
    assert info["schema_version"] == SCHEMA_VERSION


def test_top_level_keys_always_present():
    info = build_info(SONG, None, AUDIO, FILES, TIMING, environment={})
    for key in ("song", "separation", "audio", "files", "timing", "environment"):
        assert key in info


def test_separation_is_null_when_absent():
    info = build_info(SONG, None, AUDIO, FILES, TIMING, environment={})
    assert info["separation"] is None


def test_song_title_is_preserved_verbatim():
    info = build_info(SONG, None, AUDIO, FILES, TIMING, environment={})
    assert info["song"]["title"] == "RockHard - Foolio"
    assert info["song"]["slug"] == "rockhard_foolio"


def test_missing_song_fields_become_null_not_absent():
    info = build_info({"title": "t"}, None, AUDIO, FILES, TIMING, environment={})
    assert info["song"]["video_id"] is None
    assert info["song"]["duration_seconds"] is None


def test_missing_audio_fields_become_null():
    info = build_info(SONG, None, {"format": "mp3"}, FILES, TIMING, environment={})
    assert info["audio"]["bit_depth"] is None
    assert info["audio"]["sample_rate"] is None


def test_serializes_to_json():
    import json
    json.dumps(build_info(SONG, None, AUDIO, FILES, TIMING, environment={}))


def test_probe_environment_never_raises_and_has_expected_keys():
    env = probe_environment()
    for key in ("centrifugue_version", "python", "platform", "device",
                "demucs", "audio_separator", "torch", "yt_dlp"):
        assert key in env
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_info.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'centrifugue_info'`

- [ ] **Step 3: Implement the info module**

`native-host/centrifugue_info.py`:

```python
"""Builds the info.json sidecar describing how a render was produced."""

import platform
import subprocess
import sys

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_info.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add native-host/centrifugue_info.py tests/test_info.py
git commit -m "Add info.json builder and environment probe"
```

---

### Task 5: Atomic publish helper

**Files:**
- Create: `tests/test_publish.py`
- Modify: `native-host/centrifugue_naming.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `publish_folder(temp_dir: Path, target: Path, overwrite: bool) -> Path`

- [ ] **Step 1: Write the failing tests**

`tests/test_publish.py`:

```python
import pytest
from centrifugue_naming import publish_folder


def test_publishes_temp_dir_to_target(tmp_path):
    temp = tmp_path / ".song.tmp"
    temp.mkdir()
    (temp / "vocals.flac").write_text("audio")
    target = tmp_path / "song"

    publish_folder(temp, target, overwrite=False)

    assert target.is_dir()
    assert (target / "vocals.flac").read_text() == "audio"
    assert not temp.exists()


def test_overwrite_replaces_existing_contents(tmp_path):
    target = tmp_path / "song"
    target.mkdir()
    (target / "stale.flac").write_text("old")

    temp = tmp_path / ".song.tmp"
    temp.mkdir()
    (temp / "vocals.flac").write_text("new")

    publish_folder(temp, target, overwrite=True)

    assert (target / "vocals.flac").read_text() == "new"
    assert not (target / "stale.flac").exists()


def test_refuses_to_overwrite_when_not_requested(tmp_path):
    target = tmp_path / "song"
    target.mkdir()
    temp = tmp_path / ".song.tmp"
    temp.mkdir()

    with pytest.raises(FileExistsError):
        publish_folder(temp, target, overwrite=False)


def test_leaves_no_temp_dir_behind_on_success(tmp_path):
    temp = tmp_path / ".song.tmp"
    temp.mkdir()
    publish_folder(temp, tmp_path / "song", overwrite=False)
    assert list(tmp_path.glob(".*.tmp")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_publish.py -v`
Expected: FAIL — `ImportError: cannot import name 'publish_folder'`

- [ ] **Step 3: Implement `publish_folder`**

Move `import os` and `import shutil` up into the existing import block at the
top of `native-host/centrifugue_naming.py` (beside `re` and `unicodedata`),
then append the function to the end of the file:

```python
def publish_folder(temp_dir, target, overwrite):
    """Move a fully-built temp dir into place in one atomic rename.

    Ableton watches output folders, so it must never observe a partially
    written one. Same-volume directory rename is atomic; on overwrite the
    old folder is only deleted after the new one is in place.
    """
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        if not overwrite:
            raise FileExistsError(f"{target} already exists")
        retired = target.with_name(f".{target.name}.old")
        shutil.rmtree(retired, ignore_errors=True)
        os.rename(target, retired)
        try:
            os.rename(temp_dir, target)
        except OSError:
            os.rename(retired, target)
            raise
        shutil.rmtree(retired, ignore_errors=True)
    else:
        os.rename(temp_dir, target)

    return target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_publish.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add native-host/centrifugue_naming.py tests/test_publish.py
git commit -m "Add atomic folder publish for output directories"
```

---

### Task 6: Wire the host to the new modules

**Files:**
- Modify: `native-host/centrifugue_host.py:96-99` (`get_download_dir`)
- Modify: `native-host/centrifugue_host.py:589-815` (`run_stem_separation_background`)

**Interfaces:**
- Consumes: `slugify`, `resolve_output_folder`, `publish_folder`, `load_config`, `get_output_dir`, `build_info`, `probe_environment`.
- Produces: no new public functions.

- [ ] **Step 1: Import the modules and repoint `get_download_dir`**

Replace `get_download_dir` (line 96):

```python
from centrifugue_config import load_config, get_output_dir
from centrifugue_naming import slugify, resolve_output_folder, publish_folder
from centrifugue_info import build_info, probe_environment


def get_download_dir():
    """Configured output directory, defaulting to ~/Downloads."""
    return get_output_dir()
```

- [ ] **Step 2: Fail early if the output dir is unusable**

At the top of `run_stem_separation_background`, before the download step:

```python
    download_dir = get_download_dir()
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        write_progress('error', f'Output folder is not writable: {exc}',
                       error=str(exc), job_id=job_id, video_title=title,
                       action='download_stems', quality=quality, genre=genre)
        clear_job_state()
        return
```

- [ ] **Step 3: Capture timing, audio, and identity locals**

These must be initialised near the top of `run_stem_separation_background`,
before any of the later steps read them:

```python
    import re as _re
    from datetime import datetime, timezone

    started_epoch = time.time()
    started_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    download_seconds = None
    separation_seconds = None
    duration_seconds = None
    audio_sample_rate = None
    audio_channels = None
    models_used = []

    _m = _re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})', url or '')
    video_id = _m.group(1) if _m else None
```

Then populate them at these exact points:

Immediately after `audio_file` is resolved from the yt-dlp download (the
`wav_files[0]` assignment, around line 659):

```python
        download_seconds = round(time.time() - started_epoch, 2)
        duration_seconds = get_audio_duration(audio_file)
        audio_sample_rate, audio_channels = probe_audio_stream(audio_file)
```

Add this helper next to `get_audio_duration` (around line 287). It mirrors that
function's ffprobe usage and returns `(None, None)` rather than raising, so a
missing ffprobe never fails a job:

```python
def probe_audio_stream(file_path):
    """Return (sample_rate, channels) for an audio file, or (None, None)."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None, None
    try:
        result = subprocess.run(
            [ffprobe, '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=sample_rate,channels',
             '-of', 'default=nw=1:nk=1', str(file_path)],
            capture_output=True, text=True, timeout=30)
        parts = result.stdout.split()
        return int(parts[0]), int(parts[1])
    except Exception:
        return None, None
```

Set `separation_start = time.time()` immediately before the first separation
stage runs, and immediately after the last stage completes:

```python
        separation_seconds = round(time.time() - separation_start, 2)
```

- [ ] **Step 4: Record the model chain**

Where `run_roformer_stage` is invoked, append:

```python
        models_used.append({'stage': 'vocals', 'kind': 'bs-roformer',
                            'name': 'model_bs_roformer_ep_317_sdr_12.9755'})
```

Where `run_demucs_stage` is invoked, append (using that call's real arguments):

```python
        models_used.append({'stage': 'instruments', 'kind': 'demucs',
                            'name': model, 'shifts': shifts, 'overlap': overlap})
```

- [ ] **Step 5: Replace the finalize block**

Replace the "Step 3: Organize output files" block (currently lines 750-780, the `quality_suffix`/`genre_suffix`/`stem_mapping` logic) with:

```python
        import json as _json
        from datetime import datetime, timezone

        config = load_config()
        slug = slugify(title,
                       max_length=config.get('naming', {}).get('max_length', 80),
                       video_id=video_id)

        def _read_info(folder):
            try:
                return _json.loads((folder / 'info.json').read_text())
            except (OSError, ValueError):
                return None

        target, overwrite = resolve_output_folder(
            download_dir, slug, genre, quality, read_info=_read_info)

        staging = download_dir / f".{target.name}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)

        copied_files = []

        def _place(stem_key, source):
            dest = staging / f"{stem_key}{source.suffix}"
            shutil.copy2(source, dest)
            copied_files.append({
                'stem': stem_key,
                'filename': dest.name,
                'bytes': dest.stat().st_size,
            })

        for stem_name in genre_mode['stems']:
            if stem_name in stem_files:
                _place(stem_name, stem_files[stem_name])

        if 'beat' in stem_files:
            _place('beat', stem_files['beat'])
        elif 'combine' in genre_mode:
            for combined_name, source_stems in genre_mode['combine'].items():
                sources = [stem_files[s] for s in source_stems if s in stem_files]
                if sources:
                    dest = staging / f"{combined_name}{sources[0].suffix}"
                    if combine_stems(sources, dest):
                        copied_files.append({
                            'stem': combined_name,
                            'filename': dest.name,
                            'bytes': dest.stat().st_size,
                        })
```

- [ ] **Step 6: Write `info.json` and publish**

Immediately after the placement block, before the temp-dir cleanup:

```python
        if not copied_files:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_job_state()
            write_progress('error', 'No stem files were created',
                          error='No output files', job_id=job_id, video_title=title,
                          action='download_stems', quality=quality, genre=genre)
            return

        if config.get('write_info_json', True):
            ext = Path(copied_files[0]['filename']).suffix.lstrip('.')
            info = build_info(
                song={'title': title, 'slug': slug, 'url': url,
                      'video_id': video_id, 'duration_seconds': duration_seconds},
                separation={'genre_mode': genre, 'quality_preset': quality,
                            'stems': [f['stem'] for f in copied_files],
                            'models': models_used},
                audio={'format': ext, 'codec': ext,
                       'sample_rate': audio_sample_rate, 'channels': audio_channels,
                       'bit_depth': 16 if ext == 'flac' else None},
                files=copied_files,
                timing={'started_at': started_at,
                        'completed_at': datetime.now(timezone.utc)
                                        .strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'download_seconds': download_seconds,
                        'separation_seconds': separation_seconds,
                        'total_seconds': round(time.time() - started_epoch, 2)},
                environment=probe_environment(),
            )
            (staging / 'info.json').write_text(_json.dumps(info, indent=2) + '\n')

        publish_folder(staging, target, overwrite)
```

- [ ] **Step 7: Verify the full suite still passes**

Run: `./venv-demucs/bin/python -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1-5)

Run: `./venv-demucs/bin/python -c "import sys; sys.path.insert(0,'native-host'); import centrifugue_host"`
Expected: no output (imports cleanly)

- [ ] **Step 8: Commit**

```bash
git add native-host/centrifugue_host.py
git commit -m "Write stems to configured folder with info.json sidecar"
```

---

### Task 7: `get_config` / `set_config` native actions

**Files:**
- Modify: `native-host/centrifugue_host.py:988-1050` (`main` dispatch)
- Modify: `extension-firefox/background.js`
- Modify: `extension-chrome/background.js`

**Interfaces:**
- Consumes: `load_config`, `save_config` from Task 3.
- Produces: native actions `get_config` → `{success, config}`; `set_config` → `{success, config}` or `{success: false, error}`.

- [ ] **Step 1: Add the actions to the host dispatch**

Insert before the `elif action == 'ping':` branch:

```python
    elif action == 'get_config':
        send_message({'success': True, 'config': load_config()})

    elif action == 'set_config':
        try:
            updated = save_config(message.get('config') or {})
            send_message({'success': True, 'config': updated})
        except ValueError as exc:
            send_message({'success': False, 'error': str(exc)})
```

Add `save_config` to the existing `centrifugue_config` import at the top.

- [ ] **Step 2: Verify by hand**

Run:

```bash
printf '\x11\x00\x00\x00{"action":"get_config"}' | ./venv-demucs/bin/python native-host/centrifugue_host.py | tail -c +5
```

Expected: JSON containing `"output_dir"`. (The 4-byte prefix is the native-messaging length header for a 17-byte body.)

- [ ] **Step 3: Relay the actions in both background scripts**

In each `background.js`, alongside the existing `get_progress` handling, add to the message router:

```javascript
  if (message.action === "get_config") {
    return await sendToNativeHost({ action: "get_config" });
  }

  if (message.action === "set_config") {
    return await sendToNativeHost({
      action: "set_config",
      config: message.config,
    });
  }
```

- [ ] **Step 4: Commit**

```bash
git add native-host/centrifugue_host.py extension-firefox/background.js extension-chrome/background.js
git commit -m "Add get_config and set_config native messaging actions"
```

---

### Task 8: Popup settings UI

**Files:**
- Modify: `extension-firefox/popup/popup.html`, `extension-firefox/popup/popup.js`
- Modify: `extension-chrome/popup/popup.html`, `extension-chrome/popup/popup.js`

**Interfaces:**
- Consumes: `get_config` / `set_config` from Task 7.
- Produces: no new interfaces.

Apply identical changes to both copies.

- [ ] **Step 1: Add the settings markup**

In `popup.html`, after the `cancelBtn` button (line ~223):

```html
  <details id="settings">
    <summary>Settings</summary>
    <label for="outputDir">Output folder</label>
    <input id="outputDir" type="text" spellcheck="false"
           placeholder="~/Downloads" />
    <button id="saveSettingsBtn">Save</button>
    <div id="settingsStatus"></div>
  </details>
```

- [ ] **Step 2: Load the current value when the popup opens**

In `popup.js`, add and call from the existing init path:

```javascript
async function loadSettings() {
  try {
    const response = await browser.runtime.sendMessage({ action: "get_config" });
    if (response && response.success) {
      document.getElementById("outputDir").value = response.config.output_dir;
    }
  } catch (e) {
    // Settings are non-critical: a failure here must not block downloads.
  }
}
```

- [ ] **Step 3: Save on click, surfacing host validation errors**

```javascript
async function saveSettings() {
  const status = document.getElementById("settingsStatus");
  const outputDir = document.getElementById("outputDir").value.trim();
  status.textContent = "Saving...";
  try {
    const response = await browser.runtime.sendMessage({
      action: "set_config",
      config: { output_dir: outputDir },
    });
    status.textContent =
      response && response.success ? "Saved" : `Error: ${response.error}`;
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
  }
}

document.getElementById("saveSettingsBtn")
  .addEventListener("click", saveSettings);
loadSettings();
```

- [ ] **Step 4: Verify in the browser**

Run `./build-xpi.sh`, reload the extension, open the popup, expand Settings.
Expected: the field shows the current output folder. Enter a bad path such as
`/proc/nope` and click Save.
Expected: an inline `Error: output_dir is not writable: ...` rather than a silent failure.

- [ ] **Step 5: Commit**

```bash
git add extension-firefox/popup extension-chrome/popup
git commit -m "Add output folder setting to extension popup"
```

---

### Task 9: README documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Configuration section**

After the installation section, documenting `~/.centrifugue/config.json` with the key table from the spec (`output_dir`, `naming.style`, `naming.max_length`, `write_info_json`), and noting the setting is also editable from the popup.

- [ ] **Step 2: Add the Ableton note**

```markdown
### Using stems in Ableton Live

Set the output folder to `~/Music/Ableton/User Library/Centrifugue`. The User
Library is already a Place in Live's browser, so new song folders appear while
a project is open -- no restart and no manual rescan. Stems are published
atomically, so Live never sees a half-written folder.

FLAC (the Ultra preset's output) requires Live 11 or newer.
```

- [ ] **Step 3: Add the `info.json` reference table**

Document every key with path, type, and meaning:

| Key | Type | Description |
|-----|------|-------------|
| `schema_version` | int | Sidecar format version. Currently `1`. |
| `song.title` | string | Original video title, unmodified. |
| `song.slug` | string | Normalized name used for the folder. |
| `song.url` | string | Source URL. |
| `song.video_id` | string\|null | YouTube video id, `null` if not parsed. |
| `song.duration_seconds` | float\|null | Source audio duration. |
| `separation` | object\|null | Present for stem jobs. |
| `separation.genre_mode` | string | `full`, `hiphop`, or `rock`. |
| `separation.quality_preset` | string | `fast`, `balanced`, or `ultra`. |
| `separation.stems` | string[] | Stem keys produced. |
| `separation.models` | object[] | Model chain in run order. |
| `separation.models[].stage` | string | `vocals` or `instruments`. |
| `separation.models[].kind` | string | `bs-roformer` or `demucs`. |
| `separation.models[].name` | string | Model identifier. |
| `separation.models[].shifts` | int\|null | Demucs shift passes. |
| `separation.models[].overlap` | float\|null | Demucs overlap. |
| `audio.format` | string | Container/extension, e.g. `flac`. |
| `audio.codec` | string | Codec name. |
| `audio.sample_rate` | int\|null | Hz. |
| `audio.channels` | int\|null | Channel count. |
| `audio.bit_depth` | int\|null | `null` for lossy formats. |
| `files[].stem` | string | Stem key. |
| `files[].filename` | string | Name within the folder. |
| `files[].bytes` | int | File size. |
| `timing.started_at` | string | UTC ISO-8601, `Z` suffix. |
| `timing.completed_at` | string | UTC ISO-8601, `Z` suffix. |
| `timing.download_seconds` | float\|null | yt-dlp time. |
| `timing.separation_seconds` | float\|null | Model time. |
| `timing.total_seconds` | float | Wall-clock total. |
| `environment.centrifugue_version` | string | App version. |
| `environment.python` | string | Interpreter version. |
| `environment.platform` | string | OS-release-arch. |
| `environment.device` | string\|null | `mps`, `cuda`, or `cpu`. |
| `environment.demucs` | string\|null | Package version. |
| `environment.audio_separator` | string\|null | Package version. |
| `environment.torch` | string\|null | Package version. |
| `environment.yt_dlp` | string\|null | Binary version. |

Note that MP3-only downloads honour `output_dir` but produce no folder and no
`info.json`.

- [ ] **Step 4: Update the Architecture tree**

Add `centrifugue_naming.py`, `centrifugue_config.py`, `centrifugue_info.py` under `native-host/`, and a `tests/` entry.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "Document output configuration and info.json schema"
```

---

## Manual Integration Test

After Task 9, run one real job end to end:

- [ ] Set the output folder to `~/Music/Ableton/User Library/Centrifugue` via the popup.
- [ ] Download stems for a short video, genre `rock`, quality `fast`.
- [ ] Confirm `<output>/<slug>/` contains `vocals.mp3`, `drums.mp3`, `bass.mp3`, `info.json`.
- [ ] Confirm `info.json` `files[]` matches what is on disk and `timing.total_seconds` is plausible.
- [ ] Re-run identical settings → same folder, contents replaced, no `_2`.
- [ ] Re-run with genre `full` → new `<slug>_full_fast/` folder.
- [ ] With Live open, confirm the folder appears in the browser without restarting Live.
