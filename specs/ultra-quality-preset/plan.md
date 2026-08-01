# Ultra Quality Preset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hybrid BS-RoFormer + htdemucs_ft "Ultra" quality preset producing best-possible 4-stem separation, upgrade "Detailed" to htdemucs_ft, and output lossless FLAC for Ultra.

**Architecture:** The Python native host gains a two-stage pipeline: `audio-separator` (BS-RoFormer) splits vocals/instrumental as stage 1, then the existing Demucs path splits the instrumental as stage 2. Both stages run as subprocesses whose tqdm stderr is parsed for progress, exactly like the current Demucs invocation. Stage-1 failure falls back to a single htdemucs_ft run so Ultra can never be worse than Detailed.

**Tech Stack:** Python 3.13, demucs 4.0.1, audio-separator 0.44.2 (BS-RoFormer ckpt), torch 2.9.1 (MPS), ffmpeg, Firefox MV2 + Chrome MV3 WebExtensions.

## Global Constraints

- torch MUST stay at 2.9.1 and torchaudio at 2.9.1 (torchvision 0.24.*) — audio-separator otherwise upgrades torch to 2.12.x which breaks demucs's torchaudio native extension. Every pip command that touches this venv must carry these pins.
- Model: `model_bs_roformer_ep_317_sdr_12.9755.ckpt`; weights live in `<project>/.cache/audio-separator-models/` (gitignored).
- Preset keys are exactly `fast`, `balanced`, `ultra` (UI labels: Fast / Detailed / Ultra). `balanced` and Ultra stage 2 use `htdemucs_ft`, 0 shifts, overlap 0.5. `fast` is unchanged.
- Ultra outputs FLAC; fast/balanced keep MP3 320.
- Commit rules (`.claude/rules.md`): one responsibility per commit, subject ≤72 chars imperative, body ONLY `Co-Authored-By: Claude <noreply@anthropic.com>`.
- No automated test suite exists; each task ends with explicit manual verification commands and expected output (project convention: manual testing).

---

### Task 1: Pinned dependencies in install.sh + model pre-download

**Files:**
- Modify: `install.sh` (venv setup section, lines ~72-95)

**Interfaces:**
- Produces: `venv-demucs/bin/audio-separator` executable; model file at `.cache/audio-separator-models/model_bs_roformer_ep_317_sdr_12.9755.ckpt`; both later tasks rely on these exact paths.

- [ ] **Step 1: Add audio-separator install to install.sh**

After the existing Demucs install block (after line 95 `fi`), add:

```bash
# Install audio-separator for BS-RoFormer (Ultra preset).
# torch/torchaudio/torchvision are pinned: audio-separator would otherwise
# upgrade torch past what demucs's torchaudio build supports.
echo "  Installing audio-separator (BS-RoFormer support)..."
"$VENV_DIR/bin/pip" install --quiet "audio-separator[cpu]" \
    "torch==2.9.1" "torchaudio==2.9.1" "torchvision==0.24.*"
echo "  [OK] audio-separator installed"

# Pre-download the BS-RoFormer model so the first Ultra run doesn't stall
MODEL_CACHE_DIR="$SCRIPT_DIR/.cache/audio-separator-models"
mkdir -p "$MODEL_CACHE_DIR"
if [ -f "$MODEL_CACHE_DIR/model_bs_roformer_ep_317_sdr_12.9755.ckpt" ]; then
    echo "  [OK] BS-RoFormer model already downloaded"
else
    echo "  Pre-downloading BS-RoFormer model (~640 MB, one-time)..."
    "$VENV_DIR/bin/audio-separator" --download_model_only \
        -m model_bs_roformer_ep_317_sdr_12.9755.ckpt \
        --model_file_dir "$MODEL_CACHE_DIR" \
        || echo "  [WARN] Model pre-download failed (offline?) - it will download on first Ultra run"
fi
```

- [ ] **Step 2: Verify install.sh syntax and run it**

Run: `bash -n install.sh && ./install.sh`
Expected: completes; prints `[OK] audio-separator installed`; model download runs (or `already downloaded` on re-run).

