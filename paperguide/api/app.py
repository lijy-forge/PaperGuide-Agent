"""FastAPI application factory for the unauthenticated local demonstration API."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from paperguide.application import TaskStoreProtocol
from paperguide.runtime import RuntimeSettings
from paperguide.runtime.host import PersistentTaskHostClient, SQLiteHostBroker
from paperguide.runtime.metrics import MetricsExporterProtocol

from .dependencies import (
    APIDependencies,
    APIRuntimeHealthChecker,
    RuntimeHealthCheckerProtocol,
    create_default_dependencies,
)
from .error_handlers import install_error_handlers
from .routes import (
    artifacts_router,
    events_router,
    health_router,
    internal_router,
    manual_sources_router,
    metrics_router,
    research_router,
    tasks_router,
)
from .schemas import APISettings
from .security import APISecurityMiddleware


def create_api_app(
    *,
    dependencies: APIDependencies | None = None,
    task_host_client: PersistentTaskHostClient | None = None,
    task_store: TaskStoreProtocol | None = None,
    broker: SQLiteHostBroker | None = None,
    metrics_exporter: MetricsExporterProtocol | None = None,
    runtime_health_checker: RuntimeHealthCheckerProtocol | None = None,
    artifact_root: str | Path | None = None,
    api_settings: APISettings | None = None,
    runtime_settings: RuntimeSettings | None = None,
) -> FastAPI:
    """Create a thin API that never constructs workers, Graphs, or LLM clients."""

    if dependencies is None:
        explicit = (
            task_host_client,
            task_store,
            broker,
            metrics_exporter,
        )
        if all(value is not None for value in explicit):
            settings = api_settings or APISettings(
                artifact_root=artifact_root or "paperguide-exports",
            )
            root = Path(artifact_root or settings.artifact_root).resolve(
                strict=False
            )
            checker = runtime_health_checker or APIRuntimeHealthChecker(
                broker,
                root,
            )
            dependencies = APIDependencies(
                task_host_client=task_host_client,
                task_store=task_store,
                broker=broker,
                metrics_exporter=metrics_exporter,
                runtime_health_checker=checker,
                settings=settings,
                artifact_root=root,
            )
        elif any(value is not None for value in explicit):
            raise ValueError("all explicit API runtime dependencies are required")
        else:
            dependencies = create_default_dependencies(
                api_settings,
                runtime_settings,
            )
    settings = APISettings.model_validate(dependencies.settings.model_dump())
    root = dependencies.artifact_root.resolve(strict=False)
    app = FastAPI(
        title=settings.title,
        version=settings.version,
        description=(
            "Local demonstration API. User authentication is not implemented; "
            "do not expose this service directly to untrusted networks."
        ),
    )
    app.state.paperguide_dependencies = APIDependencies(
        task_host_client=dependencies.task_host_client,
        task_store=dependencies.task_store,
        broker=dependencies.broker,
        metrics_exporter=dependencies.metrics_exporter,
        runtime_health_checker=dependencies.runtime_health_checker,
        settings=settings,
        artifact_root=root,
    )
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Request-ID"],
            expose_headers=[
                "Content-Disposition",
                "Content-Type",
                "X-Artifact-SHA256",
                "X-Request-ID",
            ],
        )
    app.add_middleware(APISecurityMiddleware)
    install_error_handlers(app)
    app.include_router(research_router, prefix=settings.api_prefix)
    app.include_router(manual_sources_router, prefix=settings.api_prefix)
    app.include_router(tasks_router, prefix=settings.api_prefix)
    app.include_router(events_router, prefix=settings.api_prefix)
    app.include_router(artifacts_router, prefix=settings.api_prefix)
    app.include_router(metrics_router, prefix=settings.api_prefix)
    app.include_router(health_router)
    app.include_router(internal_router)
    return app


def create_default_api_app() -> FastAPI:
    """Uvicorn factory creating only lightweight persistent runtime clients."""

    return create_api_app()
