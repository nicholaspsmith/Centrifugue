"""BPM and musical-key detection for separated stems.

Detection runs *after* separation, which is the whole point: beat tracking
on an isolated drums stem beats beat tracking on a full mix, and chroma on
bass+other (percussion removed) beats chroma on a full mix. The stems are
already on disk, so the accuracy is free.

Two audiences, one module:

  * Pure helpers (key formatting, Camelot, tempo folding, filename
    suffixing) import with nothing but the standard library, so the host
    -- which the browser spawns under *system* python -- and the unit
    tests can both use them.
  * The detectors need librosa/numpy, which live only in venv-demucs.
    They import lazily, and the host reaches them by running this file as
    a script under the venv interpreter (see `--json`).
"""

import argparse
import json
import math
import re
import sys

# Sharps, not flats: a flat sign has no ASCII form and "Db" vs "C#" would
# make filenames inconsistent with the Camelot table below.
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Camelot wheel: index by pitch class, per mode. Adjacent numbers are
# harmonically compatible, which is the only reason to carry it at all.
_CAMELOT_MAJOR = ("8B", "3B", "10B", "5B", "12B", "7B",
                  "2B", "9B", "4B", "11B", "6B", "1B")
_CAMELOT_MINOR = ("5A", "12A", "7A", "2A", "9A", "4A",
                  "11A", "6A", "1A", "8A", "3A", "10A")

# Krumhansl-Kessler key profiles. Correlating an averaged chroma vector
# against all 24 rotations of these is the standard key-finding method.
KK_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
            2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
KK_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
            2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

# Tempo octave-folding window. Live's own auto-warp makes the same class
# of error; validating our .asd parser against Ableton's factory previews
# turned up 63 clips warped at exactly double their labelled tempo.
DEFAULT_TEMPO_RANGE = (70.0, 180.0)

ANALYSIS_SR = 22050


# --------------------------------------------------------------------------
# Pure helpers -- no third-party imports, safe under system python
# --------------------------------------------------------------------------

def format_key(pitch_class, mode):
    """Render a key as `Fmin` / `F#maj`. Returns None for bad input."""
    if pitch_class is None or mode not in ("major", "minor"):
        return None
    try:
        name = NOTE_NAMES[int(pitch_class) % 12]
    except (TypeError, ValueError):
        return None
    return f"{name}{'maj' if mode == 'major' else 'min'}"


def camelot(pitch_class, mode):
    """Render a key in Camelot wheel notation (`4A`). None for bad input."""
    if pitch_class is None or mode not in ("major", "minor"):
        return None
    try:
        idx = int(pitch_class) % 12
    except (TypeError, ValueError):
        return None
    return (_CAMELOT_MAJOR if mode == "major" else _CAMELOT_MINOR)[idx]


def fold_tempo(bpm, low=None, high=None):
    """Halve/double a tempo until it lands in the expected window.

    Beat trackers routinely land an octave out. Folding is only ever a
    guess, but it is the same guess a human makes when they see 62 BPM on
    a drum'n'bass track.
    """
    if bpm is None:
        return None
    try:
        value = float(bpm)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None

    lo, hi = DEFAULT_TEMPO_RANGE
    if low is not None:
        lo = float(low)
    if high is not None:
        hi = float(high)
    if lo <= 0 or hi <= lo:
        return round(value, 2)

    # Guard the loops: a pathological range could otherwise spin forever.
    for _ in range(12):
        if value < lo:
            value *= 2
        else:
            break
    for _ in range(12):
        if value >= hi:
            value /= 2
        else:
            break
    return round(value, 2)


def format_bpm(bpm):
    """`124` for a whole tempo, `123.5` otherwise. None stays None."""
    if bpm is None:
        return None
    try:
        value = float(bpm)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    rounded = round(value, 1)
    if abs(rounded - round(rounded)) < 0.05:
        return str(int(round(rounded)))
    return f"{rounded:.1f}"


def format_bpm_integer(bpm):
    """Whole-number tempo for filenames and ID3. None stays None."""
    if bpm is None:
        return None
    try:
        value = float(bpm)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return str(int(round(value)))


def analysis_suffix(bpm=None, key=None):
    """Build the `_124bpm_Fmin` filename tail. Empty when nothing is known.

    Rounded to a whole number deliberately. Sample libraries name tempos as
    integers, and `beat_101.3bpm` reads as noise; the exact 101.33 that makes
    a three-minute warp line up is kept in the Live Set and info.json, where
    precision actually does something.
    """
    parts = []
    tempo = format_bpm_integer(bpm)
    if tempo:
        parts.append(f"{tempo}bpm")
    if key:
        parts.append(str(key))
    return ("_" + "_".join(parts)) if parts else ""


def _split_extension(filename):
    """Split on the final dot only -- stem names never carry a real suffix."""
    idx = str(filename).rfind(".")
    if idx <= 0:
        return str(filename), ""
    return str(filename)[:idx], str(filename)[idx:]


