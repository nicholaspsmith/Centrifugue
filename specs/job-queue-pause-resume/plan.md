# Job Queue with Pause/Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Queue any number of songs, convert them one at a time, and pause/resume an individual conversion without losing progress.

**Architecture:** A new `centrifugue_queue.py` owns the queue file and a `tick()` scheduler that is the only code allowed to start work. Pause freezes the worker's process group with `SIGSTOP`; resume `SIGCONT`s it. Process control is injected so the scheduler is unit-testable without spawning real workers.

**Tech Stack:** Python 3.9+, pytest, stdlib only (`fcntl`, `signal`, `os`, `json`). No new runtime dependencies.

## Global Constraints

- Spec: `specs/job-queue-pause-resume/spec.md`. Read it before starting.
- No new runtime dependencies. pytest is dev-only.
- Exactly one job may be `running` at any time.
- `max_paused_jobs` default is `2`; `0` disables pausing.
- Every queue read-modify-write happens under an `fcntl.flock` on the queue file.
- A corrupt queue file yields an empty queue and is never fatal.
- Signals to a dead PID are not errors — reap the job and continue.
- Commit messages follow `.claude/rules.md`: imperative subject ≤72 chars, body containing only `Co-Authored-By: Claude <noreply@anthropic.com>`, one responsibility per commit, no AI attribution.
- Both extensions stay in sync: every UI change lands in `extension-firefox/` **and** `extension-chrome/`.
- Run tests with `./venv-demucs/bin/python -m pytest`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `native-host/centrifugue_queue.py` | **Create.** Queue file I/O, locking, `tick()` scheduler, pause/resume/remove, migration. |
| `native-host/centrifugue_host.py` | **Modify.** Enqueue instead of refuse; per-job progress paths; new actions; worker calls `tick()` on exit. |
| `native-host/centrifugue_config.py` | **Modify.** Add `max_paused_jobs`. |
| `extension-*/background.js` | **Modify.** Relay the new actions. |
| `extension-*/popup/popup.{html,js}` | **Modify.** Queue list UI. |
| `extension-*/content.js` | **Modify.** Queue list in the floating menu. |
| `tests/test_queue.py` | **Create.** Queue file + migration. |
| `tests/test_scheduler.py` | **Create.** `tick()` behaviour with injected process control. |
| `tests/test_queue_ops.py` | **Create.** Pause/resume/remove. |

**Phasing:** Tasks 1–6 deliver a working, fully tested engine with no UI. Tasks 7–9 add the UI.

---

### Task 1: Queue file storage

**Files:**
- Create: `native-host/centrifugue_queue.py`
- Create: `tests/test_queue.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SCHEMA_VERSION: int`
  - `get_queue_path() -> Path`
  - `load_queue() -> dict` — never raises; returns `{"schema_version": 1, "jobs": [...]}`
  - `save_queue(queue: dict) -> None`
  - `make_job(job_id, url, title, quality, genre) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/test_queue.py`:

```python
import json
import pytest
import centrifugue_queue as q


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "get_queue_path", lambda: tmp_path / "queue.json")
    return tmp_path


def test_missing_file_returns_empty_queue():
    assert q.load_queue() == {"schema_version": q.SCHEMA_VERSION, "jobs": []}


def test_corrupt_file_returns_empty_queue_rather_than_raising(isolated_queue):
    (isolated_queue / "queue.json").write_text("{not json")
    assert q.load_queue()["jobs"] == []


def test_non_dict_file_returns_empty_queue(isolated_queue):
    (isolated_queue / "queue.json").write_text("[1,2,3]")
    assert q.load_queue()["jobs"] == []


def test_save_then_load_round_trips(isolated_queue):
    job = q.make_job("job_1", "http://x", "Song", "ultra", "rock")
    q.save_queue({"schema_version": q.SCHEMA_VERSION, "jobs": [job]})
    loaded = q.load_queue()
    assert [j["job_id"] for j in loaded["jobs"]] == ["job_1"]
    assert loaded["jobs"][0]["title"] == "Song"


def test_new_job_starts_queued_with_no_pid():
    job = q.make_job("job_1", "http://x", "Song", "ultra", "rock")
    assert job["status"] == "queued"
    assert job["pid"] is None
    assert job["temp_dir"] is None
    assert job["finished_at"] is None
    assert job["error"] is None
    assert job["added_at"] > 0


def test_saved_queue_is_valid_json_on_disk(isolated_queue):
    q.save_queue({"schema_version": q.SCHEMA_VERSION, "jobs": []})
    json.loads((isolated_queue / "queue.json").read_text())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'centrifugue_queue'`

- [ ] **Step 3: Implement storage**

`native-host/centrifugue_queue.py`:

