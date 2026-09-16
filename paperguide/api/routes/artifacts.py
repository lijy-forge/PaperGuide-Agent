"""Boundary-checked report artifact download route."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from paperguide.application import ResearchTaskStatus
from paperguide.export import (
    ArtifactFormatIntegrityError,
    ArtifactFormatIntegrityValidator,
    ExportFormat,
)

from ..dependencies import APIDependencies, get_api_dependencies
from ..exceptions import APIError
from ..schemas import ErrorResponse

router = APIRouter(prefix="/tasks", tags=["artifacts"])

_MEDIA_TYPES = {
    ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
    ExportFormat.HTML: "text/html; charset=utf-8",
    ExportFormat.PDF: "application/pdf",
}
_EXTENSIONS = {
    ExportFormat.MARKDOWN: ".md",
    ExportFormat.HTML: ".html",
    ExportFormat.PDF: ".pdf",
}


@router.get(
    "/{task_id}/artifact",
    response_class=FileResponse,
    summary="Download a completed research artifact",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def download_artifact(
    task_id: UUID,
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> FileResponse:
    task = dependencies.task_store.get(task_id)
    if task.status is not ResearchTaskStatus.COMPLETED or task.artifact is None:
        raise APIError(
            "ARTIFACT_NOT_READY",
            "Research artifact is not ready.",
            409,
        )
    artifact = task.artifact
    if artifact.task_id is not None and artifact.task_id != task_id:
        raise APIError(
            "ARTIFACT_PATH_INVALID",
            "Artifact path is invalid.",
            400,
        )
    root = dependencies.artifact_root.resolve(strict=False)
    candidate = Path(artifact.file_path)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError as error:
        raise APIError(
            "ARTIFACT_NOT_FOUND",
            "Research artifact file was not found.",
            404,
        ) from error
    except (OSError, ValueError) as error:
        raise APIError(
            "ARTIFACT_PATH_INVALID",
            "Artifact path is invalid.",
            400,
        ) from error
    if not resolved.is_file():
        raise APIError(
            "ARTIFACT_NOT_FOUND",
            "Research artifact file was not found.",
            404,
        )
    try:
        ArtifactFormatIntegrityValidator().validate(
            artifact.format,
            resolved.name,
            _MEDIA_TYPES[artifact.format],
            resolved.read_bytes(),
        )
    except (ArtifactFormatIntegrityError, OSError) as error:
        raise APIError(
            "ARTIFACT_FORMAT_MISMATCH",
            "Research artifact format is invalid.",
            409,
        ) from error
    filename = f"research-report{_EXTENSIONS[artifact.format]}"
    headers = {
        "X-Artifact-SHA256": artifact.sha256,
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
    return FileResponse(
        path=resolved,
        media_type=_MEDIA_TYPES[artifact.format],
        filename=filename,
        content_disposition_type="attachment",
        headers=headers,
    )
