# Configurable Stem Output — Paths, Naming, and `info.json`

**Date:** 2026-08-01
**Status:** Approved
**Primary use case:** Centrifugue → Ableton Live pipeline (Live 11 / 12.4.1)

## Problem

Output location and naming are hardcoded and awkward to consume programmatically:

- `get_download_dir()` always returns `~/Downloads`. There is no way to send
  stems anywhere else, so they cannot land in a folder Ableton already watches.
- Folder names embed the raw YouTube title, genre, and quality:
  `Linkin ParkLimp BizkitSlipknot Style-FFO; Aggressive NU Metal- encore - Isokuici - Rock (Ultra)`.
  Spaces, semicolons, and stray punctuation make these hostile to scripting.
- Stem files repeat the full title: `<title> - Vocals.flac`. The stem type — the
  only part that varies — is buried at the end of a 70-character name.
- Nothing records how a stem was produced. Once files land in `~/Downloads`
  there is no way to tell which model, preset, or Centrifugue version made them.

## Goals

- User-configurable output directory, settable from the extension popup
- One folder per song, named from a normalized slug of the title
- Stem files named solely by stem type (`vocals.flac`, `beat.flac`)
- An `info.json` per song folder capturing provenance, timing, and environment
- Folders appear in Ableton's browser complete, never half-written
- Existing installs keep working with no config file present

## Non-Goals (out of scope)

- Embedding metadata as FLAC Vorbis comments / MP3 ID3 tags (Ableton cannot
  display them; revisit only if another tool needs it)
- Migrating or renaming previously downloaded folders
- Any change to separation quality, models, or preset behaviour
- A native folder picker (browser extensions cannot open one)

## Configuration

Host-owned file at `~/.centrifugue/config.json`, created with defaults on first
run. The host is the source of truth; the popup reads and writes it over native
messaging.

```json
{
  "output_dir": "~/Downloads",
  "naming": { "style": "lowercase_ascii", "max_length": 80 },
  "write_info_json": true
}
```

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `output_dir` | string | `~/Downloads` | Destination root. `~` expanded at read time. |
| `naming.style` | string | `lowercase_ascii` | Only supported value today; reserved for future styles. |
| `naming.max_length` | int | `80` | Max slug length before truncation. |
| `write_info_json` | bool | `true` | Set false to suppress the sidecar. |

Resolution order: config file → built-in default. Unreadable or malformed config
falls back to defaults and logs a warning rather than failing the job. If
`output_dir` does not exist the host creates it; if it cannot (permissions, bad
path) the job fails early with a clear error **before** downloading anything.

Two new native message actions:

- `get_config` → returns the effective config
- `set_config` → validates and persists; rejects an `output_dir` that is not
  writable, returning the reason for display in the popup

## Naming

### Slug algorithm

```
1. Unicode NFKD decompose; drop combining marks       ("café" -> "cafe")
2. Encode to ASCII, ignoring anything left
3. Lowercase
4. Replace every char outside [a-z0-9_-] with "_"
5. Collapse runs of "_" to a single "_"
6. Strip leading/trailing "_" and "-"
7. Truncate to naming.max_length, then strip trailing "_" again
8. If the result is empty, fall back to "video_<video_id>",
   or "untitled" when no video id is available
```

Step 8 is load-bearing: a fully non-Latin title (e.g. Japanese) reduces to an
empty string after step 2, which would otherwise produce a folder named `_` or
crash on an empty path component.

| Input title | Slug |
|-------------|------|
| `RockHard - Foolio` | `rockhard_foolio` |
| `Café Tacvba — Éres (Official)` | `cafe_tacvba_eres_official` |
| `Linkin ParkLimp BizkitSlipknot Style-FFO; Aggressive NU Metal- encore - Isokuici` | `linkin_parklimp_bizkitslipknot_style-ffo_aggressive_nu_metal_encore_isokuici` |
| `米津玄師 - アイドル` (no Latin chars survive) | `video_<video_id>` |

### Layout

```
<output_dir>/rockhard_foolio/
    vocals.flac
    drums.flac
    bass.flac
    info.json
```

Stem filenames are the stem key plus the real extension: `vocals`, `drums`,
`bass`, `other`, `beat`. Extension follows the preset (`.flac` for Ultra,
`.mp3` otherwise), read from the produced file rather than assumed.

MP3-only downloads keep their current single-file behaviour and honour
`output_dir`. They create no folder, and therefore no `info.json` — the sidecar
describes a song folder, and inventing one for a lone MP3 would clutter the
output root. Their filename is unchanged.