```python
"""Persistent job queue for Centrifugue.

The native host handles one message and exits, so there is no daemon to
hold the queue in memory. The queue lives on disk and every mutation is a
locked read-modify-write, because workers finishing and the host reacting
to a click can collide.
"""

import json
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_queue.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add native-host/centrifugue_queue.py tests/test_queue.py
git commit -m "Add persistent job queue storage"
```

---

### Task 2: Locked mutation helper

**Files:**
- Modify: `native-host/centrifugue_queue.py`
- Modify: `tests/test_queue.py`

**Interfaces:**
- Consumes: `load_queue`, `save_queue` from Task 1.
- Produces: `mutate_queue(fn: Callable[[dict], Any]) -> Any` — locks the queue file, loads, calls `fn(queue)`, saves, returns `fn`'s return value.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_queue.py`:

```python
def test_mutate_persists_changes():
    def add(queue):
        queue["jobs"].append(q.make_job("job_1", "u", "t", "fast", "full"))
        return "added"

    assert q.mutate_queue(add) == "added"
    assert len(q.load_queue()["jobs"]) == 1


def test_mutate_on_missing_file_starts_from_empty():
    q.mutate_queue(lambda queue: queue["jobs"].append(
        q.make_job("job_1", "u", "t", "fast", "full")))
    assert len(q.load_queue()["jobs"]) == 1


def test_mutate_propagates_exceptions_without_saving(isolated_queue):
    q.mutate_queue(lambda queue: queue["jobs"].append(
        q.make_job("job_1", "u", "t", "fast", "full")))

    def boom(queue):
        queue["jobs"].append(q.make_job("job_2", "u", "t", "fast", "full"))
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        q.mutate_queue(boom)
    # the failed mutation must not have been written
    assert [j["job_id"] for j in q.load_queue()["jobs"]] == ["job_1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_queue.py -k mutate -v`
Expected: FAIL — `AttributeError: module 'centrifugue_queue' has no attribute 'mutate_queue'`

- [ ] **Step 3: Implement the locked mutation**

Add `import fcntl` and `import os` to the imports, then append:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_queue.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add native-host/centrifugue_queue.py tests/test_queue.py
git commit -m "Add locked read-modify-write for the job queue"
```

---

### Task 3: Progress file paths

**Files:**
- Modify: `native-host/centrifugue_queue.py`
- Modify: `tests/test_queue.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `get_progress_dir() -> Path`
  - `get_job_progress_path(job_id: str) -> Path`
  - `read_job_progress(job_id: str) -> dict` — `{}` when absent or unreadable
  - `write_job_progress(job_id: str, progress: dict) -> None`
  - `clear_job_progress(job_id: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_queue.py`:

```python
@pytest.fixture
def isolated_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "get_progress_dir", lambda: tmp_path / "progress")
    return tmp_path / "progress"


def test_missing_progress_reads_as_empty_dict(isolated_progress):
    assert q.read_job_progress("job_1") == {}


def test_progress_round_trips(isolated_progress):
    q.write_job_progress("job_1", {"stage": "processing", "percent": 42})
    assert q.read_job_progress("job_1")["percent"] == 42


def test_corrupt_progress_reads_as_empty_dict(isolated_progress):
    isolated_progress.mkdir(parents=True, exist_ok=True)
    (isolated_progress / "job_1.json").write_text("{broken")
    assert q.read_job_progress("job_1") == {}


def test_clear_progress_removes_the_file(isolated_progress):
    q.write_job_progress("job_1", {"stage": "complete"})
    q.clear_job_progress("job_1")
    assert q.read_job_progress("job_1") == {}


def test_clearing_absent_progress_is_not_an_error(isolated_progress):
    q.clear_job_progress("never_existed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_queue.py -k progress -v`
Expected: FAIL — `AttributeError: module 'centrifugue_queue' has no attribute 'get_progress_dir'`

- [ ] **Step 3: Implement progress files**

Append to `native-host/centrifugue_queue.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_queue.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add native-host/centrifugue_queue.py tests/test_queue.py
git commit -m "Add per-job progress files"
```

---

### Task 4: The tick() scheduler

**Files:**
- Modify: `native-host/centrifugue_queue.py`
- Create: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `mutate_queue`, `read_job_progress` from Tasks 2–3.
- Produces:
  - `is_alive(pid: int) -> bool`
  - `reap(queue: dict, alive=is_alive, progress=read_job_progress) -> None` — mutates in place
  - `schedule(queue: dict, spawn, cont, alive=is_alive) -> dict | None` — starts at most one job, returns it
  - `tick(spawn=None, cont=None) -> dict` — locked reap + schedule, returns the queue

`spawn(job) -> int` returns a new PID. `cont(pid) -> None` continues a frozen group. Both are injected so tests never create processes.

- [ ] **Step 1: Write the failing tests**

`tests/test_scheduler.py`:

