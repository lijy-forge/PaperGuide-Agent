"""Controlled uploads for Google Scholar and CNKI manual supplements."""

import hashlib
import tempfile
from pathlib import Path
from uuid import uuid4

import pymupdf
from fastapi import APIRouter, Depends, Request, status

from ..dependencies import APIDependencies, get_api_dependencies
from ..exceptions import APIError
from ..schemas import ErrorResponse, ManualSourceUploadResponse

router = APIRouter(prefix="/manual-sources", tags=["manual-sources"])
MAX_MANUAL_PDF_BYTES = 50 * 1024 * 1024


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ManualSourceUploadResponse,
    summary="Upload a PDF acquired manually from Google Scholar or CNKI",
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
)
async def upload_manual_source(
    request: Request,
    dependencies: APIDependencies = Depends(get_api_dependencies),
) -> ManualSourceUploadResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    if content_type != "application/pdf":
        raise APIError("INVALID_PDF", "Content-Type must be application/pdf.", 400)
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > MAX_MANUAL_PDF_BYTES:
                raise APIError("PDF_TOO_LARGE", "PDF exceeds the 50 MB limit.", 413)
        except ValueError as error:
            raise APIError("INVALID_PDF", "Invalid Content-Length.", 400) from error
    payload = await request.body()
    if not payload or len(payload) > MAX_MANUAL_PDF_BYTES:
        code, message, status_code = (
            ("INVALID_PDF", "Uploaded PDF is empty.", 400)
            if not payload
            else ("PDF_TOO_LARGE", "PDF exceeds the 50 MB limit.", 413)
        )
        raise APIError(code, message, status_code)
    if not payload.startswith(b"%PDF"):
        raise APIError("INVALID_PDF", "Uploaded file is not a PDF.", 400)
    try:
        with pymupdf.open(stream=payload, filetype="pdf") as document:
            if document.needs_pass or document.page_count < 1:
                raise ValueError("encrypted or empty PDF")
            page_count = document.page_count
    except Exception as error:
        raise APIError("INVALID_PDF", "PDF is damaged, encrypted, or empty.", 400) from error

    upload_id = uuid4()
    target_root = (dependencies.artifact_root.parent / "manual-sources").resolve(strict=False)
    target_root.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".part", prefix=f"{upload_id}-", dir=target_root, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(payload)
        temporary_path.replace(target_root / f"{upload_id}.pdf")
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise APIError("UPLOAD_FAILED", "Unable to store the uploaded PDF.", 503) from error
    return ManualSourceUploadResponse(
        upload_id=upload_id,
        size_bytes=len(payload),
        page_count=page_count,
        sha256=hashlib.sha256(payload).hexdigest(),
    )