- [ ] **Step 3: Verify both engines import and MPS works**

```bash
V=venv-demucs/bin
"$V/pip" check
"$V/python" -c "import demucs.separate, torch; print('demucs OK', torch.__version__, torch.backends.mps.is_available())"
"$V/python" -c "from audio_separator.separator import Separator; print('separator OK')"
"$V/audio-separator" --version
```
Expected: `pip check` clean (or only warnings unrelated to torch); `demucs OK 2.9.1 True`; `separator OK`; `audio-separator 0.44.2`.

- [ ] **Step 4: Commit**

```bash
git add install.sh
git commit -m "Install audio-separator with pinned torch for Ultra preset"
```
(body: `Co-Authored-By: Claude <noreply@anthropic.com>`)

---

### Task 2: Presets and constants in the native host

**Files:**
- Modify: `native-host/centrifugue_host.py:33-63` (constants + `QUALITY_PRESETS`), `:541` (estimate fallback), `:628` (quality_suffix)

**Interfaces:**
- Produces: `QUALITY_PRESETS['ultra']` with `'engine': 'hybrid'`; constants `ROFORMER_MODEL`, `MODEL_CACHE_DIR`, `SEPARATOR_BIN` used by Task 4.

- [ ] **Step 1: Add constants after line 35 (`DEMUCS_PYTHON = ...`)**

```python
# audio-separator (BS-RoFormer) for the Ultra preset's vocal stage
SEPARATOR_BIN = DEMUCS_VENV / 'bin' / 'audio-separator'
ROFORMER_MODEL = 'model_bs_roformer_ep_317_sdr_12.9755.ckpt'
MODEL_CACHE_DIR = PROJECT_ROOT / '.cache' / 'audio-separator-models'
```

- [ ] **Step 2: Replace QUALITY_PRESETS with**

```python
QUALITY_PRESETS = {
    'fast': {
        'model': 'htdemucs',
        'shifts': 0,
        'overlap': 0.25,
        'cpu_limit': 400,
        'time_multiplier': 0.4,
        'description': 'Fast processing, basic quality'
    },
    'balanced': {
        'model': 'htdemucs_ft',
        'shifts': 0,
        'overlap': 0.5,
        'cpu_limit': 400,
        'time_multiplier': 1.0,
        'description': 'Fine-tuned model, good quality'
    },
    'ultra': {
        'model': 'htdemucs_ft',   # stage 2; stage 1 is BS-RoFormer
        'engine': 'hybrid',
        'shifts': 0,
        'overlap': 0.5,
        'cpu_limit': 500,
        'time_multiplier': 2.5,
        'description': 'Hybrid BS-RoFormer + Demucs, best quality'
    }
}
```

- [ ] **Step 3: Update the two quality-keyed dicts**

Line ~541: `estimated_seconds = {'fast': 90, 'balanced': 300, 'high': 600}` → `{'fast': 90, 'balanced': 240, 'ultra': 600}`.
Line ~628: `quality_suffix = {'fast': '', 'balanced': ' (HQ)', 'high': ' (Ultra)'}` → `{'fast': '', 'balanced': ' (HQ)', 'ultra': ' (Ultra)'}`.

- [ ] **Step 4: Verify**

```bash
python3 -m py_compile native-host/centrifugue_host.py
python3 -c "
import importlib.util as u; s=u.spec_from_file_location('h','native-host/centrifugue_host.py'); m=u.module_from_spec(s); s.loader.exec_module(m)
assert set(m.QUALITY_PRESETS) == {'fast','balanced','ultra'}
assert m.QUALITY_PRESETS['ultra']['engine'] == 'hybrid'
assert m.QUALITY_PRESETS['balanced']['model'] == 'htdemucs_ft'
print('presets OK')"
```
Expected: `presets OK`.

- [ ] **Step 5: Commit** — `Add ultra preset and upgrade balanced to htdemucs_ft`

---

### Task 3: Extract run_demucs_stage() from the inline Demucs block