```python
import pytest
import centrifugue_queue as q


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "get_queue_path", lambda: tmp_path / "queue.json")
    monkeypatch.setattr(q, "get_progress_dir", lambda: tmp_path / "progress")
    return tmp_path


def _queue(*jobs):
    return {"schema_version": q.SCHEMA_VERSION, "jobs": list(jobs)}


def _job(job_id, status="queued", pid=None):
    job = q.make_job(job_id, "u", job_id, "fast", "full")
    job["status"] = status
    job["pid"] = pid
    return job


class Recorder:
    def __init__(self, next_pid=999):
        self.spawned, self.continued, self.next_pid = [], [], next_pid

    def spawn(self, job):
        self.spawned.append(job["job_id"])
        return self.next_pid

    def cont(self, pid):
        self.continued.append(pid)


def test_empty_queue_starts_nothing():
    rec = Recorder()
    assert q.schedule(_queue(), rec.spawn, rec.cont) is None
    assert rec.spawned == []


def test_queued_job_without_pid_is_spawned():
    queue = _queue(_job("a"))
    rec = Recorder(next_pid=4242)
    started = q.schedule(queue, rec.spawn, rec.cont)
    assert started["job_id"] == "a"
    assert queue["jobs"][0]["status"] == "running"
    assert queue["jobs"][0]["pid"] == 4242
    assert queue["jobs"][0]["started_at"] is not None
    assert rec.spawned == ["a"] and rec.continued == []


def test_queued_job_with_live_pid_is_continued_not_respawned():
    queue = _queue(_job("a", pid=1234))
    rec = Recorder()
    q.schedule(queue, rec.spawn, rec.cont, alive=lambda pid: True)
    assert rec.continued == [1234]
    assert rec.spawned == []
    assert queue["jobs"][0]["status"] == "running"


def test_queued_job_with_dead_pid_is_respawned():
    queue = _queue(_job("a", pid=1234))
    rec = Recorder(next_pid=77)
    q.schedule(queue, rec.spawn, rec.cont, alive=lambda pid: False)
    assert rec.spawned == ["a"]
    assert queue["jobs"][0]["pid"] == 77


def test_nothing_starts_while_a_job_is_running():
    queue = _queue(_job("a", status="running", pid=1), _job("b"))
    rec = Recorder()
    assert q.schedule(queue, rec.spawn, rec.cont, alive=lambda pid: True) is None
    assert rec.spawned == []


def test_paused_jobs_are_skipped():
    queue = _queue(_job("a", status="paused", pid=1), _job("b"))
    rec = Recorder()
    started = q.schedule(queue, rec.spawn, rec.cont, alive=lambda pid: True)
    assert started["job_id"] == "b"


def test_jobs_start_in_order():
    queue = _queue(_job("a"), _job("b"))
    rec = Recorder()
    started = q.schedule(queue, rec.spawn, rec.cont)
    assert started["job_id"] == "a"


def test_reap_marks_dead_running_job_complete_when_progress_says_so():
    queue = _queue(_job("a", status="running", pid=1))
    q.reap(queue, alive=lambda pid: False,
           progress=lambda job_id: {"stage": "complete"})
    assert queue["jobs"][0]["status"] == "complete"
    assert queue["jobs"][0]["finished_at"] is not None


def test_reap_marks_dead_running_job_error_when_progress_is_incomplete():
    queue = _queue(_job("a", status="running", pid=1))
    q.reap(queue, alive=lambda pid: False,
           progress=lambda job_id: {"stage": "processing", "message": "halfway"})
    assert queue["jobs"][0]["status"] == "error"
    assert "halfway" in queue["jobs"][0]["error"]


def test_reap_uses_the_progress_error_when_present():
    queue = _queue(_job("a", status="running", pid=1))
    q.reap(queue, alive=lambda pid: False,
           progress=lambda job_id: {"stage": "error", "error": "demucs blew up"})
    assert queue["jobs"][0]["status"] == "error"
    assert queue["jobs"][0]["error"] == "demucs blew up"


def test_reap_leaves_live_jobs_alone():
    queue = _queue(_job("a", status="running", pid=1))
    q.reap(queue, alive=lambda pid: True, progress=lambda job_id: {})
    assert queue["jobs"][0]["status"] == "running"


def test_reap_clears_pid_on_terminal_jobs():
    queue = _queue(_job("a", status="running", pid=1))
    q.reap(queue, alive=lambda pid: False,
           progress=lambda job_id: {"stage": "complete"})
    assert queue["jobs"][0]["pid"] is None


def test_tick_reaps_then_schedules():
    q.save_queue(_queue(_job("a", status="running", pid=1), _job("b")))
    rec = Recorder(next_pid=55)
    result = q.tick(spawn=rec.spawn, cont=rec.cont)
    # 'a' is dead so it is reaped, freeing the slot for 'b'
    statuses = {j["job_id"]: j["status"] for j in result["jobs"]}
    assert statuses["a"] == "error"
    assert statuses["b"] == "running"
    assert rec.spawned == ["b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — `AttributeError: module 'centrifugue_queue' has no attribute 'schedule'`

- [ ] **Step 3: Implement the scheduler**

Append to `native-host/centrifugue_queue.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_scheduler.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add native-host/centrifugue_queue.py tests/test_scheduler.py
git commit -m "Add queue scheduler with reap and start-one semantics"
```

---

### Task 5: Pause, resume, and remove

**Files:**
- Modify: `native-host/centrifugue_queue.py`
- Create: `tests/test_queue_ops.py`

**Interfaces:**
- Consumes: `mutate_queue`, `is_alive` from Tasks 2 and 4.
- Produces:
  - `find_job(queue: dict, job_id: str) -> dict | None`
  - `count_paused(queue: dict) -> int`
  - `pause_job(job_id, stop=..., max_paused=2) -> dict` — `{"success": bool, "error": str}`
  - `resume_job(job_id) -> dict`
  - `remove_job(job_id, kill=...) -> dict`

`stop(pid)` and `kill(pid)` are injected; production passes process-group signal senders.

- [ ] **Step 1: Write the failing tests**

`tests/test_queue_ops.py`:

```python
import pytest
import centrifugue_queue as q


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "get_queue_path", lambda: tmp_path / "queue.json")
    monkeypatch.setattr(q, "get_progress_dir", lambda: tmp_path / "progress")
    return tmp_path


