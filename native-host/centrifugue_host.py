#!/usr/bin/env python3
"""
Centrifugue - Native messaging host for browser extension.
Extract audio stems from YouTube videos using yt-dlp and Demucs AI.

Architecture:
- Stem separation runs as independent background processes
- Progress is written to ~/.centrifugue_progress.json for polling
- Extension polls get_progress to check status
- Supports cancel_job to stop running processes
"""

import json
import struct
import subprocess
import sys
import os
import shutil
import tempfile
import re
import time
import threading
import signal
from datetime import datetime, timezone
from pathlib import Path

from centrifugue_config import (load_config, save_config, get_output_dir,
                                parse_folder_choice)
from centrifugue_naming import slugify, resolve_output_folder, publish_folder
from centrifugue_info import build_info, probe_environment
from centrifugue_cookies import resolve_cookie_spec

# Ensure Homebrew binaries are in PATH
os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH', '')

# Get the directory containing this script
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent

# Demucs virtual environment (relative to project root)
DEMUCS_VENV = PROJECT_ROOT / 'venv-demucs'
DEMUCS_PYTHON = DEMUCS_VENV / 'bin' / 'python'

# audio-separator (BS-RoFormer) for the Ultra preset's vocal stage
SEPARATOR_BIN = DEMUCS_VENV / 'bin' / 'audio-separator'
ROFORMER_MODEL = 'model_bs_roformer_ep_317_sdr_12.9755.ckpt'
MODEL_CACHE_DIR = PROJECT_ROOT / '.cache' / 'audio-separator-models'

# Quality presets for stem separation
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

# Genre modes determine which stems to output
GENRE_MODES = {
    'full': {
        'stems': ['vocals', 'drums', 'bass', 'other'],
        'description': 'All 4 stems'
    },
    'hiphop': {
        'stems': ['vocals'],
        'combine': {'beat': ['drums', 'bass', 'other']},
        'description': 'Vocals + Beat'
    },
    'rock': {
        'stems': ['vocals', 'drums', 'bass'],
        'description': 'Vocals, Drums, Bass'
    }
}

# Global state for tracking background jobs
active_job = None
active_process = None

# Path to this script (for spawning background worker)
SCRIPT_PATH = os.path.abspath(__file__)


def get_download_dir():
    """Configured output directory, defaulting to ~/Downloads."""
    return get_output_dir()


def get_progress_file():
    """Get path to the progress tracking file"""
    return Path.home() / ".centrifugue_progress.json"


def get_job_file():
    """Get path to the job state file (survives native host restarts)"""
    return Path.home() / ".centrifugue_job.json"


def write_progress(stage, message, percent=0, estimated_seconds=None, video_title=None,
                   job_id=None, action=None, quality=None, genre=None, error=None):
    """Write progress info to file for extension to poll"""
    progress_file = get_progress_file()
    progress = {
        'stage': stage,
        'message': message,
        'percent': percent,
        'estimated_seconds': estimated_seconds,
        'video_title': video_title,
        'job_id': job_id,
        'action': action,
        'quality': quality,
        'genre': genre,
        'error': error,
        'timestamp': time.time()
    }
    try:
        with open(progress_file, 'w') as f:
            json.dump(progress, f)
    except:
        pass


def read_progress():
    """Read current progress from file"""
    progress_file = get_progress_file()
    try:
        if progress_file.exists():
            with open(progress_file, 'r') as f:
                data = json.load(f)
                # Check if progress is stale (older than 10 minutes with no update)
                if data.get('stage') == 'processing':
                    age = time.time() - data.get('timestamp', 0)
                    if age > 600:  # 10 minutes
                        data['stage'] = 'stale'
                        data['message'] = 'Job appears to have stalled'
                return data
    except:
        pass
    return {'stage': 'idle', 'message': 'Ready', 'percent': 0}


def clear_progress():
    """Clear the progress file"""
    progress_file = get_progress_file()
    try:
        if progress_file.exists():
            progress_file.unlink()
    except:
        pass


def save_job_state(job_id, pid, temp_dir, title, action, quality, genre, url):
    """Save job state to file so it survives native host restarts"""
    job_file = get_job_file()
    state = {
        'job_id': job_id,
        'pid': pid,
        'temp_dir': temp_dir,
        'title': title,
        'action': action,
        'quality': quality,
        'genre': genre,
        'url': url,
        'started': time.time()
    }
    try:
        with open(job_file, 'w') as f:
            json.dump(state, f)
    except:
        pass