**Files:**
- Modify: `native-host/centrifugue_host.py` — new function before `run_stem_separation_background` (~line 462); replace inline block at lines ~547-660 in that function.

**Interfaces:**
- Produces: `run_demucs_stage(input_file, output_root, model, shifts, overlap, use_flac, progress_cb) -> dict[str, Path] | None`. `progress_cb(stage_percent: int, detail: str)` receives 0-100 within-stage progress. Returns `{stem_name: Path}` for stems found (keys among vocals/drums/bass/other), or None on failure. Consumed by Task 4.

- [ ] **Step 1: Add the function**

```python
def run_demucs_stage(input_file, output_root, model, shifts, overlap, use_flac, progress_cb):
    """Run Demucs on input_file; return {stem_name: Path} or None on failure.

    progress_cb(stage_percent, detail) gets within-stage progress 0-100.
    """
    global active_process

    cmd = [
        str(DEMUCS_PYTHON), '-m', 'demucs',
        str(input_file),
        '-n', model,
        '-o', str(output_root),
        '--overlap', str(overlap),
        '-d', 'mps'  # Apple Metal GPU acceleration
    ]
    cmd.extend(['--flac'] if use_flac else ['--mp3', '--mp3-bitrate', '320'])
    if shifts > 0:
        cmd.extend(['--shifts', str(shifts)])

    active_process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1
    )

    total_shifts = shifts + 1
    current_shift = 0
    last_percent = 0
    last_stage = 0

    for line in active_process.stderr:
        percent, detected_shift = parse_demucs_progress(line)
        if detected_shift is not None:
            current_shift = detected_shift
            last_percent = 0
        if percent is not None and percent >= last_percent:
            last_percent = percent
            stage_pct = int((current_shift / total_shifts) * 100
                            + percent / total_shifts)
            if stage_pct > last_stage:
                last_stage = stage_pct
                if total_shifts > 1:
                    detail = f'Pass {current_shift + 1}/{total_shifts} ({percent}%)'
                else:
                    detail = f'{percent}%'
                progress_cb(stage_pct, detail)

    active_process.wait()
    returncode = active_process.returncode
    active_process = None
    if returncode != 0:
        return None

    ext = 'flac' if use_flac else 'mp3'
    stems_dir = Path(output_root) / model / Path(input_file).stem
    if not stems_dir.exists():
        for potential_dir in Path(output_root).rglob("*"):
            if potential_dir.is_dir() and any(potential_dir.glob(f"*.{ext}")):
                stems_dir = potential_dir
                break
    if not stems_dir.exists():
        return None

    stems = {}
    for stem_file in stems_dir.glob("*.*"):
        name = stem_file.stem.lower()
        if name in ('vocals', 'drums', 'bass', 'other'):
            stems[name] = stem_file
    return stems or None
```

- [ ] **Step 2: Rewire run_stem_separation_background to use it**

Replace everything from `# Step 2: Run Demucs with real-time progress parsing` (~547) through the `stem_files` build loop (~660) with:

```python
        # Step 2: Separate
        demucs_output = temp_path / "separated"

        def demucs_progress(stage_pct, detail):
            overall = 10 + int(stage_pct * 0.8)  # map 0-100 -> 10-90
            write_progress('processing', f'Separating stems... {detail}',
                          percent=overall, estimated_seconds=estimated_seconds,
                          job_id=job_id, video_title=title,
                          action='download_stems', quality=quality, genre=genre)

        stem_files = run_demucs_stage(
            audio_file, demucs_output, preset['model'], preset['shifts'],
            preset['overlap'], use_flac=False, progress_cb=demucs_progress)

        if stem_files is None:
            write_progress('error', 'Stem separation failed',
                          error='Demucs did not produce stems', job_id=job_id,
                          video_title=title, action='download_stems',
                          quality=quality, genre=genre)
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_job_state()
            return
```

