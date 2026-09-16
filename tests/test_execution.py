"""Tests for the thread-pool-backed PaperGuide task execution runtime."""

import hashlib
import threading
import time
import unittest
from types import SimpleNamespace
from uuid import uuid4

from paperguide.application import (
    InMemoryTaskStore,
    ResearchExecutionError,
    ResearchRequest,
    ResearchTask,
    ResearchTaskStatus,
    TaskNotFoundError,
)
from paperguide.execution import (
    InMemoryTaskExecutor,
    TaskExecutorProtocol,
)
from paperguide.export import ArtifactMetadata, ExportFormat


def make_artifact(name: str = "report.md") -> ArtifactMetadata:
    """Create deterministic artifact metadata for a successful fake worker."""

    payload = name.encode("utf-8")
    return ArtifactMetadata(
        format=ExportFormat.MARKDOWN,
        file_path=name,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


class FakeApplicationService:
    """Application-service boundary that can complete, block, or fail."""

    def __init__(self, task_store, *, error=None, release=None):
        self.task_store = task_store
        self.error = error
        self.release = release
        self.started = threading.Event()
        self.requests = []
        self._lock = threading.Lock()

    def run(self, request):
        with self._lock:
            self.requests.append(request.model_copy(deep=True))
        self.started.set()
        if self.release is not None:
            self.release.wait(timeout=2)
        if self.error is not None:
            raise self.error
        task = ResearchTask(
            run_id=uuid4(),
            question=request.question,
            status=ResearchTaskStatus.COMPLETED,
            artifact=make_artifact(f"{len(self.requests)}-report.md"),
        )
        return SimpleNamespace(task=task)


def wait_for_status(executor, task_id, terminal=None):
    """Poll one in-memory task with a short deterministic deadline."""

    terminal = terminal or {
        ResearchTaskStatus.COMPLETED,
        ResearchTaskStatus.FAILED,
        ResearchTaskStatus.HUMAN_REVIEW,
    }
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        task = executor.get_status(task_id)
        if task.status in terminal:
            return task
        time.sleep(0.005)
    raise AssertionError("background task did not reach the expected state")


class ExecutionTests(unittest.TestCase):
    """Verify submission, lifecycle, isolation, safety, and dependency reuse."""

    def test_submit_returns_queued_handle(self) -> None:
        store = InMemoryTaskStore()
        release = threading.Event()
        service = FakeApplicationService(store, release=release)
        executor = InMemoryTaskExecutor(service, store, max_workers=1)
        try:
            handle = executor.submit(ResearchRequest(question="Analyze SLAM"))

            self.assertEqual(handle.status, ResearchTaskStatus.QUEUED)
            self.assertIsNotNone(handle.task_id)
            self.assertTrue(service.started.wait(timeout=1))
            self.assertIn(
                executor.get_status(handle.task_id).status,
                (ResearchTaskStatus.QUEUED, ResearchTaskStatus.RUNNING),
            )
        finally:
            release.set()
            executor.shutdown()

    def test_worker_execution_completes(self) -> None:
        store = InMemoryTaskStore()
        service = FakeApplicationService(store)
        with InMemoryTaskExecutor(service, store) as executor:
            handle = executor.submit(ResearchRequest(question="Analyze YOLO"))
            task = wait_for_status(executor, handle.task_id)

        self.assertEqual(task.status, ResearchTaskStatus.COMPLETED)
        self.assertIsNotNone(task.artifact)
        self.assertIsNone(task.error)

    def test_completed_inner_task_is_removed_after_result_transfer(self) -> None:
        class PersistingApplicationService(FakeApplicationService):
            def run(self, request):
                inner = self.task_store.save(
                    ResearchTask(
                        run_id=uuid4(),
                        question=request.question,
                        status=ResearchTaskStatus.COMPLETED,
                        artifact=make_artifact("inner-report.md"),
                    )
                )
                return SimpleNamespace(task=inner)

        store = InMemoryTaskStore()
        service = PersistingApplicationService(store)
        with InMemoryTaskExecutor(service, store) as executor:
            handle = executor.submit(ResearchRequest(question="Question"))
            task = wait_for_status(executor, handle.task_id)

        self.assertEqual(task.status, ResearchTaskStatus.COMPLETED)
        self.assertEqual([item.task_id for item in store.list()], [handle.task_id])

    def test_worker_failure_is_safely_recorded(self) -> None:
        secret = "password=do-not-leak"
        store = InMemoryTaskStore()
        service = FakeApplicationService(store, error=RuntimeError(secret))
        with InMemoryTaskExecutor(service, store) as executor:
            handle = executor.submit(ResearchRequest(question="Question"))
            task = wait_for_status(executor, handle.task_id)

        self.assertEqual(task.status, ResearchTaskStatus.FAILED)
        self.assertIn("RuntimeError", task.error)
        self.assertNotIn(secret, task.error)
        self.assertIsNone(task.artifact)

    def test_application_failure_is_preserved_without_duplicate_task(self) -> None:
        class FailingApplicationService(FakeApplicationService):
            def run(self, request):
                inner = self.task_store.save(
                    ResearchTask(
                        run_id=uuid4(),
                        question=request.question,
                        status=ResearchTaskStatus.FAILED,
                        error="research graph terminated without a report "
                        "(reading:AnalysisLLMInvocationError)",
                    )
                )
                raise ResearchExecutionError(
                    "research task execution failed",
                    task_id=inner.task_id,
                    run_id=inner.run_id,
                )

        store = InMemoryTaskStore()
        service = FailingApplicationService(store)
        with InMemoryTaskExecutor(service, store) as executor:
            handle = executor.submit(ResearchRequest(question="Question"))
            task = wait_for_status(executor, handle.task_id)

        self.assertEqual(task.status, ResearchTaskStatus.FAILED)
        self.assertIn("reading:AnalysisLLMInvocationError", task.error)
        self.assertEqual([item.task_id for item in store.list()], [handle.task_id])

    def test_status_query_delegates_to_shared_store(self) -> None:
        store = InMemoryTaskStore()
        service = FakeApplicationService(store)
        with InMemoryTaskExecutor(service, store) as executor:
            handle = executor.submit(ResearchRequest(question="Question"))
            task = wait_for_status(executor, handle.task_id)

            self.assertEqual(executor.get_status(handle.task_id), task)
            with self.assertRaises(TaskNotFoundError):
                executor.get_status(uuid4())

    def test_multiple_tasks_are_isolated(self) -> None:
        store = InMemoryTaskStore()
        service = FakeApplicationService(store)
        with InMemoryTaskExecutor(service, store, max_workers=2) as executor:
            first = executor.submit(ResearchRequest(question="First question"))
            second = executor.submit(ResearchRequest(question="Second question"))
            first_task = wait_for_status(executor, first.task_id)
            second_task = wait_for_status(executor, second.task_id)

        self.assertNotEqual(first.task_id, second.task_id)
        self.assertEqual(first_task.question, "First question")
        self.assertEqual(second_task.question, "Second question")
        self.assertEqual(first_task.status, ResearchTaskStatus.COMPLETED)
        self.assertEqual(second_task.status, ResearchTaskStatus.COMPLETED)

    def test_request_is_not_modified(self) -> None:
        request = ResearchRequest(question="Analyze localization", max_papers=4)
        original = request.model_copy(deep=True)
        store = InMemoryTaskStore()
        service = FakeApplicationService(store)
        with InMemoryTaskExecutor(service, store) as executor:
            handle = executor.submit(request)
            wait_for_status(executor, handle.task_id)

        self.assertEqual(request, original)
        self.assertEqual(service.requests[0], original)
        self.assertIsNot(service.requests[0], request)

    def test_application_service_instance_is_reused(self) -> None:
        store = InMemoryTaskStore()
        service = FakeApplicationService(store)
        with InMemoryTaskExecutor(service, store) as executor:
            handles = [
                executor.submit(ResearchRequest(question=f"Question {index}"))
                for index in range(2)
            ]
            for handle in handles:
                wait_for_status(executor, handle.task_id)

            self.assertIs(executor.application_service, service)
            self.assertIs(executor.task_store, service.task_store)
            self.assertEqual(len(service.requests), 2)

    def test_protocol_compatibility(self) -> None:
        store = InMemoryTaskStore()
        service = FakeApplicationService(store)
        executor = InMemoryTaskExecutor(service, store)
        try:
            self.assertIsInstance(executor, TaskExecutorProtocol)
        finally:
            executor.shutdown()


if __name__ == "__main__":
    unittest.main()
