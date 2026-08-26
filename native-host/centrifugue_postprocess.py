"""Post-separation analysis: detect, rename, tag, and write Ableton sidecars.

One code path serves both callers -- the worker finishing a fresh render and
the `analyze` CLI backfilling folders that were separated before any of this
existed -- so a backfilled folder is byte-for-byte what a fresh render would
have produced.

Everything here is best-effort by design. A song whose key will not resolve
still gets its BPM; a missing ffmpeg costs the tags but not the filenames.
Losing the whole render because a detector was unsure would be a much worse
outcome than an incomplete sidecar.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from centrifugue_analysis import (apply_analysis_suffix, strip_analysis_suffix,
                                  format_bpm_integer)

AUDIO_EXTENSIONS = (".flac", ".wav", ".mp3", ".aiff", ".aif", ".m4a", ".ogg")

# Stem preferred for tempo. Isolated drums beat a full mix; in hiphop mode
# there is no drums stem, so the vocals-removed `beat` stands in.
BPM_STEM_ORDER = ("drums", "beat", "other", "bass", "instrumental")

# Stems preferred for key. Percussion smears chroma, so drums are excluded;
# bass carries the root and `other` the harmony.
KEY_STEM_ORDER = ("bass", "other", "instrumental", "beat")

# Only if nothing above exists. A vocal line is monophonic and full of
# bends and passing tones, so it is a poor chroma source -- worth using
# alone, not worth mixing in alongside a stem that carries real harmony.
KEY_STEM_FALLBACK = ("vocals",)

# Track order in the generated Live Set. The first track becomes the song
# tempo master, so a rhythmic stem must come first.
TRACK_ORDER = ("drums", "beat", "bass", "other", "instrumental", "vocals")


def find_stems(folder):
    """Map stem name -> path for one output folder, ignoring the suffix."""
    stems = {}
    try:
        entries = sorted(Path(folder).iterdir())
    except OSError:
        return stems
    for entry in entries:
        if not entry.is_file() or entry.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        base = Path(strip_analysis_suffix(entry.name)).stem
        stems[base] = entry
    return stems


def pick_sources(stems):
    """Choose which stems feed each detector. Returns (bpm_path, key_paths)."""
    bpm_source = None
    for name in BPM_STEM_ORDER:
        if name in stems:
            bpm_source = stems[name]
            break
    if bpm_source is None and stems:
        bpm_source = next(iter(stems.values()))

    key_sources = [stems[name] for name in KEY_STEM_ORDER if name in stems]
    if not key_sources:
        key_sources = [stems[name] for name in KEY_STEM_FALLBACK if name in stems]
    if not key_sources and stems:
        key_sources = [next(iter(stems.values()))]
    # Two stems is the useful maximum: a third adds load time, not accuracy.
    return bpm_source, key_sources[:2]


def run_analysis(venv_python, bpm_source, key_sources, tempo_range=None,
                 timeout=600, log=None):
    """Run the detectors inside the Demucs venv and return their JSON.

    librosa lives in venv-demucs, and the host runs under system python when
    the browser spawns it, so this has to cross a process boundary -- the
    same reason centrifugue_info probes the venv rather than importing torch.
    """
    script = Path(__file__).resolve().parent / "centrifugue_analysis.py"
    command = [str(venv_python), str(script)]
    if bpm_source:
        command += ["--bpm-from", str(bpm_source)]
    for source in key_sources or []:
        command += ["--key-from", str(source)]
    if tempo_range:
        command += ["--tempo-min", str(tempo_range[0]),
                    "--tempo-max", str(tempo_range[1])]

    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        if log:
            log(f"analysis failed to launch: {exc}")
        return None

    if result.returncode != 0:
        if log:
            log(f"analysis exited {result.returncode}: {result.stderr[-400:]}")
        return None

    try:
        return json.loads(result.stdout)
    except ValueError:
        if log:
            log(f"analysis produced unparseable output: {result.stdout[:200]}")
        return None


def plan_renames(paths, bpm=None, key=None):
    """Map each path to its suffixed name. Pure, so the edge cases are testable.

    Collisions are dropped rather than resolved: two stems that would land on
    one name means something is already wrong, and silently clobbering one is
    worse than leaving both alone.
    """
    planned = {}
    taken = set()
    for path in paths:
        path = Path(path)
        new_name = apply_analysis_suffix(path.name, bpm, key)
        if new_name == path.name:
            taken.add(new_name)
            continue
        if new_name in taken or (path.parent / new_name).exists():
            continue
        taken.add(new_name)
        planned[path] = path.parent / new_name
    return planned


def apply_renames(planned, log=None):
    """Rename stems, carrying any Live .asd sidecar along with them.

    An .asd is bound to its audio file by name. Leaving it behind would
    orphan Live's existing analysis and leave a stale file in the folder.
    """
    renamed = {}
    for source, target in planned.items():
        try:
            os.rename(source, target)
        except OSError as exc:
            if log:
                log(f"rename failed for {source.name}: {exc}")
            continue
        renamed[source] = target

        sidecar = source.with_name(source.name + ".asd")
        if sidecar.exists():
            try:
                os.rename(sidecar, target.with_name(target.name + ".asd"))
            except OSError:
                pass
    return renamed


def _tag_arguments(suffix, bpm, key, camelot):
    """Per-format metadata keys.

    FLAC/Ogg take free-form Vorbis comments; MP3 needs the ID3v2 frame names
    (TBPM/TKEY) or the values land in a TXXX frame nothing reads.
    """
    tempo = format_bpm_integer(bpm)
    args = []
    if suffix in (".mp3",):
        if tempo:
            args += ["-metadata", f"TBPM={tempo}"]
        if key:
            args += ["-metadata", f"TKEY={key}"]
        if camelot:
            args += ["-metadata", f"TXXX=CAMELOT={camelot}"]
    else:
        if tempo:
            args += ["-metadata", f"BPM={tempo}"]
        if key:
            args += ["-metadata", f"KEY={key}", "-metadata", f"INITIALKEY={key}"]
        if camelot:
            args += ["-metadata", f"CAMELOTKEY={camelot}"]
    if args:
        args += ["-metadata", "COMMENT=Analysed by Centrifugue"]
    return args


def write_tags(path, bpm=None, key=None, camelot=None, ffmpeg="ffmpeg", log=None):
    """Stamp BPM/key into the file's own metadata, losslessly.

    Live 12 ignores these, but Rekordbox, Serato, Mixed In Key and the macOS
    Finder do not, and the tag survives a rename where the filename does not.
    Streams are copied, never re-encoded.
    """
    path = Path(path)
    arguments = _tag_arguments(path.suffix.lower(), bpm, key, camelot)
    if not arguments:
        return False

    handle, temporary = tempfile.mkstemp(suffix=path.suffix, dir=str(path.parent))
    os.close(handle)
    command = ([ffmpeg, "-y", "-loglevel", "error", "-i", str(path),
                "-map", "0", "-c", "copy"] + arguments + [temporary])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            if log:
                log(f"tagging failed for {path.name}: {result.stderr[-200:]}")
            os.unlink(temporary)
            return False
        shutil.move(temporary, path)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        if log:
            log(f"tagging failed for {path.name}: {exc}")
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return False


def probe_duration(path, ffprobe="ffprobe"):
    """Duration in seconds, or None. Never raises."""
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def ordered_stems(stems):
    """Stems in Live-track order, rhythmic first so it can master the tempo."""
    ordered = [(name, stems[name]) for name in TRACK_ORDER if name in stems]
    ordered += [(name, path) for name, path in sorted(stems.items())
                if name not in TRACK_ORDER]
    return ordered


def live_entries(stems, final, ffprobe="ffprobe"):
    """(name, final path, duration) per stem, in Live-track order.

    Durations are probed once here because both Ableton outputs need them
    and probing is the expensive part.
    """
    entries = []
    for name, path in ordered_stems(stems):
        duration = probe_duration(path, ffprobe) or 0.0
        entries.append((name, final / Path(path).name, duration))
    return entries


def write_live_set(folder, stems, bpm, key=None, ffprobe="ffprobe", log=None,
                   final_folder=None):
    """Write `<folder>/<final folder name>.als`. Returns the path, or None.

    `final_folder` exists because a fresh render is assembled in a hidden
    staging directory and only then renamed into place. The Live Set embeds
    absolute sample paths, so those must describe where the stems will *end
    up*, not the staging directory they are written from -- otherwise every
    generated set points at a path that no longer exists by the time anyone
    opens it.
    """
    import centrifugue_ableton as ableton

    folder = Path(folder)
    final = Path(final_folder) if final_folder else folder

    entries = live_entries(stems, final, ffprobe)
    if not entries:
        return None

    target = folder / f"{final.name}.als"
    try:
        ableton.write_als(target, entries, bpm, project_root=final, key=key)
        return target
    except (OSError, ValueError) as exc:
        if log:
            log(f"Live Set generation failed: {exc}")
        return None


def write_live_clips(folder, stems, bpm, key=None, ffprobe="ffprobe",
                     log=None, final_folder=None):
    """Write one `<stem>.alc` Live Clip per stem. Returns the names written.

    These are what makes a stem land in time when it is dragged straight
    into an existing Set. Live reads no tempo from a bare audio file, so it
    estimates one per file and gets a different answer for each stem; a
    Live Clip carries our markers instead, identical across every stem, and
    follows the Set's own tempo.

    Best-effort like everything else here: a stem whose clip fails to write
    still ships its audio, and the caller still gets the rest.
    """
    import centrifugue_ableton as ableton

    folder = Path(folder)
    final = Path(final_folder) if final_folder else folder

    written = []
    for name, sample, duration in live_entries(stems, final, ffprobe):
        target = folder / f"{name}.alc"
        try:
            ableton.write_alc(target, name, sample, duration, bpm,
                              project_root=final, key=key)
            written.append(target.name)
        except (OSError, ValueError) as exc:
            if log:
                log(f"Live Clip generation failed for {name}: {exc}")
    return written


def update_info(folder, analysis, extras=None):
    """Merge an `analysis` block into an existing info.json. Never raises."""
    path = Path(folder) / "info.json"
    try:
        info = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(info, dict):
        return False

    block = {
        "bpm": analysis.get("bpm"),
        "bpm_confidence": analysis.get("bpm_confidence"),
        "key": analysis.get("key"),
        "camelot": analysis.get("camelot"),
        "mode": analysis.get("mode"),
        "key_confidence": analysis.get("key_confidence"),
    }
    block.update(extras or {})
    info["analysis"] = block

    try:
        path.write_text(json.dumps(info, indent=2) + "\n")
        return True
    except OSError:
        return False