def strip_analysis_suffix(filename):
    """Remove a previously applied `_124bpm_Fmin` tail.

    Backfilling a folder twice must not produce `vocals_124bpm_Fmin_124bpm_Fmin`,
    and a re-analysis that lands on a different tempo has to replace the old
    tail rather than append to it.
    """
    base, ext = _split_extension(filename)
    base = re.sub(
        r"_\d+(?:\.\d+)?bpm(?:_[A-G]#?(?:maj|min))?(?:_\d{1,2}[AB])?$",
        "", base, flags=re.IGNORECASE)
    return base + ext


def apply_analysis_suffix(filename, bpm=None, key=None):
    """`vocals.flac` -> `vocals_124bpm_Fmin.flac`, idempotently."""
    base, ext = _split_extension(strip_analysis_suffix(filename))
    return base + analysis_suffix(bpm, key) + ext


# --------------------------------------------------------------------------
# Detection -- needs librosa, so only ever called under the venv interpreter
# --------------------------------------------------------------------------

def _load(path, sr=ANALYSIS_SR):
    import librosa
    audio, rate = librosa.load(str(path), sr=sr, mono=True)
    return audio, rate


# Finer than librosa's 512 default. The tempogram's usable tempo bins are
# `frame_rate * 60 / lag` for integer lag, so at hop=512 the bins either
# side of 140 BPM are 136.0 and 143.6 -- 140 is not a representable answer.
# Shrinking the hop tightens that grid, but the real fix is below: read the
# tempo off the tracked beat positions instead of off a tempogram bin.
BEAT_HOP = 256


def detect_bpm(path, tempo_range=DEFAULT_TEMPO_RANGE):
    """Estimate tempo from one audio file.

    The tempo comes from the spacing of the beats the tracker actually
    found, not from the tempogram peak it started at. Beat frames are
    quantised to the hop grid, but a median over hundreds of beats averages
    that quantisation away, and a least-squares fit over the beat indices
    sharpens it further. On a three-minute drums stem that is a far finer
    estimate than any single tempogram bin can express.

    Confidence deliberately does *not* reward a steady pulse on its own --
    a tracker locked onto the wrong multiple is perfectly steady. It is the
    agreement between two independent estimates (tempogram vs beat spacing)
    scaled by how rhythmic the material is.
    """
    import numpy as np
    import librosa

    audio, sr = _load(path)
    if audio.size == 0:
        return {"bpm": None, "confidence": 0.0, "raw_bpm": None}

    onset = librosa.onset.onset_strength(y=audio, sr=sr, hop_length=BEAT_HOP,
                                         aggregate=np.median)
    if onset.size == 0 or not np.any(onset):
        return {"bpm": None, "confidence": 0.0, "raw_bpm": None}

    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr,
                                           hop_length=BEAT_HOP, trim=False)
    grid_bpm = float(np.atleast_1d(tempo)[0]) if np.size(tempo) else None

    times = librosa.frames_to_time(beats, sr=sr, hop_length=BEAT_HOP)
    beat_bpm = None
    steadiness = 0.0

    if times.size >= 3:
        intervals = np.diff(times)
        intervals = intervals[intervals > 0]
        if intervals.size >= 2:
            median_interval = float(np.median(intervals))
            if median_interval > 0:
                beat_bpm = 60.0 / median_interval
                spread = float(np.median(np.abs(intervals - median_interval)))
                steadiness = max(0.0, min(1.0, 1.0 - (spread / median_interval) * 8.0))

                # Least-squares refinement, but only over the stretch of beats
                # that actually kept time -- one dropped beat would otherwise
                # drag the slope and make a good estimate worse.
                keep = np.abs(intervals - median_interval) < median_interval * 0.25
                if keep.sum() >= max(4, int(0.6 * keep.size)):
                    idx = np.flatnonzero(
                        np.concatenate(([True], keep)))[: keep.sum() + 1]
                    if idx.size >= 4:
                        selected = times[idx]
                        positions = np.round(
                            (selected - selected[0]) / median_interval)
                        if np.all(np.diff(positions) > 0):
                            slope = np.polyfit(positions, selected, 1)[0]
                            if slope > 0:
                                refined = 60.0 / slope
                                # Only trust the fit if it agrees with the
                                # robust median; otherwise it has gone astray.
                                if abs(refined - beat_bpm) < beat_bpm * 0.05:
                                    beat_bpm = refined

    raw = beat_bpm if beat_bpm else grid_bpm
    if raw is None or not math.isfinite(raw) or raw <= 0:
        return {"bpm": None, "confidence": 0.0, "raw_bpm": None}

    # Two independent estimates agreeing (after octave folding, since they
    # can legitimately disagree by a factor of two) is real evidence.
    agreement = 0.0
    if beat_bpm and grid_bpm:
        folded_beat = fold_tempo(beat_bpm, *tempo_range)
        folded_grid = fold_tempo(grid_bpm, *tempo_range)
        if folded_beat and folded_grid:
            error = abs(folded_beat - folded_grid) / folded_beat
            agreement = max(0.0, min(1.0, 1.0 - error * 20.0))

    # Sparse or arrhythmic material should not report high confidence no
    # matter how tidily the tracker fit a grid to it.
    density = min(1.0, float(np.size(beats)) / 32.0)
    confidence = round(agreement * (0.5 + 0.5 * steadiness) * (0.4 + 0.6 * density), 3)

    return {
        "bpm": fold_tempo(raw, *tempo_range),
        "raw_bpm": round(raw, 3),
        "grid_bpm": round(grid_bpm, 3) if grid_bpm else None,
        "confidence": confidence,
        "beat_count": int(np.size(beats)),
    }