def _seed(*jobs):
    q.save_queue({"schema_version": q.SCHEMA_VERSION, "jobs": list(jobs)})


def _job(job_id, status="queued", pid=None):
    job = q.make_job(job_id, "u", job_id, "fast", "full")
    job["status"] = status
    job["pid"] = pid
    return job


def test_pause_running_job_stops_it():
    _seed(_job("a", status="running", pid=1))
    stopped = []
    result = q.pause_job("a", stop=stopped.append)
    assert result["success"] is True
    assert stopped == [1]
    assert q.find_job(q.load_queue(), "a")["status"] == "paused"


def test_pause_queued_job_sends_no_signal():
    _seed(_job("a"))
    stopped = []
    result = q.pause_job("a", stop=stopped.append)
    assert result["success"] is True
    assert stopped == []
    assert q.find_job(q.load_queue(), "a")["status"] == "paused"


def test_pause_refused_at_the_cap():
    _seed(_job("a", status="paused", pid=1),
          _job("b", status="paused", pid=2),
          _job("c", status="running", pid=3))
    result = q.pause_job("c", stop=lambda pid: None, max_paused=2)
    assert result["success"] is False
    assert "2" in result["error"]
    assert q.find_job(q.load_queue(), "c")["status"] == "running"


def test_pause_disabled_when_cap_is_zero():
    _seed(_job("a", status="running", pid=1))
    result = q.pause_job("a", stop=lambda pid: None, max_paused=0)
    assert result["success"] is False


def test_pause_unknown_job_reports_an_error():
    _seed()
    assert q.pause_job("nope", stop=lambda pid: None)["success"] is False


def test_pause_terminal_job_is_refused():
    _seed(_job("a", status="complete"))
    assert q.pause_job("a", stop=lambda pid: None)["success"] is False


def test_resume_returns_job_to_queued_keeping_its_pid():
    _seed(_job("a", status="paused", pid=1))
    result = q.resume_job("a")
    assert result["success"] is True
    job = q.find_job(q.load_queue(), "a")
    assert job["status"] == "queued"
    assert job["pid"] == 1


def test_resume_non_paused_job_is_refused():
    _seed(_job("a", status="running", pid=1))
    assert q.resume_job("a")["success"] is False


def test_remove_running_job_kills_it():
    _seed(_job("a", status="running", pid=7))
    killed = []
    result = q.remove_job("a", kill=killed.append)
    assert result["success"] is True
    assert killed == [7]
    assert q.find_job(q.load_queue(), "a") is None


def test_remove_queued_job_sends_no_signal():
    _seed(_job("a"))
    killed = []
    q.remove_job("a", kill=killed.append)
    assert killed == []
    assert q.load_queue()["jobs"] == []


def test_remove_unknown_job_reports_an_error():
    _seed()
    assert q.remove_job("nope", kill=lambda pid: None)["success"] is False


