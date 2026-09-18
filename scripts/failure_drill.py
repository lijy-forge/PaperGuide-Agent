"""Drive the runtime's failure paths so the dashboard counters can be checked.

A healthy demo run only ever moves ``已提交`` and ``已完成``. Every other counter
on the dashboard stays at zero, which leaves the operator unable to tell a
working counter from a broken one. This script exercises the two paths that
produce the remaining numbers, using the same broker the host uses:

``fail``
    An application whose ``run`` raises. The host marks the task FAILED and
    does **not** retry it: a request that is bad in itself will be just as bad
    the second time, so retrying only burns the quota.

``deadletter``
    A worker that dies while holding a lease, repeatedly. Nothing marks the
    task failed here — the host that would have done so is gone — so the lease
    simply expires and recovery requeues the task. After ``max_attempts``
    expiries the task is dead-lettered instead of being handed to a fourth
    worker that would most likely die the same way.

Both drills write to the real runtime database, so run them against a
throwaway one unless the intent is to populate a demo dashboard:

    python -m scripts.failure_drill deadletter --database drill.sqlite3
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

from paperguide.application.models import ResearchRequest
from paperguide.execution.sqlite import PersistentTaskStore
from paperguide.runtime.host.broker import SQLiteHostBroker
from paperguide.runtime.host.client import PersistentTaskHostClient
from paperguide.runtime.host.hardening import RuntimeRecoveryService
from paperguide.runtime.host.service import TaskHost
from paperguide.runtime.settings import RuntimeSettings

_HOST_VERSION_WAIT = 0.4


def _settings() -> RuntimeSettings:
    """Demo mode, so the drill never needs a provider or a key."""

    return RuntimeSettings.model_validate({"mode": "demo", "log_level": "WARNING"})


def _counters(broker: SQLiteHostBroker) -> dict[str, int]:
    snapshot = broker.get_metrics()
    return {
        "已提交": snapshot.submitted,
        "已完成": snapshot.completed,
        "失败": snapshot.failed,
        "已取消": snapshot.cancelled,
        "死信任务": snapshot.dead_letter_total,
        "队列长度": snapshot.queue_size,
        "运行中任务": snapshot.running_tasks,
        "租约过期": snapshot.lease_expired_total,
    }


def _report(label: str, before: dict[str, int], after: dict[str, int]) -> None:
    print(f"\n{label}")
    print(f"  {'计数器':<12}{'演练前':>8}{'演练后':>8}{'增量':>8}")
    for key in before:
        delta = after[key] - before[key]
        mark = "  <-- " if delta else ""
        print(f"  {key:<12}{before[key]:>8}{after[key]:>8}{delta:>+8}{mark}")


class _RaisingApplicationService:
    """Stand in for the real service and fail the way a bad request would."""

    def __init__(self, task_store: PersistentTaskStore) -> None:
        self.task_store = task_store

    def run(self, request: ResearchRequest) -> None:
        raise RuntimeError("injected failure for the drill")


def drill_fail(database: Path, count: int) -> int:
    """Submit requests whose execution raises, and confirm they land as FAILED."""

    settings = _settings()
    broker = SQLiteHostBroker(database)
    before = _counters(broker)

    def failing_application(config, *, task_store, **_kwargs):
        class _Container:
            def __init__(self) -> None:
                self.application_service = _RaisingApplicationService(task_store)

        return _Container()

    host = TaskHost(
        settings,
        database_path=database,
        application_factory=failing_application,
        poll_interval=0.05,
    )
    thread = threading.Thread(target=host.serve_forever, daemon=True)
    thread.start()
    time.sleep(_HOST_VERSION_WAIT)

    # Submit the way the API does. Handing the request straight to the
    # executor would skip the broker, and then nothing records the events the
    # dashboard counts: the tasks fail but every counter stays at zero.
    store = PersistentTaskStore(database)
    client = PersistentTaskHostClient(store, broker)
    task_ids: list[UUID] = []
    for index in range(count):
        handle = client.submit(
            ResearchRequest(question=f"故障演练 {index}", max_papers=3)
        )
        task_ids.append(handle.task_id)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        statuses = [store.get(task_id).status.value for task_id in task_ids]
        if all(status in {"failed", "completed", "cancelled"} for status in statuses):
            break
        time.sleep(0.2)

    host.shutdown()
    thread.join(timeout=10)
    after = _counters(broker)
    _report(f"演练一：{count} 个任务在执行时抛异常", before, after)
    print("\n  任务终态：")
    for task_id in task_ids:
        task = store.get(task_id)
        print(f"    {str(task_id)[:8]}  {task.status.value:<10}{task.error or ''}")
    if after["失败"] > before["失败"] and after["死信任务"] == before["死信任务"]:
        print(
            "\n  「失败」增加而「死信任务」没有：抛异常的请求不重试，"
            "\n  因为同一个请求再跑一次还是会抛。"
        )
    return 0


def drill_dead_letter(database: Path, max_attempts: int) -> int:
    """Let a lease expire repeatedly until recovery gives up on the task."""

    broker = SQLiteHostBroker(database)
    store = PersistentTaskStore(database)
    recovery = RuntimeRecoveryService(broker, store, max_attempts=max_attempts)
    before = _counters(broker)

    # Enqueue without a host, so nothing can claim the task behind our back.
    host_id = uuid4()
    broker.acquire_host(host_id, version="drill")
    client = PersistentTaskHostClient(store, broker)
    task_id = client.submit(
        ResearchRequest(question="崩溃恢复演练", max_papers=3)
    ).task_id
    print(f"\n  任务 {task_id}")

    for attempt in range(1, max_attempts + 2):
        lease = broker.claim_next(host_id, lease_seconds=0.5, require_healthy_host=False)
        if lease is None:
            print(f"  第 {attempt} 次：队列里已经没有它了 —— 说明已被放弃")
            break
        print(
            f"  第 {attempt} 次：被领走（attempt_count={lease.attempt_count}），"
            "模拟 worker 在持有租约时崩溃"
        )
        time.sleep(0.7)  # outlive the lease without ever reporting a result
        result = recovery.recover()
        if task_id in result.dead_lettered:
            print(f"  第 {attempt} 次：租约过期，已达上限 {max_attempts} 次 -> 移入死信")
            break
        if task_id in result.requeued:
            print(f"  第 {attempt} 次：租约过期 -> 放回队列重试")

    broker.release_host(host_id)
    after = _counters(broker)
    _report(f"演练二：worker 反复崩溃（上限 {max_attempts} 次）", before, after)
    if after["死信任务"] > before["死信任务"] and after["失败"] == before["失败"]:
        print(
            "\n  「死信任务」增加而「失败」没有：没有任何东西把它标成失败，"
            "\n  因为本该标记的那个进程已经死了。判定完全由租约过期做出。"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("drill", choices=["fail", "deadletter"])
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("paperguide-runtime.sqlite3"),
        help="runtime database to write to (default: the real one)",
    )
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--max-attempts", type=int, default=3)
    arguments = parser.parse_args(argv)

    if arguments.drill == "fail":
        return drill_fail(arguments.database, arguments.count)
    return drill_dead_letter(arguments.database, arguments.max_attempts)


if __name__ == "__main__":
    sys.exit(main())
