"""Filename and folder naming for Centrifugue output.

Pure functions: no filesystem writes, no network. Kept separate from
centrifugue_host.py so the rules can be unit-tested without a browser,
a model, or a download.
"""

import os
import re
import shutil
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