def load_job_state():
    """Load job state from file"""
    job_file = get_job_file()
    try:
        if job_file.exists():
            with open(job_file, 'r') as f:
                return json.load(f)
    except:
        pass
    return None


def clear_job_state():
    """Clear the job state file"""
    job_file = get_job_file()
    try:
        if job_file.exists():
            job_file.unlink()
    except:
        pass


def sanitize_filename(name):
    """Remove or replace characters that aren't safe for filenames"""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 100:
        name = name[:100]
    return name or "download"


def read_message():
    """Read a message from the extension via stdin"""
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None

    message_length = struct.unpack('@I', raw_length)[0]
    message = sys.stdin.buffer.read(message_length).decode('utf-8')
    return json.loads(message)


def send_message(message):
    """Send a message to the extension via stdout"""
    encoded = json.dumps(message).encode('utf-8')
    length = struct.pack('@I', len(encoded))
    sys.stdout.buffer.write(length)
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def find_ytdlp():
    """Find yt-dlp executable, checking common install locations"""
    locations = [
        '/opt/homebrew/bin/yt-dlp',
        '/usr/local/bin/yt-dlp',
        str(Path.home() / '.local' / 'bin' / 'yt-dlp'),
        '/usr/bin/yt-dlp',
    ]
    for loc in locations:
        if os.path.isfile(loc) and os.access(loc, os.X_OK):
            return loc
    # Fall back to PATH search
    found = shutil.which('yt-dlp')
    return found if found else None


def find_ffmpeg():
    """Find ffmpeg in common locations"""
    locations = [
        '/opt/homebrew/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        '/usr/bin/ffmpeg',
    ]
    for loc in locations:
        if os.path.isfile(loc) and os.access(loc, os.X_OK):
            return loc
    return 'ffmpeg'


def find_ffprobe():
    """Find ffprobe in common locations"""
    locations = [
        '/opt/homebrew/bin/ffprobe',
        '/usr/local/bin/ffprobe',
        '/usr/bin/ffprobe',
    ]
    for loc in locations:
        if os.path.isfile(loc) and os.access(loc, os.X_OK):
            return loc
    return None


def get_ytdlp_auth_args():
    """Get yt-dlp args to bypass YouTube bot detection.

    Cookies come from whichever Firefox-family profile actually holds a
    signed-in YouTube session, detected at runtime. Hardcoding "firefox"
    fails for anyone who browses in Zen or another fork: yt-dlp reads an
    empty profile and YouTube answers "Sign in to confirm you're not a
    bot". Override with the cookies_from_browser config key.
    """
    spec = resolve_cookie_spec(load_config().get('cookies_from_browser'))
    return ['--cookies-from-browser', spec]


