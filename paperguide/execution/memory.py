"""Thread-pool-backed in-memory execution of PaperGuide application requests."""

import inspect
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from paperguide.application import (
    ResearchApplicationService,
    ResearchExecutionError,
    ResearchRequest,
    ResearchTask,
    ResearchTaskStatus,
    TaskNotFoundError,
    TaskStoreProtocol,
)
from paperguide.orchestration.errors import sanitize_message
from paperguide.runtime_context import (
    CancellationTokenProtocol,
    ExecutionAbortedError,
    ExecutionContext,
    execution_scope,
)

from .exceptions import TaskSubmissionError
from .models import TaskHandle


class InMemoryTaskExecutor:
    """Run injected application-service requests on a bounded local thread pool."""

    def __init__(
        self,
        application_service: ResearchApplicationService,
        task_store: TaskStoreProtocol,
        *,
        max_workers: int = 4,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least one")
        if getattr(application_service, "task_store", None) is not task_store:
            raise ValueError(
                "executor and application service must share the same TaskStore"
            )
        self.application_service = application_service
        self.task_store = task_store
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="paperguide-task",
        )
        self._futures: dict[UUID, Future[None]] = {}
        self._execution_ids: set[str] = set()
        self._lock = RLock()
        self._shutdown = False

    def submit(self, request: ResearchRequest) -> TaskHandle:
        """Persist a queued task and schedule an isolated request copy."""

        safe_request = ResearchRequest.model_validate(request.model_dump())
        created = self.task_store.save(
            ResearchTask(
                run_id=uuid4(),
                question=safe_request.question,
                status=ResearchTaskStatus.CREATED,
            )
        )
        queued = self.task_store.update(
            created.task_id,
            status=ResearchTaskStatus.QUEUED,
        )
        return self.submit_existing(queued.task_id, safe_request)

    def submit_existing(
        self,
        task_id: UUID,
        request: ResearchRequest,
        *,
        fencing_token: int | None = None,
        execution_id: str | None = None,
        cancellation_token: CancellationTokenProtocol | None = None,
    ) -> TaskHandle:
        """Schedule an existing queued task, as used by a persistent host."""

        if (fencing_token is None) != (execution_id is None):
            raise ValueError(
                "fencing_token and execution_id must be provided together"
            )
        safe_request = ResearchRequest.model_validate(request.model_dump())
        with self._lock:
            if execution_id is not None and execution_id in self._execution_ids:
                existing = self.task_store.get(task_id)
                return TaskHandle(
                    task_id=task_id,
                    status=existing.status,
                    created_at=existing.created_at,
                )
            queued = self.task_store.get(task_id)
            if queued.status is not ResearchTaskStatus.QUEUED:
                raise TaskSubmissionError("existing task is not queued")
            if self._shutdown:
                self._mark_failed(task_id, TaskSubmissionError)
                raise TaskSubmissionError("task executor has been shut down")
            try:
                if execution_id is not None:
                    self._execution_ids.add(execution_id)
                future = self._pool.submit(
                    self._execute,
                    task_id,
                    deepcopy(safe_request),
                    fencing_token,
                    execution_id,
                    cancellation_token,
                )
            except RuntimeError as error:
                if execution_id is not None:
                    self._execution_ids.discard(execution_id)
                self._mark_failed(
                    task_id,
                    type(error),
                    fencing_token=fencing_token,
                    execution_id=execution_id,
                )
                raise TaskSubmissionError("task could not be queued") from error
            self._futures[task_id] = future
            future.add_done_callback(
                lambda completed, task_id=task_id: self._forget_future(
                    task_id, completed
                )
            )
        return TaskHandle(
            task_id=task_id,
            status=ResearchTaskStatus.QUEUED,
            created_at=queued.created_at,
        )

    def get_status(self, task_id: UUID) -> ResearchTask:
        """Delegate status lookup to the shared injected TaskStore."""

        return self.task_store.get(task_id)

    def cancel(self, task_id: UUID) -> ResearchTask:
        """Cancel queued work or mark running work as cancellation-requested."""

        with self._lock:
            task = self.task_store.get(task_id)
            if task.status is ResearchTaskStatus.QUEUED:
                future = self._futures.get(task_id)
                if future is not None and future.cancel():
                    return self.task_store.update(
                        task_id,
                        status=ResearchTaskStatus.CANCELLED,
                        artifact=None,
                        error=None,
                    )
                return self.task_store.update(
                    task_id,
                    status=ResearchTaskStatus.CANCEL_REQUESTED,
                    artifact=None,
                    error=None,
                )
            if task.status is ResearchTaskStatus.RUNNING:
                return self.task_store.update(
                    task_id,
                    status=ResearchTaskStatus.CANCEL_REQUESTED,
                    artifact=None,
                    error=None,
                )
            return task

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        """Stop accepting work and shut down the owned thread pool."""

        with self._lock:
            self._shutdown = True
        self._pool.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __enter__(self) -> "InMemoryTaskExecutor":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.shutdown()

    def _execute(
        self,
        task_id: UUID,
        request: ResearchRequest,
        fencing_token: int | None,
        execution_id: str | None,
        cancellation_token: CancellationTokenProtocol | None,
    ) -> None:
        context = (
            ExecutionContext(task_id, execution_id, cancellation_token)
            if execution_id is not None and cancellation_token is not None
            else None
        )
        try:
            with execution_scope(context):
                if cancellation_token is not None:
                    cancellation_token.raise_if_cancelled()
                with self._lock:
                    current = self.task_store.get(task_id)
                    if current.status is ResearchTaskStatus.CANCELLED:
                        return
                    if current.status is ResearchTaskStatus.QUEUED:
                        claimed = self._update_task(
                            task_id,
                            fencing_token,
                            execution_id,
                            status=ResearchTaskStatus.RUNNING,
                        )
                        if claimed is None:
                            return
                run_signature = inspect.signature(self.application_service.run)
                if "task_id" in run_signature.parameters:
                    result = self.application_service.run(
                        request.model_copy(deep=True), task_id=task_id
                    )
                else:
                    # Compatibility for injected legacy/fake application services.
                    result = self.application_service.run(request.model_copy(deep=True))
                if cancellation_token is not None:
                    cancellation_token.raise_if_cancelled()
                application_task = result.task
                with self._lock:
                    if application_task.status is ResearchTaskStatus.COMPLETED:
                        self._update_task(
                            task_id,
                            fencing_token,
                            execution_id,
                            status=ResearchTaskStatus.COMPLETED,
                            artifact=application_task.artifact,
                            error=None,
                        )
                    elif application_task.status is ResearchTaskStatus.HUMAN_REVIEW:
                        self._update_task(
                            task_id,
                            fencing_token,
                            execution_id,
                            status=ResearchTaskStatus.HUMAN_REVIEW,
                            artifact=None,
                            error=None,
                        )
                    else:
                        # The application service may have already stored a safe
                        # terminal quality-rejection reason. Preserve it instead
                        # of replacing it with a worker implementation detail.
                        if self.task_store.get(task_id).status is not ResearchTaskStatus.FAILED:
                            self._mark_failed(
                                task_id,
                                type(application_task.status),
                                fencing_token=fencing_token,
                                execution_id=execution_id,
                            )
                if application_task.task_id != task_id:
                    self.task_store.delete(application_task.task_id)
        except ExecutionAbortedError:
            return
        except ResearchExecutionError as error:
            detail = self._consume_application_failure(task_id, error)
            self._mark_failed(
                task_id,
                type(error),
                detail=detail,
                fencing_token=fencing_token,
                execution_id=execution_id,
            )
        except Exception as error:
            self._mark_failed(
                task_id,
                type(error),
                fencing_token=fencing_token,
                execution_id=execution_id,
            )

    def _mark_failed(
        self,
        task_id: UUID,
        error_type: type[BaseException],
        *,
        detail: str | None = None,
        fencing_token: int | None = None,
        execution_id: str | None = None,
    ) -> None:
        message = f"worker execution failed ({error_type.__name__})"
        if detail:
            message = f"{message}: {sanitize_message(detail)}"
        with self._lock:
            self._update_task(
                task_id,
                fencing_token,
                execution_id,
                status=ResearchTaskStatus.FAILED,
                artifact=None,
                error=message,
            )

    def _consume_application_failure(
        self,
        outer_task_id: UUID,
        error: ResearchExecutionError,
    ) -> str | None:
        """Return the safe inner failure and remove its duplicate task record."""

        if error.task_id == outer_task_id:
            return None
        try:
            inner_task = self.task_store.get(error.task_id)
        except TaskNotFoundError:
            return None
        detail = inner_task.error
        self.task_store.delete(error.task_id)
        return detail

    def _update_task(
        self,
        task_id: UUID,
        fencing_token: int | None,
        execution_id: str | None,
        **changes: object,
    ) -> ResearchTask | None:
        if fencing_token is None or execution_id is None:
            return self.task_store.update(task_id, **changes)
        update_fenced = getattr(self.task_store, "update_fenced", None)
        if update_fenced is None:
            raise TaskSubmissionError(
                "task store does not support fenced execution"
            )
        return update_fenced(
            task_id,
            fencing_token,
            execution_id,
            **changes,
        )

    def _forget_future(self, task_id: UUID, completed: Future[None]) -> None:
        del completed
        with self._lock:
            self._futures.pop(task_id, None)
