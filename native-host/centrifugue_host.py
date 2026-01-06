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
from pathlib import Path

# Ensure Homebrew binaries are in PATH
os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH', '')

# Get the directory containing this script
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent

# Demucs virtual environment (relative to project root)
DEMUCS_VENV = PROJECT_ROOT / 'venv-demucs'
DEMUCS_PYTHON = DEMUCS_VENV / 'bin' / 'python'

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
        'model': 'htdemucs',
        'shifts': 5,
        'overlap': 0.5,
        'cpu_limit': 400,
        'time_multiplier': 1.2,
        'description': 'Good balance of speed and quality'
    },
    'high': {
        'model': 'htdemucs_ft',
        'shifts': 10,
        'overlap': 0.75,
        'cpu_limit': 500,
        'time_multiplier': 2.5,
        'description': 'Best quality, minimal stem bleeding'
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
    """Get the download directory (~/Downloads by default)"""
    return Path.home() / "Downloads"


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
    """Find yt-dlp in common locations"""
    locations = [
        '/opt/homebrew/bin/yt-dlp',
        '/usr/local/bin/yt-dlp',
        '/usr/bin/yt-dlp',
    ]
    for loc in locations:
        if os.path.isfile(loc) and os.access(loc, os.X_OK):
            return loc
    return 'yt-dlp'


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


def get_video_title(url):
    """Get the video title from YouTube URL"""
    ytdlp_path = find_ytdlp()
    try:
        result = subprocess.run(
            [ytdlp_path, '--get-title', '--no-playlist', url],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return sanitize_filename(result.stdout.strip())
    except:
        pass
    return None


def combine_stems(stem_files, output_path):
    """Combine multiple stem files into a single mixed audio file using ffmpeg"""
    ffmpeg_path = find_ffmpeg()

    cmd = [ffmpeg_path, '-y']
    for stem_file in stem_files:
        cmd.extend(['-i', str(stem_file)])

    cmd.extend([
        '-filter_complex', f'amix=inputs={len(stem_files)}:duration=longest',
        '-codec:a', 'libmp3lame',
        '-b:a', '320k',
        str(output_path)
    ])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except Exception:
        return False


def parse_demucs_progress(line):
    """Parse demucs tqdm output for progress percentage"""
    # tqdm format: " 50%|█████     | 617/1234 [01:23<01:20, 7.68it/s]"
    # or: "Separating track 1/1"
    match = re.search(r'(\d+)%\|', line)
    if match:
        return int(match.group(1))
    return None


def download_mp3(url):
    """Download YouTube video as MP3 using yt-dlp"""
    download_dir = get_download_dir()
    ytdlp_path = find_ytdlp()

    cmd = [
        ytdlp_path,
        '--extract-audio',
        '--audio-format', 'mp3',
        '--audio-quality', '0',
        '--output', str(download_dir / '%(title)s.%(ext)s'),
        '--no-playlist',
        '--print', 'after_move:filepath',
        url
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            output_lines = result.stdout.strip().split('\n')
            filename = output_lines[-1] if output_lines else "download complete"

            if os.path.exists(filename):
                filename = os.path.basename(filename)

            return {
                'success': True,
                'filename': filename,
                'message': 'Download completed successfully'
            }
        else:
            return {
                'success': False,
                'error': result.stderr or 'yt-dlp failed with no error message'
            }

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


def run_stem_separation_background(job_id, url, quality, genre, title):
    """Run stem separation as independent worker process with real-time progress parsing"""
    global active_process

    download_dir = get_download_dir()
    ytdlp_path = find_ytdlp()
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS['fast'])
    genre_mode = GENRE_MODES.get(genre, GENRE_MODES['full'])

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
            url
        ]

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

        # Get audio duration for better estimates
        audio_duration = get_audio_duration(audio_file)
        if audio_duration:
            estimated_seconds = int(audio_duration * preset['time_multiplier']) + 30
        else:
            estimated_seconds = {'fast': 90, 'balanced': 300, 'high': 600}.get(quality, 120)

        write_progress('processing', 'Separating stems with AI...', percent=10,
                      estimated_seconds=estimated_seconds, job_id=job_id, video_title=title,
                      action='download_stems', quality=quality, genre=genre)

        # Step 2: Run Demucs with real-time progress parsing
        demucs_output = temp_path / "separated"

        demucs_cmd = [
            str(DEMUCS_PYTHON), '-m', 'demucs',
            str(audio_file),
            '-n', preset['model'],
            '-o', str(demucs_output),
            '--overlap', str(preset['overlap']),
            '--mp3', '--mp3-bitrate', '320',
            '-d', 'mps'  # Use Apple Metal Performance Shaders for GPU acceleration
        ]

        if preset['shifts'] > 0:
            demucs_cmd.extend(['--shifts', str(preset['shifts'])])

        # Start demucs process
        active_process = subprocess.Popen(
            demucs_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Read stderr for progress (tqdm outputs to stderr)
        last_percent = 10
        for line in active_process.stderr:
            progress = parse_demucs_progress(line)
            if progress is not None and progress > last_percent:
                last_percent = progress
                # Scale 0-100 demucs progress to 10-90 overall progress
                overall = 10 + int(progress * 0.8)
                write_progress('processing', f'Separating stems... {progress}%', percent=overall,
                              estimated_seconds=estimated_seconds, job_id=job_id, video_title=title,
                              action='download_stems', quality=quality, genre=genre)

        active_process.wait()

        if active_process.returncode != 0:
            stderr_output = active_process.stderr.read() if active_process.stderr else "Unknown error"
            write_progress('error', f'Stem separation failed',
                          error=stderr_output, job_id=job_id, video_title=title,
                          action='download_stems', quality=quality, genre=genre)
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_job_state()
            active_process = None
            return

        active_process = None

        # Step 3: Organize output files
        write_progress('finalizing', 'Organizing stem files...', percent=92,
                      job_id=job_id, video_title=title, action='download_stems',
                      quality=quality, genre=genre)

        quality_suffix = {'fast': '', 'balanced': ' (HQ)', 'high': ' (Ultra)'}
        genre_suffix = {'full': 'Stems', 'hiphop': 'Hip Hop', 'rock': 'Rock'}
        output_folder = download_dir / f"{title} - {genre_suffix.get(genre, 'Stems')}{quality_suffix.get(quality, '')}"
        output_folder.mkdir(exist_ok=True)

        # Find the stems
        stems_dir = demucs_output / preset['model'] / audio_file.stem
        if not stems_dir.exists():
            for potential_dir in demucs_output.rglob("*"):
                if potential_dir.is_dir() and any(potential_dir.glob("*.mp3")):
                    stems_dir = potential_dir
                    break

        if not stems_dir.exists():
            write_progress('error', 'Stem files not found after separation',
                          error='Output files not found', job_id=job_id, video_title=title,
                          action='download_stems', quality=quality, genre=genre)
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_job_state()
            return

        stem_mapping = {
            'vocals': 'Vocals',
            'drums': 'Drums',
            'bass': 'Bass',
            'other': 'Other'
        }

        stem_files = {}
        for stem_file in stems_dir.glob("*.*"):
            stem_name = stem_file.stem.lower()
            if stem_name in stem_mapping:
                stem_files[stem_name] = stem_file

        copied_files = []

        for stem_name in genre_mode['stems']:
            if stem_name in stem_files:
                stem_file = stem_files[stem_name]
                dest_name = f"{title} - {stem_mapping[stem_name]}{stem_file.suffix}"
                dest_path = output_folder / dest_name
                shutil.copy2(stem_file, dest_path)
                copied_files.append(dest_name)

        if 'combine' in genre_mode:
            for combined_name, source_stems in genre_mode['combine'].items():
                source_files = [stem_files[s] for s in source_stems if s in stem_files]
                if source_files:
                    combined_dest = output_folder / f"{title} - {combined_name.title()}.mp3"
                    if combine_stems(source_files, combined_dest):
                        copied_files.append(f"{title} - {combined_name.title()}.mp3")

        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        clear_job_state()

        if not copied_files:
            write_progress('error', 'No stem files were created',
                          error='No output files', job_id=job_id, video_title=title,
                          action='download_stems', quality=quality, genre=genre)
            return

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

    elif action == 'ping':
        send_message({'success': True, 'message': 'pong'})

    else:
        send_message({'success': False, 'error': f'Unknown action: {action}'})


if __name__ == '__main__':
    main()