Keep the existing `# Step 3: Organize output files` block, but delete its now-duplicated stems-directory search and `stem_files` build loop (lines ~633-660) — `stem_files` already exists. Keep `stem_mapping`, the copy loop, and the combine block. Note the copy loop already uses `stem_file.suffix`, so it is format-agnostic.

- [ ] **Step 3: Verify with a generated test tone (no YouTube needed)**

```bash
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=8" -ac 2 /tmp/claude/tone.wav
python3 - <<'EOF'
import importlib.util as u
s = u.spec_from_file_location('h', 'native-host/centrifugue_host.py')
m = u.module_from_spec(s); s.loader.exec_module(m)
stems = m.run_demucs_stage('/tmp/claude/tone.wav', '/tmp/claude/sep_out',
                           'htdemucs', 0, 0.25, False,
                           lambda p, d: print(f'  {p}% {d}'))
print('stems:', sorted(stems) if stems else None)
assert stems and set(stems) == {'vocals', 'drums', 'bass', 'other'}
print('run_demucs_stage OK')
EOF
```
Expected: progress lines print, then `run_demucs_stage OK`.

- [ ] **Step 4: Commit** — `Extract run_demucs_stage from worker pipeline`

---

### Task 4: BS-RoFormer stage + Ultra pipeline + fallback

**Files:**
- Modify: `native-host/centrifugue_host.py` — new `run_roformer_stage()` next to `run_demucs_stage()`; Ultra branch in `run_stem_separation_background`; `combine_stems()` codec parametrization; export block additions.

**Interfaces:**
- Consumes: `run_demucs_stage` (Task 3 signature), `SEPARATOR_BIN` / `ROFORMER_MODEL` / `MODEL_CACHE_DIR` (Task 2).
- Produces: `run_roformer_stage(audio_file, output_dir, progress_cb) -> tuple[Path, Path] | None` (vocals, instrumental). `stem_files` may now contain a `'beat'` key the export block copies directly.

- [ ] **Step 1: Parametrize combine_stems output codec by extension**

In `combine_stems()` (~line 344), replace the fixed mp3 codec args:

```python
def combine_stems(stem_files, output_path):
    """Mix multiple stems into one file with ffmpeg (codec from extension)."""
    ffmpeg_path = find_ffmpeg()

    cmd = [ffmpeg_path, '-y']
    for stem_file in stem_files:
        cmd.extend(['-i', str(stem_file)])

    # normalize=0: stems are components of one mix; plain summation
    # reconstructs it. Default amix normalization would halve volumes.
    filter_arg = f'amix=inputs={len(stem_files)}:duration=longest:normalize=0'
    if str(output_path).lower().endswith('.flac'):
        codec_args = ['-c:a', 'flac']
    else:
        codec_args = ['-codec:a', 'libmp3lame', '-b:a', '320k']
    cmd.extend(['-filter_complex', filter_arg] + codec_args + [str(output_path)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except Exception:
        return False
```

- [ ] **Step 2: Add run_roformer_stage() after run_demucs_stage()**

```python
def run_roformer_stage(audio_file, output_dir, progress_cb):
    """Run BS-RoFormer vocal separation via audio-separator.

    Returns (vocals_path, instrumental_path) or None on any failure —
    caller falls back to a plain Demucs run.
    """
    global active_process

    if not (SEPARATOR_BIN.is_file() and os.access(SEPARATOR_BIN, os.X_OK)):
        return None

    cmd = [
        str(SEPARATOR_BIN), str(audio_file),
        '-m', ROFORMER_MODEL,
        '--model_file_dir', str(MODEL_CACHE_DIR),
        '--output_dir', str(output_dir),
        '--output_format', 'FLAC',
    ]

    try:
        active_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        last = 0
        for line in active_process.stdout:
            percent, _ = parse_demucs_progress(line)
            if percent is not None and percent > last:
                last = percent
                progress_cb(percent)
        active_process.wait()
        returncode = active_process.returncode
        active_process = None
        if returncode != 0:
            return None

        vocals = next(Path(output_dir).glob('*(Vocals)*'), None)
        instrumental = next(Path(output_dir).glob('*(Instrumental)*'), None)
        if vocals and instrumental:
            return vocals, instrumental
        return None
    except Exception:
        active_process = None
        return None
```