def detect_key(paths, use_hpss=True):
    """Estimate key by correlating averaged chroma against KK profiles.

    Multiple paths are summed first: bass carries the root motion and
    `other` carries the harmony, and neither alone is as reliable as the
    pair. Confidence is the margin over the runner-up key, so a track that
    sits ambiguously between relative major and minor reports low.
    """
    import numpy as np
    import librosa

    mixed = None
    for path in paths:
        audio, _ = _load(path)
        if audio.size == 0:
            continue
        if mixed is None:
            mixed = audio.astype(np.float64)
        else:
            length = min(mixed.size, audio.size)
            mixed = mixed[:length] + audio[:length].astype(np.float64)

    if mixed is None or mixed.size == 0:
        return {"key": None, "camelot": None, "confidence": 0.0,
                "tonic": None, "mode": None}

    peak = float(np.max(np.abs(mixed)))
    if peak > 0:
        mixed = mixed / peak

    if use_hpss:
        # Percussive transients smear the chroma; drop them.
        mixed = librosa.effects.harmonic(mixed.astype(np.float32), margin=4.0)

    chroma = librosa.feature.chroma_cqt(y=np.asarray(mixed, dtype=np.float32),
                                        sr=ANALYSIS_SR, bins_per_octave=36)
    profile = np.mean(chroma, axis=1)
    if not np.any(profile):
        return {"key": None, "camelot": None, "confidence": 0.0,
                "tonic": None, "mode": None}

    major = np.asarray(KK_MAJOR, dtype=np.float64)
    minor = np.asarray(KK_MINOR, dtype=np.float64)

    scores = []
    for pitch_class in range(12):
        rotated = np.roll(profile, -pitch_class)
        for mode, template in (("major", major), ("minor", minor)):
            matrix = np.corrcoef(rotated, template)
            score = matrix[0, 1]
            if math.isfinite(score):
                scores.append((float(score), pitch_class, mode))

    if not scores:
        return {"key": None, "camelot": None, "confidence": 0.0,
                "tonic": None, "mode": None}

    scores.sort(reverse=True)
    best_score, tonic, mode = scores[0]
    runner_up = scores[1][0] if len(scores) > 1 else 0.0
    # Margin over the next-best key, scaled so a decisive win reads ~1.0.
    confidence = max(0.0, min(1.0, (best_score - runner_up) * 5.0))

    return {
        "key": format_key(tonic, mode),
        "camelot": camelot(tonic, mode),
        "tonic": NOTE_NAMES[tonic],
        "mode": mode,
        "correlation": round(best_score, 4),
        "confidence": round(confidence, 3),
    }


def analyse(bpm_source, key_sources, tempo_range=DEFAULT_TEMPO_RANGE):
    """Run both detectors. Either half failing must not lose the other."""
    result = {"bpm": None, "bpm_confidence": 0.0, "key": None,
              "camelot": None, "key_confidence": 0.0}

    if bpm_source:
        try:
            tempo = detect_bpm(bpm_source, tempo_range=tempo_range)
            result["bpm"] = tempo.get("bpm")
            result["raw_bpm"] = tempo.get("raw_bpm")
            result["bpm_confidence"] = tempo.get("confidence", 0.0)
        except Exception as exc:
            result["bpm_error"] = str(exc)

    if key_sources:
        try:
            key = detect_key(key_sources)
            result["key"] = key.get("key")
            result["camelot"] = key.get("camelot")
            result["mode"] = key.get("mode")
            result["key_confidence"] = key.get("confidence", 0.0)
        except Exception as exc:
            result["key_error"] = str(exc)

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bpm-from", dest="bpm_from")
    parser.add_argument("--key-from", dest="key_from", action="append", default=[])
    parser.add_argument("--tempo-min", type=float, default=DEFAULT_TEMPO_RANGE[0])
    parser.add_argument("--tempo-max", type=float, default=DEFAULT_TEMPO_RANGE[1])
    args = parser.parse_args(argv)

    result = analyse(args.bpm_from, args.key_from,
                     tempo_range=(args.tempo_min, args.tempo_max))
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
