"""Persistent job queue for Centrifugue.

The native host handles one message and exits, so there is no daemon to
hold the queue in memory. The queue lives on disk and every mutation is a
locked read-modify-write, because workers finishing and the host reacting
to a click can collide.
"""

import fcntl
import json
import os
import shutil
import signal
import time
from pathlib import Path

SCHEMA_VERSION = 1

ACTIVE_STATUSES = ("queued", "running", "paused")
TERMINAL_STATUSES = ("complete", "error", "cancelled")


def get_queue_path():
    return Path.home() / ".centrifugue_queue.json"


def empty_queue():
    return {"schema_version": SCHEMA_VERSION, "jobs": []}


def load_queue():
    """Return the queue. Never raises: a broken file reads as empty."""
    try:
        raw = json.loads(get_queue_path().read_text())
    except (OSError, ValueError):
        return empty_queue()
    if not isinstance(raw, dict) or not isinstance(raw.get("jobs"), list):
        return empty_queue()
    raw.setdefault("schema_version", SCHEMA_VERSION)
    return raw


def save_queue(queue):
    path = get_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, indent=2) + "\n")


def make_job(job_id, url, title, quality, genre):
    return {
        "job_id": job_id,
        "url": url,
        "title": title,
        "quality": quality,
        "genre": genre,
        "status": "queued",
        "pid": None,
        "temp_dir": None,
        "added_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "error": None,
    }


def _lock_path():
    return get_queue_path().with_suffix(".lock")


def mutate_queue(fn):
    """Run fn against the queue under an exclusive lock and save the result.

    A separate lock file is used so the lock survives the queue file being
    replaced. If fn raises, nothing is written.
    """
    lock_file = _lock_path()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        queue = load_queue()
        result = fn(queue)
        save_queue(queue)
        return result
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def get_progress_dir():
    return Path.home() / ".centrifugue" / "progress"


def get_job_progress_path(job_id):
    return get_progress_dir() / f"{job_id}.json"


def read_job_progress(job_id):
    """Latest progress for a job, or {} if it has not written any."""
    try:
        data = json.loads(get_job_progress_path(job_id).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_job_progress(job_id, progress):
    path = get_job_progress_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress) + "\n")


def clear_job_progress(job_id):
    try:
        get_job_progress_path(job_id).unlink()
    except OSError:
        pass


def is_alive(pid):
    """True if the process exists. Signal 0 checks without delivering."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def reap(queue, alive=is_alive, progress=read_job_progress):
    """Move jobs whose process has died into a terminal state."""
    for job in queue["jobs"]:
        if job["status"] not in ("running", "paused"):
            continue
        if alive(job.get("pid")):
            continue

        latest = progress(job["job_id"]) or {}
        stage = latest.get("stage")
        if stage == "complete":
            job["status"] = "complete"
        else:
            job["status"] = "error"
            job["error"] = (latest.get("error")
                            or latest.get("message")
                            or "Worker exited unexpectedly")
        job["pid"] = None
        job["finished_at"] = time.time()


def schedule(queue, spawn, cont, alive=is_alive):
    """Start at most one job. Returns the job started, or None."""
    if any(job["status"] == "running" for job in queue["jobs"]):
        return None

    for job in queue["jobs"]:
        if job["status"] != "queued":
            continue
        pid = job.get("pid")
        if pid and alive(pid):
            # Previously paused then resumed: continue rather than restart
            cont(pid)
        else:
            job["pid"] = spawn(job)
        job["status"] = "running"
        job["started_at"] = time.time()
        return job
    return None


def tick(spawn=None, cont=None):
    """Reap dead jobs and start the next one. Returns the updated queue."""
    def run(queue):
        reap(queue)
        if spawn is not None and cont is not None:
            schedule(queue, spawn, cont)
        return queue

    return mutate_queue(run)


def find_job(queue, job_id):
    for job in queue["jobs"]:
        if job["job_id"] == job_id:
            return job
    return None


def count_paused(queue):
    return sum(1 for job in queue["jobs"] if job["status"] == "paused")


def stop_group(pid):
    """Freeze a worker and its children. Missing process is not an error."""
    try:
        os.killpg(pid, signal.SIGSTOP)
    except (ProcessLookupError, PermissionError):
        pass


def cont_group(pid):
    try:
        os.killpg(pid, signal.SIGCONT)
    except (ProcessLookupError, PermissionError):
        pass


def kill_group(pid):
    try:
        # Continue first: a frozen process never sees SIGTERM
        os.killpg(pid, signal.SIGCONT)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def pause_job(job_id, stop=stop_group, max_paused=2):
    def run(queue):
        job = find_job(queue, job_id)
        if job is None:
            return {"success": False, "error": f"No such job: {job_id}"}
        if job["status"] not in ("running", "queued"):
            return {"success": False,
                    "error": f"Cannot pause a {job['status']} job"}
        if count_paused(queue) >= max_paused:
            return {"success": False,
                    "error": (f"Already {max_paused} paused job(s); frozen jobs "
                              f"hold memory. Resume or remove one first.")}
        if job.get("pid"):
            stop(job["pid"])
        job["status"] = "paused"
        return {"success": True}

    return mutate_queue(run)


def resume_job(job_id):
    def run(queue):
        job = find_job(queue, job_id)
        if job is None:
            return {"success": False, "error": f"No such job: {job_id}"}
        if job["status"] != "paused":
            return {"success": False,
                    "error": f"Cannot resume a {job['status']} job"}
        # Keep the pid: the scheduler continues rather than restarting
        job["status"] = "queued"
        return {"success": True}

    return mutate_queue(run)


def remove_job(job_id, kill=kill_group):
    def run(queue):
        job = find_job(queue, job_id)
        if job is None:
            return {"success": False, "error": f"No such job: {job_id}"}
        if job.get("pid"):
            kill(job["pid"])
        temp_dir = job.get("temp_dir")
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        queue["jobs"] = [j for j in queue["jobs"] if j["job_id"] != job_id]
        return {"success": True}

    result = mutate_queue(run)
    clear_job_progress(job_id)
    return result


def migrate_legacy_job(legacy, alive=is_alive):
    """Adopt an in-flight job from the pre-queue single-job file.

    Only a live process is worth adopting; a dead one is history and its
    progress file (if any) is stale.
    """
    if not legacy:
        return None
    pid = legacy.get("pid")
    if not pid or not alive(pid):
        return None

    job = make_job(
        legacy.get("job_id") or f"job_{int(time.time() * 1000)}",
        legacy.get("url") or "",
        legacy.get("title") or "Unknown",
        legacy.get("quality") or "fast",
        legacy.get("genre") or "full",
    )
    job["status"] = "running"
    job["pid"] = pid
    job["temp_dir"] = legacy.get("temp_dir")
    job["started_at"] = legacy.get("started")
    return job
