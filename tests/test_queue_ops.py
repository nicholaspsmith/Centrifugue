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


# --- Terminal jobs must not accumulate forever ------------------------------

def test_clear_finished_removes_terminal_jobs_only():
    _seed(_job("a", status="complete"), _job("b", status="running", pid=1),
          _job("c", status="error"), _job("d"))
    result = q.clear_finished()
    assert result["success"] is True
    assert result["removed"] == 2
    assert sorted(j["job_id"] for j in q.load_queue()["jobs"]) == ["b", "d"]


def test_clear_finished_on_empty_queue_is_fine():
    _seed()
    assert q.clear_finished()["removed"] == 0


def test_prune_drops_terminal_jobs_older_than_the_cutoff():
    import time as _t
    old = _job("old", status="complete"); old["finished_at"] = _t.time() - 90000
    fresh = _job("fresh", status="complete"); fresh["finished_at"] = _t.time()
    queue = {"schema_version": 1, "jobs": [old, fresh]}
    q.prune(queue, max_age_seconds=86400)
    assert [j["job_id"] for j in queue["jobs"]] == ["fresh"]


def test_prune_never_drops_active_jobs():
    import time as _t
    stale_running = _job("r", status="running", pid=1)
    stale_running["added_at"] = _t.time() - 900000
    queue = {"schema_version": 1, "jobs": [stale_running]}
    q.prune(queue, max_age_seconds=86400)
    assert [j["job_id"] for j in queue["jobs"]] == ["r"]


def test_prune_keeps_terminal_jobs_without_a_finish_time():
    orphan = _job("o", status="error")
    queue = {"schema_version": 1, "jobs": [orphan]}
    q.prune(queue, max_age_seconds=86400)
    assert [j["job_id"] for j in queue["jobs"]] == ["o"]