def test_count_paused_counts_only_paused():
    queue = {"schema_version": 1, "jobs": [
        _job("a", status="paused", pid=1),
        _job("b", status="running", pid=2),
        _job("c", status="paused", pid=3),
    ]}
    assert q.count_paused(queue) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_queue_ops.py -v`
Expected: FAIL — `AttributeError: module 'centrifugue_queue' has no attribute 'pause_job'`

- [ ] **Step 3: Implement the operations**

Add `import shutil` and `import signal` to the imports, then append:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/test_queue_ops.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add native-host/centrifugue_queue.py tests/test_queue_ops.py
git commit -m "Add pause, resume, and remove queue operations"
```

---

### Task 6: Wire the host to the queue

**Files:**
- Modify: `native-host/centrifugue_config.py`
- Modify: `native-host/centrifugue_host.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: native actions `get_queue`, `pause_job`, `resume_job`, `remove_job`; `download_stems` now enqueues.

- [ ] **Step 1: Add the config key**

In `native-host/centrifugue_config.py`, extend `DEFAULT_CONFIG`:

```python
DEFAULT_CONFIG = {
    "output_dir": "~/Downloads",
    "naming": {"style": "lowercase_ascii", "max_length": 80},
    "write_info_json": True,
    "cookies_from_browser": "auto",
    "max_paused_jobs": 2,
}
```

- [ ] **Step 2: Import the queue module in the host**

Add beside the other `centrifugue_*` imports at the top of
`native-host/centrifugue_host.py`:

```python
import centrifugue_queue as jobq
```

- [ ] **Step 3: Route progress writes to per-job files**

`write_progress()` currently writes one shared file. Give it a `job_id` and
write both the legacy file (so an old popup still works) and the per-job file.
Add this at the end of `write_progress`, after the existing legacy write:

```python
    if job_id:
        jobq.write_job_progress(job_id, progress)
```

- [ ] **Step 4: Replace the single-job guard with an enqueue**

Replace the body of `start_stems_job` down to (but not including) the
`worker_cmd` construction with:

```python
def spawn_worker(job):
    """Launch a detached worker for a queued job; returns its pid."""
    worker_cmd = [
        sys.executable, SCRIPT_PATH, '--worker',
        '--job-id', job['job_id'],
        '--url', job['url'],
        '--quality', job['quality'],
        '--genre', job['genre'],
        '--title', job['title'],
    ]
    proc = subprocess.Popen(
        worker_cmd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def start_stems_job(url, quality='fast', genre='full'):
    """Append a job to the queue and start it if the slot is free."""
    title = get_video_title(url) or "stems"
    job_id = f"job_{int(time.time() * 1000)}"

    def add(queue):
        queue['jobs'].append(jobq.make_job(job_id, url, title, quality, genre))

    jobq.mutate_queue(add)
    jobq.tick(spawn=spawn_worker, cont=jobq.cont_group)

    return {'success': True, 'job_id': job_id, 'video_title': title,
            'queued': True}
```

`job_id` uses milliseconds because two songs queued in the same second would
otherwise collide.

- [ ] **Step 5: Have the worker advance the queue when it exits**

At the very end of `run_worker_mode`, after the separation function returns,
add:

```python
    # Keep the queue moving even with the browser closed
    try:
        jobq.tick(spawn=spawn_worker, cont=jobq.cont_group)
    except Exception:
        pass
```

- [ ] **Step 6: Add the dispatch entries**

In `main()`, insert before the `elif action == 'ping':` branch:

```python
    elif action == 'get_queue':
        queue = jobq.tick(spawn=spawn_worker, cont=jobq.cont_group)
        jobs = []
        for job in queue['jobs']:
            merged = dict(job)
            merged['progress'] = jobq.read_job_progress(job['job_id'])
            jobs.append(merged)
        send_message({'success': True, 'jobs': jobs})

    elif action == 'pause_job':
        limit = load_config().get('max_paused_jobs', 2)
        result = jobq.pause_job(message.get('job_id'), max_paused=limit)
        if result.get('success'):
            jobq.tick(spawn=spawn_worker, cont=jobq.cont_group)
        send_message(result)

    elif action == 'resume_job':
        result = jobq.resume_job(message.get('job_id'))
        if result.get('success'):
            jobq.tick(spawn=spawn_worker, cont=jobq.cont_group)
        send_message(result)

    elif action == 'remove_job':
        result = jobq.remove_job(message.get('job_id'))
        if result.get('success'):
            jobq.tick(spawn=spawn_worker, cont=jobq.cont_group)
        send_message(result)
```

- [ ] **Step 7: Verify**

Run: `./venv-demucs/bin/python -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1–5 plus the existing suite)

Run:

```bash
./venv-demucs/bin/python - <<'PY'
import json, struct, subprocess
def call(msg):
    data = json.dumps(msg).encode()
    p = subprocess.run(["./venv-demucs/bin/python", "native-host/centrifugue_host.py"],
                       input=struct.pack("<I", len(data)) + data,
                       capture_output=True, timeout=60)
    n = struct.unpack("<I", p.stdout[:4])[0]
    return json.loads(p.stdout[4:4+n])
print("get_queue  ->", call({"action": "get_queue"}))
print("pause bad  ->", call({"action": "pause_job", "job_id": "nope"}))
PY
```

