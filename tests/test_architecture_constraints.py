"""Architecture gates for the paperguide package.

The package is layered: ``domain`` holds the pure model, and every other
subpackage sits above it. Two properties keep that layering honest and are
cheap to check, so they are asserted here rather than left to review:

* ``domain`` depends on nothing else inside paperguide.
* No two subpackages import each other at runtime.

Only module-level imports count. ``if TYPE_CHECKING:`` blocks and
function-local imports are deliberate tools for breaking a cycle, so they are
excluded — the package already uses both.
"""

import ast
from collections import deque
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "paperguide"


def _is_type_checking_guard(node: ast.stmt) -> bool:
    """Return whether a statement is an ``if TYPE_CHECKING:`` block."""

    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _module_level_imports(source: str, *, package: str) -> set[str]:
    """Return the paperguide subpackages imported at module level."""

    imported: set[str] = set()
    for node in ast.parse(source).body:
        if _is_type_checking_guard(node):
            continue
        targets: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            targets.append(node.module)
        elif isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        for target in targets:
            parts = target.split(".")
            if len(parts) >= 2 and parts[0] == "paperguide" and parts[1] != package:
                imported.add(parts[1])
    return imported


def _dependency_graph() -> dict[str, set[str]]:
    """Map each paperguide subpackage to the subpackages it imports."""

    graph: dict[str, set[str]] = {}
    for package_dir in sorted(PACKAGE_ROOT.iterdir()):
        if not package_dir.is_dir() or package_dir.name.startswith((".", "__")):
            continue
        package = package_dir.name
        edges: set[str] = set()
        for path in package_dir.rglob("*.py"):
            edges |= _module_level_imports(path.read_text("utf-8"), package=package)
        graph[package] = edges
    return graph


@pytest.fixture(scope="module")
def graph() -> dict[str, set[str]]:
    return _dependency_graph()


def test_subpackages_were_discovered(graph):
    """Guard the gates below against silently scanning nothing."""

    assert "domain" in graph
    assert len(graph) >= 10


def test_domain_layer_depends_on_nothing_inside_paperguide(graph):
    """The domain model stays free of application and infrastructure concerns."""

    assert graph["domain"] == set()


def test_no_subpackage_import_cycles(graph):
    """A runtime cycle between subpackages means the layering has broken down."""

    cycles: list[list[str]] = []
    for start in graph:
        # Breadth-first walk back to the starting package.
        queue = deque((neighbour, [start, neighbour]) for neighbour in graph[start])
        seen = set(graph[start])
        while queue:
            current, path = queue.popleft()
            if current == start:
                cycles.append(path)
                break
            for neighbour in graph.get(current, set()):
                if neighbour == start:
                    cycles.append([*path, neighbour])
                    queue.clear()
                    break
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append((neighbour, [*path, neighbour]))
    assert not cycles, f"import cycles between paperguide subpackages: {cycles}"
