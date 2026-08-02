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
    statuses = {j["job_id"]: j["status"] for j in result["jobs"]}
    assert statuses["a"] == "error"
    assert statuses["b"] == "running"
    assert rec.spawned == ["b"]
