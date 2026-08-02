# Job Queue with Pause/Resume

**Date:** 2026-08-01
**Status:** Approved
**Depends on:** `specs/configurable-stem-output/spec.md` (config file, output layout)

## Problem

Centrifugue processes exactly one song at a time and offers no control over a
run once it starts:

- `start_stems_job()` refuses a second job outright: *"A job is already
  running. Please wait for it to complete or cancel it."* Queueing a few songs
  means babysitting the browser and starting each one by hand.
- State is single-job by construction. `~/.centrifugue_job.json` holds one
  record and `~/.centrifugue_progress.json` one progress blob, so there is
  nowhere to represent a second job.
- The only control is `cancel_job`, which destroys the work. An Ultra run nine
  minutes in cannot be held while the machine is needed for something else.

## Goals

- Queue any number of songs; exactly one converts at a time
- Pause and resume an individual conversion without losing progress
- Pausing the running job lets the queue advance to the next song
- The queue keeps moving when the browser is closed
- Full queue visibility and control in both the popup and the YouTube menu

## Non-Goals (out of scope)

- Reordering the queue (append and remove only)
- Concurrent conversions — the GPU is the bottleneck, one at a time stands
- Surviving a reboot: a frozen process dies with the machine
- Changes to separation quality, models, naming, or `info.json`

## Pause Semantics

Pause sends `SIGSTOP` to the worker's process group; resume sends `SIGCONT`.
The worker is already spawned with `start_new_session=True`, so its PID leads
the group and the signal reaches yt-dlp and Demucs children too — the same
mechanism `cancel_job` uses today with `SIGTERM`.

Freezing keeps every byte of progress: a run nine minutes in resumes nine
minutes in. The cost is that a frozen process keeps holding its RAM and MPS
allocation.

**Frozen-memory guard.** Each paused Ultra job holds several GB. Pausing is
refused, with a clear message, once `max_paused_jobs` (default `2`) jobs are
already frozen. Without this, pausing repeatedly exhausts unified memory and
wedges the machine.

## State Model

### Queue file — `~/.centrifugue_queue.json`

```json
{
  "schema_version": 1,
  "jobs": [
    {
      "job_id": "job_1785617843",
      "url": "https://www.youtube.com/watch?v=...",
      "title": "BLP Kosher - Cheap Gas",
      "quality": "ultra",
      "genre": "rock",
      "status": "running",
      "pid": 11522,
      "temp_dir": "/var/folders/.../centrifugue_z8jzm1vq",
      "added_at": 1785617843.8,
      "started_at": 1785617845.1,
      "finished_at": null,
      "error": null
    }
  ]
}
```

| Status | Meaning | Has PID |
|--------|---------|---------|
| `queued` | Waiting for the slot. Either never started, or paused-then-resumed. | maybe |
| `running` | Actively converting. | yes |
| `paused` | Frozen with `SIGSTOP`; still holds memory. | yes |
| `complete` | Finished successfully. | no |
| `error` | Failed; `error` holds the message. | no |
| `cancelled` | Removed by the user. | no |

A `queued` job **with** a PID is a resumed job awaiting its slot — the
scheduler continues it rather than spawning a new worker. This distinction is
what makes resume free rather than a restart.

### Progress files — `~/.centrifugue/progress/<job_id>.json`

Per-job, same shape as today's progress blob. Progress is written roughly once
a second by the worker; keeping it out of the queue file means each file has
exactly one writer and workers can never clobber a concurrent pause or enqueue.

Terminal state is recorded in the queue by the worker before it exits, so a
missing progress file is never load-bearing.

## Scheduler

`tick()` is the only code that starts work. Under an `fcntl.flock` on the
queue file it performs one read-modify-write:

1. **Reap.** For every `running` or `paused` job, verify the PID is alive
   (`os.kill(pid, 0)`). A dead PID becomes `complete` if its progress file
   reports stage `complete`, otherwise `error`.
