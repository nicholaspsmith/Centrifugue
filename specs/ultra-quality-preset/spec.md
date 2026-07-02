# Ultra Quality Preset — Hybrid BS-RoFormer + Demucs Pipeline

**Date:** 2026-07-02
**Status:** Approved
**Hardware context:** Apple M5 Pro (18 CPU cores, 20 GPU cores, 48 GB unified memory)

## Problem

Centrifugue's separation quality is capped by the `htdemucs` base model. The
fine-tuned `htdemucs_ft` model exists in the `high` preset but is unreachable
from either extension UI (only `fast` and `balanced` are exposed). Newer
transformer models (BS-RoFormer, vocals SDR ~12.98 vs ~9 for Demucs) now run
practically on this hardware and meaningfully outperform Demucs on vocal
separation. Stems are also re-compressed to MP3 320, adding a lossy step.

## Goals

- Best possible quality on all 4 stems (vocals, drums, bass, other)
- Acceptable runtime for the top preset: ~10 minutes per typical song
- A broken new dependency must never make the extension worse than today

## Non-Goals (out of scope)

- 6-stem models (guitar/piano)
- Replacing the Demucs engine or switching to MLX-native runtimes
- Changes to the download-MP3-only path

## Presets

| Preset key | UI label | What runs | Output | Est. time |
|-----------|----------|-----------|--------|-----------|
| `fast` | Fast | `htdemucs`, 0 shifts (unchanged) | MP3 320 | ~2 min |
| `balanced` | Detailed | `htdemucs_ft`, 0 shifts | MP3 320 | ~4 min |
| `ultra` | Ultra | Hybrid: BS-RoFormer → `htdemucs_ft` | FLAC | ~10 min |

- `htdemucs_ft` at 0 shifts is a bag of 4 fine-tuned models: better quality at
  comparable cost to the current `balanced` (`htdemucs` × 6 shift passes).
- The old `high` preset (dead config, never exposed) is replaced by `ultra`.
- Demucs settings: `fast` keeps overlap 0.25; `balanced` and Ultra Stage 2 use
  `htdemucs_ft`, 0 shifts, overlap 0.5. Quality gains come from better models,
  not high shift counts (diminishing returns).

## Ultra Pipeline

1. **Stage 1 — vocal split.** `audio-separator` runs BS-RoFormer
   (`model_bs_roformer_ep_317_sdr_12.9755.ckpt`) on the downloaded audio,
   producing `vocals` + `instrumental`. Runs as a subprocess, same pattern as
   the existing Demucs invocation.
2. **Stage 2 — instrument split.** Existing `htdemucs_ft` runs on the
   *instrumental*, producing drums / bass / other. Its residual "vocals"
   output is mixed into `other` with ffmpeg so no signal is discarded.
3. **Genre-mode shortcut.** Hiphop mode (Vocals + Beat) skips Stage 2:
   Stage 1's instrumental *is* the beat. Rock mode and full mode run both
   stages.
4. **Output format.** Ultra emits FLAC (lossless). Fast/Detailed keep MP3 320.

## Progress, Cancellation, Errors

- **Progress mapping (Ultra):** download 0–10%, Stage 1 10–55%, Stage 2
  55–90%, export/cleanup 90–100%. Hiphop shortcut maps Stage 1 to 10–90%.
  Stage 1 parses tqdm-style stderr like the existing Demucs parser; if
  unparseable, the bar holds at a coarse "Separating vocals…" step. Message
  text always names the current stage.
- **Cancellation:** each stage assigns its `Popen` to the existing
  `active_process` global as it starts; the existing cancel path works
  mid-either-stage.
- **First-run model download:** BS-RoFormer weights (~600 MB–1 GB).
  `install.sh` pre-downloads (non-fatal if offline); the worker also handles
  download at runtime with a "Downloading AI model (one-time)…" message.
- **Fallback:** if Stage 1 fails for any reason (package missing, download
  failed, OOM), the worker logs the error and falls back to a single-model
  `htdemucs_ft` run with the message "Ultra unavailable, using Detailed
  quality". The Ultra option always appears; failure degrades, never breaks.

## Dependencies & Storage

- `audio-separator` (pip) installs into the existing `venv-demucs` (torch
  2.9.1 already present; audio-separator's own Demucs support proves
  coexistence). Fallback if pip resolution conflicts: dedicated
  `venv-separator` — only if forced.
- Model weights live in the project `.cache/` directory (already gitignored)
  via `--model_file_dir`.
- `install.sh` gains one step: pip install + model pre-download.

## UI Changes

- Third quality option ("Ultra — best quality, ~10 min") in the floating
  panel and popup of **both** `extension/` and `extension-chrome/`.
- "Detailed" estimate text updates to ~4 min.
- No other UI changes.

## Testing (manual, per project convention)

1. `./install.sh` completes; audio-separator installed; model in `.cache/`.
2. Each of the three presets produces 4 stems on a short YouTube video.
3. Hiphop genre on Ultra produces vocals + beat, skips Stage 2 (visibly faster).
4. Cancel works mid-Stage-1 and mid-Stage-2.
5. Fallback: with the model renamed out of `.cache/` while offline, an Ultra
   job completes at Detailed quality with the warning message.