- [ ] **Step 3: Add the Ultra branch in run_stem_separation_background**

Replace the `# Step 2: Separate` block from Task 3 with:

```python
        # Step 2: Separate
        demucs_output = temp_path / "separated"
        use_flac = preset.get('engine') == 'hybrid'

        def demucs_progress_range(lo, hi):
            def cb(stage_pct, detail):
                overall = lo + int(stage_pct / 100 * (hi - lo))
                write_progress('processing', f'Separating stems... {detail}',
                              percent=overall, estimated_seconds=estimated_seconds,
                              job_id=job_id, video_title=title,
                              action='download_stems', quality=quality, genre=genre)
            return cb

        stem_files = None

        if preset.get('engine') == 'hybrid':
            roformer_out = temp_path / 'roformer'
            stage1_hi = 90 if genre == 'hiphop' else 55

            if not (MODEL_CACHE_DIR / ROFORMER_MODEL).exists():
                write_progress('processing', 'Downloading AI model (one-time)...',
                              percent=10, estimated_seconds=estimated_seconds,
                              job_id=job_id, video_title=title,
                              action='download_stems', quality=quality, genre=genre)

            def stage1_progress(pct):
                overall = 10 + int(pct / 100 * (stage1_hi - 10))
                write_progress('processing', f'Separating vocals... {pct}%',
                              percent=overall, estimated_seconds=estimated_seconds,
                              job_id=job_id, video_title=title,
                              action='download_stems', quality=quality, genre=genre)

            stage1 = run_roformer_stage(audio_file, roformer_out, stage1_progress)

            if stage1 is not None:
                vocals_path, instrumental_path = stage1
                if genre == 'hiphop':
                    # Instrumental IS the beat — skip stage 2 entirely
                    stem_files = {'vocals': vocals_path, 'beat': instrumental_path}
                else:
                    stage2_stems = run_demucs_stage(
                        instrumental_path, demucs_output, preset['model'],
                        preset['shifts'], preset['overlap'], use_flac=True,
                        progress_cb=demucs_progress_range(55, 90))
                    if stage2_stems is not None:
                        # RoFormer vocals replace Demucs vocals; mix Demucs's
                        # residual "vocals" (whatever RoFormer left in the
                        # instrumental) into other so no signal is discarded
                        residual = stage2_stems.pop('vocals', None)
                        if residual is not None and 'other' in stage2_stems:
                            mixed_other = temp_path / 'other_mixed.flac'
                            if combine_stems([stage2_stems['other'], residual], mixed_other):
                                stage2_stems['other'] = mixed_other
                        stage2_stems['vocals'] = vocals_path
                        stem_files = stage2_stems

            if stem_files is None:
                # Fallback: single-model htdemucs_ft run, never fail outright
                write_progress('processing',
                              'Ultra unavailable, using Detailed quality...',
                              percent=10, estimated_seconds=estimated_seconds,
                              job_id=job_id, video_title=title,
                              action='download_stems', quality=quality, genre=genre)

        if stem_files is None:
            stem_files = run_demucs_stage(
                audio_file, demucs_output, preset['model'], preset['shifts'],
                preset['overlap'], use_flac=False,
                progress_cb=demucs_progress_range(10, 90))

        if stem_files is None:
            write_progress('error', 'Stem separation failed',
                          error='Demucs did not produce stems', job_id=job_id,
                          video_title=title, action='download_stems',
                          quality=quality, genre=genre)
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_job_state()
            return
```

- [ ] **Step 4: Handle 'beat' in the export block**

In `# Step 3: Organize output files`: add `'beat': 'Beat'` to `stem_mapping`. Before the `if 'combine' in genre_mode:` block, add:

```python
        if 'beat' in stem_files:
            beat_file = stem_files['beat']
            dest_name = f"{title} - Beat{beat_file.suffix}"
            shutil.copy2(beat_file, output_folder / dest_name)
            copied_files.append(dest_name)
        elif 'combine' in genre_mode:
```
(i.e. the existing combine block becomes the `elif`; its body is unchanged except the output extension should follow the stems: use `'.flac'` if the source stems are FLAC — compute `combine_ext = source_files[0].suffix` and use it for `combined_dest`.)

- [ ] **Step 5: Verify Ultra pipeline on the test tone**

```bash
python3 - <<'EOF'
import importlib.util as u
s = u.spec_from_file_location('h', 'native-host/centrifugue_host.py')
m = u.module_from_spec(s); s.loader.exec_module(m)
r = m.run_roformer_stage('/tmp/claude/tone.wav', '/tmp/claude/rofo_out',
                         lambda p: print(f'  stage1 {p}%'))
assert r is not None, "roformer stage failed"
vocals, inst = r
print('vocals:', vocals.name)
print('instrumental:', inst.name)
print('run_roformer_stage OK')
EOF
```
Expected: progress prints, both output names shown, `run_roformer_stage OK`.

- [ ] **Step 6: Verify fallback** — temporarily `mv .cache/audio-separator-models{,.bak}` and rerun the snippet: it must return `None` quickly only if the binary is missing; with binary present but model dir gone, audio-separator re-downloads — so instead test fallback by renaming the binary: `mv venv-demucs/bin/audio-separator{,.bak}`, rerun, expect `roformer stage failed` assertion (i.e. returns None). Restore both.

- [ ] **Step 7: Commit** — `Add hybrid BS-RoFormer Ultra pipeline with Demucs fallback`

---

### Task 5: Cancel kills the whole worker process group

**Files:**
- Modify: `native-host/centrifugue_host.py:783-788` (`cancel_job`)

**Interfaces:** none new; behavior fix. The worker is spawned with `start_new_session=True`, so its PID == its process-group ID; killing the group also kills a running Demucs/RoFormer child (today the child is orphaned and keeps burning GPU).

- [ ] **Step 1: Replace the single os.kill in cancel_job**

```python
        try:
            pid = job_state.get('pid')
            if pid:
                # Worker was started with start_new_session=True, so pid is
                # the process-group leader; kill the group so a running
                # separation subprocess dies too instead of being orphaned
                try:
                    os.killpg(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    os.kill(pid, signal.SIGTERM)
        except:
            pass
```

- [ ] **Step 2: Verify**

```bash
python3 -m py_compile native-host/centrifugue_host.py && echo OK
```
Expected: `OK`. Full cancel behavior is exercised in Task 7's manual matrix.

- [ ] **Step 3: Commit** — `Kill worker process group on cancel`

---

### Task 6: Ultra option in both extension UIs

**Files:**
- Modify: `extension-chrome/content.js:620-623` (qualities array)
- Modify: `extension-chrome/popup/popup.html:204-213` (quality-options div)
- Modify: `extension-firefox/content.js:421-431` (static quality row HTML)
- Modify: `extension-firefox/popup/popup.html:203-213` (quality-options div)

**Interfaces:** the UI sends `quality: "ultra"` — must match the `QUALITY_PRESETS` key from Task 2 exactly.

- [ ] **Step 1: extension-chrome/content.js** — qualities array becomes:

```javascript
  const qualities = [
    { value: "fast", label: "Fast", desc: "~2 min", selected: true },
    { value: "balanced", label: "Detailed", desc: "~4 min", selected: false },
    { value: "ultra", label: "Ultra", desc: "~10 min", selected: false }
  ];
```

- [ ] **Step 2: extension-chrome/popup/popup.html** — quality options become:

```html
      <div class="quality-options">
        <div class="quality-option selected" data-quality="fast">
          <div class="label">Fast</div>
          <div class="desc">~2 min</div>
        </div>
        <div class="quality-option" data-quality="balanced">
          <div class="label">Detailed</div>
          <div class="desc">~4 min</div>
        </div>
        <div class="quality-option" data-quality="ultra">
          <div class="label">Ultra</div>
          <div class="desc">~10 min</div>
        </div>
      </div>
```

