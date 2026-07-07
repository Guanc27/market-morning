"""Background AI jobs with progress tracking."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Coroutine

_lock = threading.Lock()

PORTFOLIO_JOB: dict[str, Any] = {
    "running": False,
    "progress": 0,
    "message": "Idle",
    "done": False,
    "error": None,
    "result": None,
    "started_at": 0.0,
}

PICKS_JOB: dict[str, Any] = {
    "running": False,
    "progress": 0,
    "message": "Idle",
    "done": False,
    "error": None,
    "result": None,
    "started_at": 0.0,
}

EXPLORE_JOB: dict[str, Any] = {
    "running": False,
    "progress": 0,
    "message": "Idle",
    "done": False,
    "error": None,
    "result": None,
    "started_at": 0.0,
}

BRIEF_AI_JOB: dict[str, Any] = {
    "running": False,
    "progress": 0,
    "message": "Idle",
    "done": False,
    "error": None,
    "result": None,
    "started_at": 0.0,
}


def update_job(job: dict[str, Any], **fields: Any) -> None:
    """Thread-safe mutation of a job's fields (guarded by the shared lock)."""
    with _lock:
        job.update(**fields)


def snapshot_job(job: dict[str, Any]) -> dict[str, Any]:
    """Thread-safe shallow copy of a job for read-only serialization."""
    with _lock:
        return dict(job)


def _set_progress(job: dict[str, Any], progress: int, message: str) -> None:
    with _lock:
        job["progress"] = progress
        job["message"] = message


def reset_brief_ai_job() -> None:
    update_job(
        BRIEF_AI_JOB,
        running=True,
        done=False,
        progress=0,
        message="Starting brief…",
        error=None,
        result=None,
    )


def finish_brief_ai_job(message: str = "Brief ready", result: dict[str, Any] | None = None) -> None:
    update_job(
        BRIEF_AI_JOB,
        running=False,
        done=True,
        progress=100,
        message=message,
        result=result,
    )


def set_portfolio_progress(progress: int, message: str) -> None:
    _set_progress(PORTFOLIO_JOB, progress, message)


def set_brief_ai_progress(progress: int, message: str) -> None:
    _set_progress(BRIEF_AI_JOB, progress, message)


def set_picks_progress(progress: int, message: str) -> None:
    _set_progress(PICKS_JOB, progress, message)


def set_explore_progress(progress: int, message: str) -> None:
    _set_progress(EXPLORE_JOB, progress, message)


def _job_is_stale(job: dict[str, Any], max_seconds: float = 600.0) -> bool:
    import time
    started = job.get("started_at") or 0.0
    return bool(job.get("running") and started and (time.time() - started) > max_seconds)


def clear_stale_job_if_needed(job: dict[str, Any], max_seconds: float = 600.0) -> bool:
    """Mark a long-running job as timed out. Returns True if the job was cleared."""
    with _lock:
        if _job_is_stale(job, max_seconds):
            job.update(
                running=False,
                done=True,
                progress=100,
                message="Timed out",
                error="Job timed out after 10 minutes — tap Retry or run the action again.",
                result=None,
            )
            return True
    return False


def start_async_job(
    job: dict[str, Any],
    coro_factory: Callable[[], Coroutine[Any, Any, Any]],
) -> tuple[bool, str | None]:
    import time
    with _lock:
        if job.get("running"):
            if _job_is_stale(job):
                job.update(running=False, done=True, progress=100, message="Timed out", error="Job timed out")
            else:
                return False, "already_running"
        job.update(
            running=True,
            done=False,
            progress=5,
            message="Starting…",
            error=None,
            result=None,
            started_at=time.time(),
        )

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(coro_factory())
            update_job(job, running=False, done=True, progress=100, message="Complete", result=result)
        except Exception as e:
            update_job(job, running=False, done=True, progress=100, message="Failed", error=str(e))
        finally:
            loop.close()

    threading.Thread(target=_run, daemon=True).start()
    return True, None
