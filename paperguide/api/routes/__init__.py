"""PaperGuide API route modules."""

from .artifacts import router as artifacts_router
from .events import router as events_router
from .health import router as health_router
from .internal import router as internal_router
from .metrics import router as metrics_router
from .manual_sources import router as manual_sources_router
from .research import router as research_router
from .tasks import router as tasks_router

__all__ = [
    "artifacts_router",
    "events_router",
    "health_router",
    "internal_router",
    "metrics_router",
    "manual_sources_router",
    "research_router",
    "tasks_router",
]