### Collisions

Given base slug `S`, genre `g`, quality `q`:

1. `S/` does not exist → use `S/`.
2. `S/` exists with an `info.json` whose `genre` **and** `quality` match `g`/`q`
   → overwrite in place (a deliberate redo).
3. `S/` exists with different settings, or has no readable `info.json`
   → use `S_g_q/`.
4. `S_g_q/` also exists with different settings → append `_2`, `_3`, … until free.

Case 3's "no readable `info.json`" arm covers folders made by hand or by an
older Centrifugue: never assume an unknown folder is safe to overwrite.

## Atomic Publish

Live's browser watches folders in Places. Writing stems directly into the
destination lets Live observe partial files and cache a truncated import.

Stems are assembled in `<output_dir>/.<slug>.tmp/`, then the completed directory
is renamed into its final name in one `os.rename`. Same-volume directory rename
is atomic, so Live only ever sees a finished folder. On overwrite (case 2), the
existing folder is swapped out and deleted only after the new one is in place.
The temp directory is removed on failure so partial state never accumulates.

`info.json` is written inside the temp directory before the rename, so it is
never missing from a published folder.

## `info.json`

Schema version 1. Written last inside the temp dir, published atomically with
the stems.

```json
{
  "schema_version": 1,
  "song": {
    "title": "RockHard - Foolio",
    "slug": "rockhard_foolio",
    "url": "https://www.youtube.com/watch?v=...",
    "video_id": "AMxCPVRUKQo",
    "duration_seconds": 256.14
  },
  "separation": {
    "genre_mode": "rock",
    "quality_preset": "ultra",
    "stems": ["vocals", "drums", "bass"],
    "models": [
      { "stage": "vocals", "kind": "bs-roformer",
        "name": "model_bs_roformer_ep_317_sdr_12.9755" },
      { "stage": "instruments", "kind": "demucs",
        "name": "htdemucs_ft", "shifts": 0, "overlap": 0.5 }
    ]
  },
  "audio": {
    "format": "flac", "codec": "flac",
    "sample_rate": 44100, "channels": 2, "bit_depth": 16
  },
  "files": [
    { "stem": "vocals", "filename": "vocals.flac", "bytes": 15400000 }
  ],
  "timing": {
    "started_at": "2026-08-01T17:04:03Z",
    "completed_at": "2026-08-01T17:09:14Z",
    "download_seconds": 12.4,
    "separation_seconds": 289.7,
    "total_seconds": 311.2
  },
  "environment": {
    "centrifugue_version": "1.0",
    "python": "3.12.4", "platform": "macOS-15.5-arm64",
    "device": "mps",
    "demucs": "4.0.1", "audio_separator": "0.28.5",
    "torch": "2.13.0", "yt_dlp": "2026.07.21"
  }
}
```

Rules:

- Unknown or unavailable values are `null`, never omitted, so consumers can rely
  on key presence. `audio.bit_depth` is `null` for lossy formats.
- `title` preserves the original exactly; `slug` records what was derived.
- Timestamps are UTC ISO-8601 with a trailing `Z`.
- Version probing must never fail a job — a missing tool records `null`.

## README

Add to the Firefox/Zen install section: how to set the output folder, and the
Ableton recommendation (`~/Music/Ableton/User Library/Centrifugue`, already a
Place in Live, so folders appear in the browser without restarting Live).

Add a **Configuration** section documenting the config keys, and an
**`info.json` reference** section with a table describing every key: path, type,
and meaning, including that `separation` is `null` for MP3-only jobs.

## Backward Compatibility

- No config file → defaults → output lands in `~/Downloads` as before.
- Folder and file naming change for new downloads. Existing folders are left
  untouched; nothing reads the old layout.
- No extension/host protocol break: `get_config`/`set_config` are additive, and
  an older popup that never calls them still works.

## Testing

Unit-level (pure functions, no browser or model needed):

- Slug: the four table cases above, plus empty-after-ASCII, all-punctuation,
  over-length truncation not ending in `_`, and a title that is only spaces.
- Collision: each of the four cases, including the no-`info.json` folder.
- Config: missing file, malformed JSON, non-writable `output_dir`, `~` expansion.

Integration (manual, one real job):

- Stems land in the configured folder with stem-type names and an `info.json`
  whose `files[]` matches what is on disk.
- Re-run same settings overwrites; re-run different genre creates `_g_q`.
- Point `output_dir` at the Ableton User Library and confirm the folder appears
  in Live's browser, with Live running, without a restart.