- [ ] **Step 3: extension-firefox/content.js** — static HTML block becomes:

```html
        <div class="centrifugue-section-title">Quality</div>
        <div class="centrifugue-options-row">
          <div class="centrifugue-option centrifugue-quality-option selected" data-quality="fast">
            <div class="centrifugue-option-label">Fast</div>
            <div class="centrifugue-option-desc">~2 min</div>
          </div>
          <div class="centrifugue-option centrifugue-quality-option" data-quality="balanced">
            <div class="centrifugue-option-label">Detailed</div>
            <div class="centrifugue-option-desc">~4 min</div>
          </div>
          <div class="centrifugue-option centrifugue-quality-option" data-quality="ultra">
            <div class="centrifugue-option-label">Ultra</div>
            <div class="centrifugue-option-desc">~10 min</div>
          </div>
        </div>
```

- [ ] **Step 4: extension-firefox/popup/popup.html** — same three-option markup as Step 2 (this file uses the identical `quality-option` classes).

- [ ] **Step 5: Verify** — load both extensions (Firefox `about:debugging`, Brave `brave://extensions` reload). Open a YouTube video: the floating panel and popup each show Fast / Detailed / Ultra, three across, none clipped. Selecting Ultra highlights it.

- [ ] **Step 6: Commit** — `Add Ultra quality option to extension UIs`

---

### Task 7: End-to-end manual test matrix

**Files:** none modified (verification only; fix-forward anything found, committing per rule).

- [ ] **Step 1: Fast preset sanity** — short video (~2-3 min), genre Full → 4 MP3 stems in `~/Downloads/<title> - Stems/`.
- [ ] **Step 2: Detailed preset** — same video → 4 MP3 stems in `<title> - Stems (HQ)/`; folder name confirms htdemucs_ft ran (progress shows single pass).
- [ ] **Step 3: Ultra + Full** — same video → 4 FLAC stems in `<title> - Stems (Ultra)/`; progress shows "Separating vocals..." then "Separating stems..."; vocals file audibly cleaner; `ffprobe` shows FLAC.
- [ ] **Step 4: Ultra + Hip Hop** — → 2 FLAC files (Vocals, Beat); visibly faster than Step 3 (no stage 2).
- [ ] **Step 5: Cancel mid-Stage-1 and mid-Stage-2** — start Ultra, cancel during "Separating vocals..."; verify no `demucs`/`audio-separator` process survives (`pgrep -fl "demucs|audio-separator"` → empty). Repeat cancelling during "Separating stems...".
- [ ] **Step 6: Fallback** — `mv venv-demucs/bin/audio-separator{,.bak}`, run Ultra: job completes with MP3 stems (fallback runs `htdemucs_ft` with `use_flac=False`) after showing "Ultra unavailable, using Detailed quality...". Restore the binary.
- [ ] **Step 7: Update README** if it documents quality presets (`grep -n -i "quality\|preset" README.md`) — align names/times. Commit `Update README for Ultra preset` if changed.

---

## Self-Review Notes

- Spec coverage: presets table → Task 2/6; pipeline → Task 4; hiphop shortcut → Task 4 Step 3; FLAC → Tasks 3/4 (use_flac); progress mapping → Task 4 (10-55-90, hiphop 10-90); cancellation → Task 5; model pre-download → Task 1; runtime download message → Task 4 Step 3; fallback → Task 4; `.cache/` storage → Tasks 1/2; both UIs → Task 6; test checklist → Task 7. No gaps.
- Fallback intentionally produces MP3 (it is literally the Detailed path); spec says "completes at Detailed quality" — consistent.
- `estimated_seconds` is defined before the Step 2 block in the existing code (line ~537-541) and is closed over by the progress callbacks — no ordering issue.
- Type consistency: `run_demucs_stage` returns dict|None consumed as such in Task 4; `progress_cb(stage_pct, detail)` two-arg for demucs, one-arg `stage1_progress(pct)` for roformer — distinct functions, no shared signature required.