Expected: `get_queue` returns `{'success': True, 'jobs': [...]}`; the bad pause
returns `success: False` with a "No such job" message.

- [ ] **Step 8: Commit**

```bash
git add native-host/centrifugue_config.py native-host/centrifugue_host.py
git commit -m "Enqueue stem jobs and expose queue control actions"
```

---

### Task 7: Migration from the legacy single-job files

**Files:**
- Modify: `native-host/centrifugue_queue.py`
- Modify: `tests/test_queue.py`

**Interfaces:**
- Consumes: `load_queue`, `save_queue`, `make_job`, `is_alive`.
- Produces: `migrate_legacy_job(legacy: dict | None, alive=is_alive) -> dict | None` — the job record to adopt, or None.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_queue.py`:

```python
LEGACY = {
    "job_id": "job_old", "pid": 4321, "temp_dir": "/tmp/x",
    "title": "Old Song", "action": "download_stems",
    "quality": "ultra", "genre": "rock", "url": "http://x",
}


def test_live_legacy_job_is_adopted_as_running():
    job = q.migrate_legacy_job(LEGACY, alive=lambda pid: True)
    assert job["job_id"] == "job_old"
    assert job["status"] == "running"
    assert job["pid"] == 4321
    assert job["quality"] == "ultra"
    assert job["temp_dir"] == "/tmp/x"


def test_dead_legacy_job_is_ignored():
    assert q.migrate_legacy_job(LEGACY, alive=lambda pid: False) is None


def test_absent_legacy_job_is_ignored():
    assert q.migrate_legacy_job(None, alive=lambda pid: True) is None


def test_legacy_job_without_pid_is_ignored():
    assert q.migrate_legacy_job({"job_id": "x"}, alive=lambda pid: True) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv-demucs/bin/python -m pytest tests/test_queue.py -k legacy -v`
Expected: FAIL — `AttributeError: module 'centrifugue_queue' has no attribute 'migrate_legacy_job'`

- [ ] **Step 3: Implement migration**

Append to `native-host/centrifugue_queue.py`:

```python
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
```

- [ ] **Step 4: Call it from the host on startup**

In `native-host/centrifugue_host.py`, replace the `check_stale_job()` call in
`main()` with:

```python
    adopt_legacy_job()
    check_stale_job()
```

and add this function above `main()`:

```python
def adopt_legacy_job():
    """One-time import of a pre-queue job so it is not orphaned."""
    if jobq.get_queue_path().exists():
        return
    legacy = load_job_state()
    job = jobq.migrate_legacy_job(legacy)
    queue = jobq.empty_queue()
    if job:
        queue['jobs'].append(job)
    jobq.save_queue(queue)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv-demucs/bin/python -m pytest tests/ -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add native-host/centrifugue_queue.py native-host/centrifugue_host.py tests/test_queue.py