def get_audio_duration(file_path):
    """Get audio duration in seconds using ffprobe"""
    ffprobe_path = find_ffprobe()
    if not ffprobe_path:
        return None

    try:
        result = subprocess.run(
            [ffprobe_path, '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except:
        pass
    return None


def probe_audio_stream(file_path):
    """Return (sample_rate, channels) for an audio file, or (None, None)."""
    ffprobe_path = find_ffprobe()
    if not ffprobe_path:
        return None, None
    try:
        result = subprocess.run(
            [ffprobe_path, '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=sample_rate,channels',
             '-of', 'default=nw=1:nk=1', str(file_path)],
            capture_output=True, text=True, timeout=30)
        parts = result.stdout.split()
        return int(parts[0]), int(parts[1])
    except Exception:
        return None, None


def get_video_title(url):
    """Get the video title from YouTube URL"""
    ytdlp_path = find_ytdlp()
    try:
        result = subprocess.run(
            [ytdlp_path, '--get-title', '--no-playlist'] + get_ytdlp_auth_args() + [url],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return sanitize_filename(result.stdout.strip())
    except:
        pass
    return None


def get_unique_filepath(directory, basename, extension):
    """
    Generate a unique filepath by appending (1), (2), etc. if file exists.

    Args:
        directory: Path to the directory
        basename: Base filename without extension (e.g., "Numa Numa - original")
        extension: File extension with dot (e.g., ".mp3")

    Returns:
        Path object with unique filename
    """
    filepath = directory / f"{basename}{extension}"
    if not filepath.exists():
        return filepath

    # File exists, find next available number
    counter = 1
    while True:
        filepath = directory / f"{basename} ({counter}){extension}"
        if not filepath.exists():
            return filepath
        counter += 1


def combine_stems(stem_files, output_path):
    """Mix multiple stems into one file with ffmpeg (codec from extension)"""
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


def parse_demucs_progress(line):
    """Parse demucs tqdm output for progress percentage and shift info.

    Returns: tuple (percent, current_shift, total_shifts) or (None, None, None)

    When --shifts N is used, Demucs runs N+1 passes. Each pass shows 0-100%.
    We need to calculate overall progress as:
      overall = (current_shift / total_shifts) * 100 + (percent / total_shifts)
    """
    # Check for shift info: "Separated track audio shift 2"
    shift_match = re.search(r'shift\s+(\d+)', line, re.IGNORECASE)
    current_shift = int(shift_match.group(1)) if shift_match else None

    # tqdm format: " 50%|█████     | 617/1234 [01:23<01:20, 7.68it/s]"
    percent_match = re.search(r'(\d+)%\|', line)
    percent = int(percent_match.group(1)) if percent_match else None

    return percent, current_shift


def download_mp3(url):
    """Download YouTube video as MP3 using yt-dlp"""
    download_dir = get_download_dir()
    ytdlp_path = find_ytdlp()

    if not ytdlp_path:
        return {'success': False, 'error': 'yt-dlp not found. Install it with: brew install yt-dlp'}

    # Get video title first to determine unique output filename
    title = get_video_title(url)
    if not title:
        title = "audio"

    # Generate unique filepath (appends (1), (2), etc. if file exists)
    output_path = get_unique_filepath(download_dir, title, '.mp3')

    cmd = [
        ytdlp_path,
        '--extract-audio',
        '--audio-format', 'mp3',
        '--audio-quality', '0',
        '--output', str(output_path.with_suffix('.%(ext)s')),
        '--no-playlist',
    ] + get_ytdlp_auth_args() + [url]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            # Verify the file was actually created
            if output_path.exists():
                return {
                    'success': True,
                    'filename': output_path.name,
                    'message': 'Download completed successfully'
                }
            else:
                # yt-dlp returned success but file doesn't exist
                # This can happen with YouTube bot detection issues
                error_msg = 'Download failed: file was not created. '
                if 'Signature solving failed' in result.stderr:
                    error_msg += 'YouTube bot detection issue. Try updating yt-dlp: brew upgrade yt-dlp'
                elif result.stderr:
                    error_msg += result.stderr
                else:
                    error_msg += 'Unknown error (no output file)'
                return {
                    'success': False,
                    'error': error_msg
                }
        else:
            error = result.stderr or 'yt-dlp failed with no error message'
            if 'Sign in to confirm' in error or 'bot' in error.lower():
                error = 'YouTube bot detection error. Try updating yt-dlp: brew upgrade yt-dlp'
            return {'success': False, 'error': error}

    except FileNotFoundError:
        return {
            'success': False,
            'error': 'yt-dlp not found. Please install it: brew install yt-dlp'
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Download timed out after 5 minutes'
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


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

    # With --shifts N, Demucs runs N+1 passes; tqdm goes to stderr
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


def run_stem_separation_background(job_id, url, quality, genre, title):
    """Run stem separation as independent worker process with real-time progress parsing"""
    global active_process

    download_dir = get_download_dir()
    ytdlp_path = find_ytdlp()
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS['fast'])
    genre_mode = GENRE_MODES.get(genre, GENRE_MODES['full'])
    config = load_config()

    # Provenance and timing captured across the whole job; consumed by the
    # info.json sidecar at the end. Populated as each stage completes.
    started_epoch = time.time()
    started_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    download_seconds = None
    separation_seconds = None
    duration_seconds = None
    audio_sample_rate = None
    audio_channels = None
    models_used = []

    _m = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})', url or '')
    video_id = _m.group(1) if _m else None

    # Fail before downloading rather than after separation finishes
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        write_progress('error', f'Output folder is not writable: {exc}',
                       error=str(exc), job_id=job_id, video_title=title,
                       action='download_stems', quality=quality, genre=genre)
        clear_job_state()
        return

    if not ytdlp_path:
        write_progress('error', 'yt-dlp not found. Install it with: brew install yt-dlp',
                      error='yt-dlp not found. Install it with: brew install yt-dlp',
                      job_id=job_id, video_title=title, action='download_stems',
                      quality=quality, genre=genre)
        clear_job_state()
        return

    # Check if Demucs is available (requires venv-demucs to be set up)
    demucs_available = DEMUCS_PYTHON.is_file() and os.access(DEMUCS_PYTHON, os.X_OK)

    if not demucs_available:
        write_progress('error', 'Demucs not found. Run install.sh to set up the virtual environment.',
                      error='Demucs not installed - run install.sh',
                      job_id=job_id, video_title=title, action='download_stems',
                      quality=quality, genre=genre)
        clear_job_state()
        return

    # Create persistent temp directory (not auto-deleted)
    temp_dir = tempfile.mkdtemp(prefix='centrifugue_')
    temp_path = Path(temp_dir)
    audio_file = temp_path / "audio.wav"

    # Update job state with temp_dir (we're running in the worker process now)
    save_job_state(job_id, os.getpid(), temp_dir, title, 'download_stems', quality, genre, url)

    try:
        # Step 1: Download audio
        write_progress('downloading', 'Downloading audio from YouTube...', percent=5,
                      job_id=job_id, video_title=title, action='download_stems',
                      quality=quality, genre=genre)

        download_cmd = [
            ytdlp_path,
            '--extract-audio',
            '--audio-format', 'wav',
            '--audio-quality', '0',
            '--output', str(audio_file),
            '--no-playlist',
        ] + get_ytdlp_auth_args() + [url]

        result = subprocess.run(download_cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            write_progress('error', f'Download failed: {result.stderr}',
                          error=result.stderr, job_id=job_id, video_title=title,
                          action='download_stems', quality=quality, genre=genre)
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_job_state()
            return

        # Find the actual downloaded file
        wav_files = list(temp_path.glob("audio.*"))
        if not wav_files:
            write_progress('error', 'Downloaded audio file not found',
                          error='Audio file not found', job_id=job_id, video_title=title,
                          action='download_stems', quality=quality, genre=genre)
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_job_state()
            return
        audio_file = wav_files[0]

        download_seconds = round(time.time() - started_epoch, 2)
        audio_sample_rate, audio_channels = probe_audio_stream(audio_file)

        # Get audio duration for better estimates
        audio_duration = get_audio_duration(audio_file)
        duration_seconds = audio_duration
        if audio_duration:
            estimated_seconds = int(audio_duration * preset['time_multiplier']) + 30
        else:
            estimated_seconds = {'fast': 90, 'balanced': 240, 'ultra': 600}.get(quality, 120)

        write_progress('processing', 'Separating stems with AI...', percent=10,
                      estimated_seconds=estimated_seconds, job_id=job_id, video_title=title,
                      action='download_stems', quality=quality, genre=genre)

        # Step 2: Separate
        separation_start = time.time()
        demucs_output = temp_path / "separated"

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
                models_used.append({'stage': 'vocals', 'kind': 'bs-roformer',
                                    'name': ROFORMER_MODEL})
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
                        models_used.append({
                            'stage': 'instruments', 'kind': 'demucs',
                            'name': preset['model'], 'shifts': preset['shifts'],
                            'overlap': preset['overlap']})
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
            # Fallback discards any hybrid stage-1 result, so the recorded
            # chain must not claim a RoFormer stage that did not contribute
            models_used = []
            stem_files = run_demucs_stage(
                audio_file, demucs_output, preset['model'], preset['shifts'],
                preset['overlap'], use_flac=False,
                progress_cb=demucs_progress_range(10, 90))
            if stem_files is not None:
                models_used.append({
                    'stage': 'instruments', 'kind': 'demucs',
                    'name': preset['model'], 'shifts': preset['shifts'],
                    'overlap': preset['overlap']})

        if stem_files is None:
            write_progress('error', 'Stem separation failed',
                          error='Demucs did not produce stems', job_id=job_id,
                          video_title=title, action='download_stems',
                          quality=quality, genre=genre)
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_job_state()
            return

        separation_seconds = round(time.time() - separation_start, 2)

        # Step 3: Organize output files
        write_progress('finalizing', 'Organizing stem files...', percent=92,
                      job_id=job_id, video_title=title, action='download_stems',
                      quality=quality, genre=genre)

        slug = slugify(title,
                       max_length=config.get('naming', {}).get('max_length', 80),
                       video_id=video_id)

        def _read_info(folder):
            try:
                return json.loads((folder / 'info.json').read_text())
            except (OSError, ValueError):
                return None

        target, overwrite = resolve_output_folder(
            download_dir, slug, genre, quality, read_info=_read_info)

        # Assemble out of sight, then publish atomically: Ableton watches
        # these folders and must never see a half-written one
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
            # Hybrid hiphop shortcut: the instrumental is already the beat
            _place('beat', stem_files['beat'])
        elif 'combine' in genre_mode:
            for combined_name, source_stems in genre_mode['combine'].items():
                source_files = [stem_files[s] for s in source_stems if s in stem_files]
                if source_files:
                    dest = staging / f"{combined_name}{source_files[0].suffix}"
                    if combine_stems(source_files, dest):
                        copied_files.append({
                            'stem': combined_name,
                            'filename': dest.name,
                            'bytes': dest.stat().st_size,
                        })

        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        clear_job_state()

        if not copied_files:
            shutil.rmtree(staging, ignore_errors=True)
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
            (staging / 'info.json').write_text(json.dumps(info, indent=2) + '\n')

        publish_folder(staging, target, overwrite)

        # Success!
        write_progress('complete', f'Created {len(copied_files)} stem files', percent=100,
                      job_id=job_id, video_title=title, action='download_stems',
                      quality=quality, genre=genre)

    except Exception as e:
        write_progress('error', str(e), error=str(e), job_id=job_id, video_title=title,
                      action='download_stems', quality=quality, genre=genre)
        shutil.rmtree(temp_dir, ignore_errors=True)
        clear_job_state()


def start_stems_job(url, quality='fast', genre='full'):
    """Start a stem separation job as an independent background subprocess"""
    global active_job

    # Check if there's already an active job
    progress = read_progress()
    if progress.get('stage') in ['downloading', 'processing', 'finalizing']:
        # Verify the job is actually still running
        job_state = load_job_state()
        if job_state:
            pid = job_state.get('pid')
            if pid:
                try:
                    os.kill(pid, 0)  # Check if process exists
                    return {
                        'success': False,
                        'error': 'A job is already running. Please wait for it to complete or cancel it.',
                        'job_id': progress.get('job_id')
                    }
                except OSError:
                    # Process is dead, clean up the stale state
                    clear_job_state()
                    clear_progress()

    # Get video title
    title = get_video_title(url) or "stems"

    # Generate job ID
    job_id = f"job_{int(time.time())}"
    active_job = job_id

    # Spawn a completely independent subprocess to do the work
    # This process will continue running even after the native host exits
    worker_cmd = [
        sys.executable,  # Use the same Python interpreter
        SCRIPT_PATH,
        '--worker',
        '--job-id', job_id,
        '--url', url,
        '--quality', quality,
        '--genre', genre,
        '--title', title
    ]

    # Start the worker as a fully detached subprocess
    # On Unix, we use start_new_session to detach from the parent
    worker_process = subprocess.Popen(
        worker_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True  # Detach from parent process group
    )

    # Save job state with the WORKER's PID (not the native host PID)
    save_job_state(job_id, worker_process.pid, None, title, 'download_stems', quality, genre, url)

    # Write initial progress
    write_progress('downloading', 'Starting...', percent=0,
                  job_id=job_id, video_title=title, action='download_stems',
                  quality=quality, genre=genre)

    return {
        'success': True,
        'job_id': job_id,
        'video_title': title,
        'message': 'Stem separation started'
    }


def cancel_job():
    """Cancel the current running job"""
    global active_process, active_job

    progress = read_progress()
    if progress.get('stage') not in ['downloading', 'processing', 'finalizing']:
        return {'success': False, 'error': 'No active job to cancel'}

    # Try to kill the process
    job_state = load_job_state()
    if job_state:
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

        # Clean up temp directory
        temp_dir = job_state.get('temp_dir')
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Kill active process if we have a reference
    if active_process:
        try:
            active_process.terminate()
            active_process.wait(timeout=5)
        except:
            try:
                active_process.kill()
            except:
                pass
        active_process = None

    active_job = None
    clear_progress()
    clear_job_state()

    return {'success': True, 'message': 'Job cancelled'}


def check_stale_job():
    """Check for and clean up stale jobs from previous runs"""
    job_state = load_job_state()
    if not job_state:
        return

    # Check if the process is still running
    pid = job_state.get('pid')
    if pid:
        try:
            os.kill(pid, 0)  # Check if process exists
            # Process is still running, leave it alone
            return
        except OSError:
            # Process is dead, clean up
            pass

    # Clean up stale job
    temp_dir = job_state.get('temp_dir')
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)

    clear_job_state()

    # Update progress to show stale status
    progress = read_progress()
    if progress.get('stage') in ['downloading', 'processing', 'finalizing']:
        write_progress('error', 'Previous job was interrupted',
                      error='Job interrupted', job_id=progress.get('job_id'),
                      video_title=progress.get('video_title'))


def pick_output_dir():
    """Open a native macOS folder chooser and persist the selection.

    The picker has to live here, not in the extension: WebExtensions can
    never see an absolute filesystem path. The chosen folder is written to
    the config by this process, because opening the dialog takes focus and
    closes the browser popup -- nothing can be handed back to it.
    """
    current = Path(os.path.expanduser(str(get_output_dir())))
    prompt = 'Choose the Centrifugue output folder'

    script = f'POSIX path of (choose folder with prompt "{prompt}"'
    if current.is_dir():
        # Escape for AppleScript's string literal
        safe = str(current).replace('\\', '\\\\').replace('"', '\\"')
        script += f' default location POSIX file "{safe}"'
    script += ')'

    try:
        result = subprocess.run(['osascript', '-e', script],
                                capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Folder chooser timed out'}
    except FileNotFoundError:
        return {'success': False, 'error': 'osascript not found (macOS only)'}

    outcome = parse_folder_choice(result.returncode, result.stdout, result.stderr)
    if not outcome.get('success'):
        return outcome

    try:
        updated = save_config({'output_dir': outcome['output_dir']})
    except ValueError as exc:
        return {'success': False, 'error': str(exc)}

    return {'success': True, 'output_dir': outcome['output_dir'], 'config': updated}


def run_worker_mode(args):
    """Run as a background worker process (called with --worker flag)"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--quality', default='fast')
    parser.add_argument('--genre', default='full')
    parser.add_argument('--title', required=True)
    parsed = parser.parse_args(args)

    # Run the stem separation directly
    run_stem_separation_background(
        parsed.job_id,
        parsed.url,
        parsed.quality,
        parsed.genre,
        parsed.title
    )


def main():
    """Main entry point"""
    # Check if running as worker subprocess
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        run_worker_mode(sys.argv[1:])
        return

    # Check for stale jobs on startup
    check_stale_job()

    message = read_message()

    if not message:
        send_message({'success': False, 'error': 'No message received'})
        return

    action = message.get('action')

    if action == 'download' or action == 'download_mp3':
        url = message.get('url')
        if not url:
            send_message({'success': False, 'error': 'No URL provided'})
            return

        # MP3 download is quick, do it synchronously
        title = get_video_title(url) or "audio"
        write_progress('downloading', 'Downloading MP3...', percent=10,
                      video_title=title, action='download_mp3')
        result = download_mp3(url)
        if result['success']:
            write_progress('complete', f'Downloaded: {result.get("filename")}', percent=100,
                          video_title=title, action='download_mp3')
        else:
            write_progress('error', result.get('error', 'Download failed'),
                          error=result.get('error'), video_title=title, action='download_mp3')
        send_message(result)

    elif action == 'download_stems':
        url = message.get('url')
        quality = message.get('quality', 'fast')
        genre = message.get('genre', 'full')
        if not url:
            send_message({'success': False, 'error': 'No URL provided'})
            return

        # Start stem separation as background job
        result = start_stems_job(url, quality, genre)
        send_message(result)

    elif action == 'get_progress':
        progress = read_progress()
        send_message({'success': True, **progress})

    elif action == 'cancel_job':
        result = cancel_job()
        send_message(result)

    elif action == 'get_config':
        send_message({'success': True, 'config': load_config()})

    elif action == 'set_config':
        try:
            updated = save_config(message.get('config') or {})
            send_message({'success': True, 'config': updated})
        except ValueError as exc:
            send_message({'success': False, 'error': str(exc)})

    elif action == 'pick_output_dir':
        send_message(pick_output_dir())

    elif action == 'ping':
        send_message({'success': True, 'message': 'pong'})

    else:
        send_message({'success': False, 'error': f'Unknown action: {action}'})


if __name__ == '__main__':
    main()
