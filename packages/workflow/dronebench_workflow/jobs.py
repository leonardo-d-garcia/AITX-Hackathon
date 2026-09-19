"""The bounded job queue (architecture sections 4 and 9).

Section 4: "Long native jobs run in subprocesses behind a bounded queue; never inside an HTTP
request/event-loop thread. Limit CAD and VSPAERO concurrency to one each initially."

This implementation uses threads rather than subprocesses, which is the right call while the only
workers are B's in-process reference implementations - there is no native library to isolate yet,
and a subprocess boundary with nothing to protect against is cost without benefit. The *interface*
is the subprocess-shaped one: every job gets a unique working directory, is cancellable, and
communicates through artifacts rather than shared objects. When Team C's OpenVSP worker arrives it
drops in behind :class:`JobQueue.submit` without the callers changing, which is exactly the "JSON
worker boundary" section 12 asks for.

Cache keys cover revision content, mission, solver version and settings, model tier, and the
relevant evidence and catalog snapshot hashes. A hit records ``reused_job_id`` so the UI can show
the reused run instead of pretending work happened.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from dronebench_contracts import (
    DroneBenchError,
    JobKind,
    JobRecord,
    MAX_QUEUED_NATIVE_ANALYSES,
    content_hash,
)

from .repository import Repository
from .store import ArtifactStore

#: Concurrency caps per job kind. CAD and the native analysis tier are one at a time.
CONCURRENCY: dict[str, int] = {
    "import": 1,
    "confirm": 1,
    "preview": 1,   # drives the CAD worker
    "evaluate": 1,  # drives the analysis worker
    "recommend": 2,
    "simulate": 2,
    "export": 1,
}


class JobCancelled(RuntimeError):
    """Raised inside a worker when the job was cancelled."""


@dataclass
class _Running:
    future: Future
    cancel: threading.Event


class JobQueue:
    """Bounded, cancellable, per-kind serialised."""

    def __init__(self, repository: Repository, store: ArtifactStore) -> None:
        self.repository = repository
        self.store = store
        self._pools: dict[str, ThreadPoolExecutor] = {
            kind: ThreadPoolExecutor(max_workers=limit, thread_name_prefix=f"db-{kind}")
            for kind, limit in CONCURRENCY.items()
        }
        self._running: dict[str, _Running] = {}
        self._lock = threading.Lock()
        self._counter = 0

    # -- keys ----------------------------------------------------------------------------------

    @staticmethod
    def cache_key(
        *,
        kind: JobKind,
        revision_content_hash: str,
        mission_hash: str | None,
        solver_version: str,
        solver_settings: dict[str, Any] | None = None,
        model_tier: str = "none",
        snapshot_hashes: dict[str, str] | None = None,
    ) -> str:
        return content_hash(
            {
                "kind": kind,
                "revision": revision_content_hash,
                "mission": mission_hash,
                "solver_version": solver_version,
                "solver_settings": solver_settings or {},
                "model_tier": model_tier,
                "snapshots": snapshot_hashes or {},
            }
        )

    def _next_job_id(self, kind: JobKind) -> str:
        with self._lock:
            self._counter += 1
            return f"job_{kind}-{self._counter:06d}"

    # -- submission ------------------------------------------------------------------------------

    def submit(
        self,
        *,
        kind: JobKind,
        design_id: str,
        revision_id: str | None,
        cache_key: str,
        work: Callable[[str, threading.Event], list[str]],
        allow_cache: bool = True,
    ) -> JobRecord:
        """Enqueue work. ``work(work_dir, cancel_event)`` returns the artifact ids it produced."""
        if allow_cache:
            cached = self.repository.find_cached_job(cache_key)
            if cached is not None:
                job = JobRecord(
                    job_id=self._next_job_id(kind),
                    kind=kind,
                    status="succeeded",
                    design_id=design_id,
                    revision_id=revision_id,
                    cache_key=cache_key,
                    work_dir="",
                    artifact_ids=list(cached.artifact_ids),
                    cache_hit=True,
                    reused_job_id=cached.job_id,
                    progress_note=f"reused run {cached.job_id}",
                )
                self.repository.put_job(job)
                self.repository.append_event(
                    design_id=design_id,
                    kind="job_succeeded",
                    tool_name=f"jobs.{kind}",
                    revision_id=revision_id,
                    job_id=job.job_id,
                    artifact_ids=job.artifact_ids,
                    inputs_summary={"cache_hit": "true", "reused_job_id": cached.job_id},
                )
                return job

        job_id = self._next_job_id(kind)
        work_dir = str(self.store.job_dir(job_id))
        job = JobRecord(
            job_id=job_id,
            kind=kind,
            status="queued",
            design_id=design_id,
            revision_id=revision_id,
            cache_key=cache_key,
            work_dir=work_dir,
        )
        self.repository.put_job(job)
        self.repository.append_event(
            design_id=design_id,
            kind="job_queued",
            tool_name=f"jobs.{kind}",
            revision_id=revision_id,
            job_id=job_id,
        )

        cancel = threading.Event()
        future = self._pools[kind].submit(self._run, job, work, work_dir, cancel)
        with self._lock:
            self._running[job_id] = _Running(future=future, cancel=cancel)
        return job

    def _run(
        self,
        job: JobRecord,
        work: Callable[[str, threading.Event], list[str]],
        work_dir: str,
        cancel: threading.Event,
    ) -> None:
        started = time.perf_counter()
        self.repository.put_job(job.model_copy(update={"status": "running"}))
        self.repository.append_event(
            design_id=job.design_id,
            kind="job_started",
            tool_name=f"jobs.{job.kind}",
            revision_id=job.revision_id,
            job_id=job.job_id,
            status="in_progress",
        )

        try:
            artifact_ids = work(work_dir, cancel)
        except JobCancelled:
            self.repository.put_job(
                job.model_copy(
                    update={
                        "status": "cancelled",
                        "elapsed_s": time.perf_counter() - started,
                        "progress_note": "cancelled",
                    }
                )
            )
            self.repository.append_event(
                design_id=job.design_id,
                kind="job_cancelled",
                tool_name=f"jobs.{job.kind}",
                revision_id=job.revision_id,
                job_id=job.job_id,
                elapsed_s=time.perf_counter() - started,
            )
            return
        except DroneBenchError as exc:
            self._fail(job, started, exc.envelope.code, exc.envelope.message)
            return
        except Exception as exc:  # noqa: BLE001 - a worker crash must not take the queue down
            self._fail(job, started, "INTERNAL", str(exc))
            return
        finally:
            with self._lock:
                self._running.pop(job.job_id, None)

        elapsed = time.perf_counter() - started
        self.repository.put_job(
            job.model_copy(
                update={
                    "status": "succeeded",
                    "artifact_ids": artifact_ids,
                    "elapsed_s": elapsed,
                }
            )
        )
        self.repository.append_event(
            design_id=job.design_id,
            kind="job_succeeded",
            tool_name=f"jobs.{job.kind}",
            revision_id=job.revision_id,
            job_id=job.job_id,
            artifact_ids=artifact_ids,
            elapsed_s=elapsed,
        )

    def _fail(self, job: JobRecord, started: float, code: str, message: str) -> None:
        """A failed worker leaves the design untouched; only the job record records the failure."""
        elapsed = time.perf_counter() - started
        self.repository.put_job(
            job.model_copy(
                update={
                    "status": "failed",
                    "error_code": code,
                    "error_message": message[:500],
                    "elapsed_s": elapsed,
                }
            )
        )
        self.repository.append_event(
            design_id=job.design_id,
            kind="job_failed",
            tool_name=f"jobs.{job.kind}",
            revision_id=job.revision_id,
            job_id=job.job_id,
            status="error",
            error_code=code,
            elapsed_s=elapsed,
            inputs_summary={"message": message[:200]},
        )

    # -- control ----------------------------------------------------------------------------------

    def cancel(self, job_id: str) -> bool:
        """Request cancellation. Returns False when the job has already finished."""
        with self._lock:
            running = self._running.get(job_id)
        if running is None:
            return False
        running.cancel.set()
        running.future.cancel()
        return True

    def wait(self, job_id: str, timeout: float = 30.0) -> JobRecord:
        """Block until a job reaches a terminal state. Used by the CLI and the tests."""
        with self._lock:
            running = self._running.get(job_id)
        if running is not None:
            try:
                running.future.result(timeout=timeout)
            except Exception:
                # The failure is already recorded on the job record; the caller reads it there.
                pass
        return self.repository.get_job(job_id)

    def shutdown(self) -> None:
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)

    @property
    def native_analysis_slots(self) -> int:
        """Section 7: at most three expensive native analyses queued at a time."""
        return MAX_QUEUED_NATIVE_ANALYSES