2. **Schedule.** If no job is `running`, take the first `queued` job in order:
   - PID present and alive → `SIGCONT` the group, status `running`
   - otherwise → spawn a detached worker, record the new PID, status `running`
3. **Write** the queue and release the lock.

**Callers:** the host on enqueue, pause, resume, remove, cancel, and
`get_queue`; and the worker as its final act after publishing output. The
worker call is what keeps the queue advancing with the browser closed, which
the existing detached-worker design already relies on.

The lock is load-bearing: a worker finishing at the same instant the user hits
pause would otherwise both schedule the next job, producing two concurrent
Demucs runs contending for the GPU.

## Operations

| Action | Effect |
|--------|--------|
| `download_stems` | Appends a job as `queued`, then `tick()`. Never refuses for being busy. |
| `get_queue` | `tick()`, then return all jobs with their progress merged in. |
| `pause_job(job_id)` | `SIGSTOP` the group → `paused` → `tick()` (next song starts). Refused past `max_paused_jobs`. |
| `resume_job(job_id)` | `paused` → `queued`, PID retained. `tick()` continues it when the slot frees. |
| `remove_job(job_id)` | `SIGKILL` the group if it has one, delete temp dir, drop the job, `tick()`. |
| `cancel_job` | Unchanged in name: removes the currently running job. |
| `get_progress` | Retained, returning the running job's progress, so a stale popup keeps working. |

Pausing a `queued` job that has never started is also allowed: it simply holds
its place and is skipped by the scheduler until resumed. No signal is sent
because there is no process.

## Configuration

Adds one key to `~/.centrifugue/config.json`:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_paused_jobs` | int | `2` | Most jobs that may be frozen at once. Frozen jobs hold RAM and GPU memory. `0` disables pausing. |

## Migration

On first load, if no queue file exists but a legacy `~/.centrifugue_job.json`
does:

- PID alive → import as a `running` job so an in-flight conversion is adopted
  rather than orphaned
- PID dead → ignore it

The legacy files are left on disk untouched; nothing reads them afterwards.

## UI

Both the popup and the YouTube floating menu render the same list. Each row
shows the title, a status badge, a progress bar for the running job, and
per-row **Pause/Resume** and **Remove** controls. Above the list: a count of
queued jobs.

Both surfaces poll `get_queue` while any job is `running` or `paused`, and
stop polling when everything is terminal. `content.js` and `popup.js` share no
code today, and each exists twice (Firefox and Chrome), so the same rendering
logic lands in four files. Keeping the queue-row markup identical across them
is a requirement, not a nicety.

## Error Handling

- A signal to a dead PID (`ProcessLookupError`) is not an error: the job is
  reaped and the queue moves on.
- A corrupt or unreadable queue file is replaced with an empty queue and
  logged, never fatal — the same posture as the config loader.
- A worker that dies without writing terminal state is reaped as `error` with
  the last progress message retained.
- Pausing beyond `max_paused_jobs` returns `success: false` with a message
  naming the limit.

## Testing

Unit (pure logic, injected process control — no real workers or models):

- Scheduler: empty queue; one queued job spawns; queued-with-PID continues
  instead of spawning; nothing starts while one is `running`; dead running PID
  reaped to `complete` vs `error` by progress stage.
- Pause: running → `paused` and the next queued job starts; refused at the cap;
  pausing a never-started job sends no signal.
- Resume: `paused` → `queued` with PID kept; continues when the slot frees.
- Remove: running job killed and temp cleaned; queued job simply dropped.
- Migration: live legacy PID imported as running; dead legacy PID ignored.
- Queue file: corrupt JSON yields an empty queue rather than raising.

Integration (manual, real jobs):

- Enqueue three songs; confirm they convert one at a time in order.
- Pause the running job; confirm the next starts and the paused one keeps its
  percentage on resume.
- Close the browser mid-queue; confirm the remaining jobs still convert.