git commit -m "Adopt an in-flight legacy job into the queue"
```

---

### Task 8: Background relays and popup queue UI

**Files:**
- Modify: `extension-firefox/background.js`, `extension-chrome/background.js`
- Modify: `extension-firefox/popup/popup.{html,js}`, `extension-chrome/popup/popup.{html,js}`

**Interfaces:**
- Consumes: the four native actions from Task 6.
- Produces: no new interfaces.

Apply identical changes to both extensions, using `browser.` in
`extension-firefox/` and `chrome.` in `extension-chrome/`.

- [ ] **Step 1: Relay the four actions**

In each `background.js`, beside the existing `get_progress` handler:

```javascript
  if (message.action === "get_queue") {
    sendToNativeHost({ action: "get_queue" })
      .then(result => sendResponse(result))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  if (["pause_job", "resume_job", "remove_job"].includes(message.action)) {
    sendToNativeHost({ action: message.action, job_id: message.job_id })
      .then(result => sendResponse(result))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }
```

- [ ] **Step 2: Add the queue markup**

In each `popup.html`, after the `cancelBtn` button:

```html
  <div id="queueSection">
    <div class="queue-header">Queue <span id="queueCount"></span></div>
    <div id="queueList"></div>
  </div>
```

and before `</style>`:

```css
    #queueSection { margin-top: 12px; border-top: 1px solid #e0e0e0; padding-top: 10px; }
    .queue-header { font-size: 12px; color: #666; margin-bottom: 6px; }
    .queue-row { border: 1px solid #eee; border-radius: 4px; padding: 6px; margin-bottom: 6px; }
    .queue-title { font-size: 11px; color: #333; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .queue-meta { font-size: 10px; color: #888; margin-top: 2px; }
    .queue-bar-outer { height: 4px; background: #eee; border-radius: 2px; margin-top: 4px; }
    .queue-bar-inner { height: 4px; background: #4caf50; border-radius: 2px; width: 0; }
    .queue-actions { margin-top: 4px; display: flex; gap: 4px; }
    .queue-actions button { font-size: 10px; padding: 2px 6px; background: #757575; color: #fff; }
    .queue-empty { font-size: 11px; color: #999; }
```

- [ ] **Step 3: Render the queue**

Append to each `popup.js`, before the `// Event listeners` block:

```javascript
const STATUS_LABEL = {
  queued: "Queued", running: "Running", paused: "Paused",
  complete: "Done", error: "Failed", cancelled: "Cancelled",
};

async function refreshQueue() {
  let response;
  try {
    response = await browser.runtime.sendMessage({ action: "get_queue" });
  } catch (error) {
    return;
  }
  const list = document.getElementById("queueList");
  const count = document.getElementById("queueCount");
  if (!response || !response.success) return;

  const jobs = response.jobs || [];
  const pending = jobs.filter(j => j.status === "queued").length;
  count.textContent = pending ? `(${pending} waiting)` : "";

  if (!jobs.length) {
    list.innerHTML = '<div class="queue-empty">Nothing queued.</div>';
    return;
  }

  list.textContent = "";
  for (const job of jobs) {
    const progress = job.progress || {};
    const row = document.createElement("div");
    row.className = "queue-row";

    const title = document.createElement("div");
    title.className = "queue-title";
    title.textContent = job.title;
    row.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "queue-meta";
    meta.textContent = `${STATUS_LABEL[job.status] || job.status} - ` +
      `${job.genre}/${job.quality}` +
      (job.status === "running" && progress.message ? ` - ${progress.message}` : "") +
      (job.status === "error" && job.error ? ` - ${job.error}` : "");
    row.appendChild(meta);

    if (job.status === "running" || job.status === "paused") {
      const outer = document.createElement("div");
      outer.className = "queue-bar-outer";
      const inner = document.createElement("div");
      inner.className = "queue-bar-inner";
      inner.style.width = `${progress.percent || 0}%`;
      outer.appendChild(inner);
      row.appendChild(outer);
    }

    const actions = document.createElement("div");
    actions.className = "queue-actions";
    if (job.status === "running" || job.status === "queued") {
      actions.appendChild(queueButton("Pause", "pause_job", job.job_id));
    }
    if (job.status === "paused") {
      actions.appendChild(queueButton("Resume", "resume_job", job.job_id));
    }
    actions.appendChild(queueButton("Remove", "remove_job", job.job_id));
    row.appendChild(actions);

    list.appendChild(row);
  }
}

function queueButton(label, action, jobId) {
  const button = document.createElement("button");
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const result = await browser.runtime.sendMessage({ action, job_id: jobId });
      if (result && !result.success) {
        updateStatus(`Error: ${result.error}`, "error");
      }
    } catch (error) {
      updateStatus(`Error: ${error.message}`, "error");
    }
    await refreshQueue();
  });
  return button;
}
```

- [ ] **Step 4: Poll while work is outstanding**

Add beside the existing `loadSettings();` call at the bottom of each `popup.js`:

```javascript
refreshQueue();
setInterval(refreshQueue, 2000);
```

- [ ] **Step 5: Verify**

Run: `node --check` on all four modified extension files. Expected: no output.

Run: `npx --yes web-ext@latest lint --source-dir=extension-firefox --self-hosted`
Expected: 0 errors.

Load the extension, queue two songs from two YouTube tabs, and confirm the
popup lists both with the second showing `Queued`.

- [ ] **Step 6: Commit**

```bash
git add extension-firefox extension-chrome
git commit -m "Show and control the job queue in the extension popup"
```

---

### Task 9: Queue UI in the YouTube floating menu

**Files:**
- Modify: `extension-firefox/content.js`, `extension-chrome/content.js`

**Interfaces:**
- Consumes: the same four actions.
- Produces: no new interfaces.

- [ ] **Step 1: Add the queue container to the menu markup**

In `createMenu()`, inside `menuElement.innerHTML`, after the closing tag of
`<div id="centrifugue-progress-container">`:

```html
      <div id="centrifugue-queue" style="display: none;">
        <div class="centrifugue-section-title">Queue</div>
        <div id="centrifugue-queue-list"></div>
      </div>
```

- [ ] **Step 2: Add styles**

In the `styles.textContent` block, append:

```css
  #centrifugue-queue { margin-top: 10px; }
  .centrifugue-queue-row { border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; padding: 6px; margin-bottom: 6px; }
  .centrifugue-queue-title { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .centrifugue-queue-meta { font-size: 10px; opacity: 0.7; margin-top: 2px; }
  .centrifugue-queue-actions { margin-top: 4px; display: flex; gap: 4px; }
  .centrifugue-queue-actions button { font-size: 10px; padding: 2px 6px; cursor: pointer; }
```

- [ ] **Step 3: Render the queue**

Add to `content.js`:

```javascript
const CENTRIFUGUE_STATUS_LABEL = {
  queued: "Queued", running: "Running", paused: "Paused",
  complete: "Done", error: "Failed", cancelled: "Cancelled",
};

async function refreshQueuePanel() {
  const container = document.getElementById("centrifugue-queue");
  const list = document.getElementById("centrifugue-queue-list");
  if (!container || !list) return;

  let response;
  try {
    response = await browser.runtime.sendMessage({ action: "get_queue" });
  } catch (error) {
    return;
  }
  if (!response || !response.success) return;

  const jobs = response.jobs || [];
  container.style.display = jobs.length ? "block" : "none";
  list.textContent = "";

  for (const job of jobs) {
    const progress = job.progress || {};
    const row = document.createElement("div");
    row.className = "centrifugue-queue-row";

    const title = document.createElement("div");
    title.className = "centrifugue-queue-title";
    title.textContent = job.title;
    row.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "centrifugue-queue-meta";
    meta.textContent =
      `${CENTRIFUGUE_STATUS_LABEL[job.status] || job.status}` +
      (job.status === "running" && progress.percent != null
        ? ` - ${progress.percent}%` : "");
    row.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "centrifugue-queue-actions";
    if (job.status === "running" || job.status === "queued") {
      actions.appendChild(makeQueueButton("Pause", "pause_job", job.job_id));
    }
    if (job.status === "paused") {
      actions.appendChild(makeQueueButton("Resume", "resume_job", job.job_id));
    }
    actions.appendChild(makeQueueButton("Remove", "remove_job", job.job_id));
    row.appendChild(actions);

    list.appendChild(row);
  }
}

function makeQueueButton(label, action, jobId) {
  const button = document.createElement("button");
  button.textContent = label;
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    button.disabled = true;
    try {
      await browser.runtime.sendMessage({ action, job_id: jobId });
    } catch (error) {
      // A failed control action must not break the panel
    }
    await refreshQueuePanel();
  });
  return button;
}
```

`textContent` is used rather than `innerHTML` throughout: video titles are
untrusted input and `web-ext lint` already flags `innerHTML` assignment in
this file.

- [ ] **Step 4: Refresh the panel with the existing poll**

Inside `showProgressInMenu()`, add as the last statement:

```javascript
  refreshQueuePanel();
```

and call `refreshQueuePanel()` once at the end of `createMenu()`.

- [ ] **Step 5: Verify**

Run: `node --check extension-firefox/content.js extension-chrome/content.js`
Expected: no output.

Run: `npx --yes web-ext@latest lint --source-dir=extension-firefox --self-hosted`
Expected: 0 errors.

On a YouTube page, queue two songs and confirm both rows appear in the
floating menu with working Pause/Resume/Remove buttons.

- [ ] **Step 6: Commit**

```bash
git add extension-firefox/content.js extension-chrome/content.js
git commit -m "Show and control the job queue in the YouTube menu"
```

---

### Task 10: README documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the queue**

Add a **Queue** section under Features describing: songs are appended and
convert one at a time; pausing the running job freezes it and starts the next;
resuming continues from where it stopped; the queue keeps running with the
browser closed.

- [ ] **Step 2: Document the config key**

Add to the configuration table:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_paused_jobs` | int | `2` | Most conversions that may be paused at once. A paused job stays in memory (including GPU memory), so this is capped deliberately. `0` disables pausing. |

- [ ] **Step 3: Add a troubleshooting entry**

```markdown
### A paused job is using memory

Pausing freezes the process rather than stopping it, so progress is kept but
RAM and GPU memory stay allocated. That is why `max_paused_jobs` defaults to
2. Remove a paused job instead of pausing it if you need the memory back.
Paused jobs do not survive a reboot.
```

- [ ] **Step 4: Update the architecture tree**

Add `centrifugue_queue.py # Job queue, scheduler, pause/resume` under
`native-host/`.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "Document the job queue and pause behaviour"
```

---

## Manual Integration Test

- [ ] Queue three songs from three YouTube tabs; confirm they convert one at a time, in order.
- [ ] Pause the running job; confirm the next starts and the paused one keeps its percentage.
- [ ] Resume the paused job; confirm it continues (does not restart) once the slot frees.
- [ ] Remove a queued job; confirm it disappears and nothing else is disturbed.
- [ ] Close the browser mid-queue; confirm the remaining jobs still convert.
- [ ] Pause three jobs with `max_paused_jobs: 2`; confirm the third is refused with a clear message.
