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
    assert [j["job_id"] for j in q.load_queue()["jobs"]] == ["job_1"]


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
