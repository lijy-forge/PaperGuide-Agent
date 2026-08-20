"""Artifact download path and response security tests."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from paperpilot.application import ResearchTask, ResearchTaskStatus
from paperpilot.export import ArtifactMetadata, ExportFormat
from tests.api_fixtures import APITestRuntime


class APIArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = APITestRuntime()

    def tearDown(self) -> None:
        self.runtime.close()

    def test_markdown_download(self) -> None:
        task = self.runtime.completed_task(
            ExportFormat.MARKDOWN,
            content=b"# report",
        )
        response = self.runtime.client.get(
            f"/api/v1/tasks/{task.task_id}/artifact"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/markdown"))
        self.assertEqual(response.content, b"# report")

    def test_html_is_forced_to_safe_attachment(self) -> None:
        task = self.runtime.completed_task(
            ExportFormat.HTML,
            content=b"<!doctype html><html><script>alert(1)</script></html>",
        )
        response = self.runtime.client.get(
            f"/api/v1/tasks/{task.task_id}/artifact"
        )
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("sandbox", response.headers["content-security-policy"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_pdf_has_correct_mime_type(self) -> None:
        task = self.runtime.completed_task(
            ExportFormat.PDF,
            content=b"%PDF-1.7\n",
        )
        response = self.runtime.client.get(
            f"/api/v1/tasks/{task.task_id}/artifact"
        )
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("research-report.pdf", response.headers["content-disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_cross_origin_download_exposes_artifact_filename_and_checksum(self) -> None:
        self.runtime.close()
        self.runtime = APITestRuntime(
            cors_origins=["http://127.0.0.1:5173"]
        )
        task = self.runtime.completed_task(
            ExportFormat.PDF,
            content=b"%PDF-1.7\n",
        )
        response = self.runtime.client.get(
            f"/api/v1/tasks/{task.task_id}/artifact",
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        exposed = response.headers.get("access-control-expose-headers", "").casefold()
        self.assertIn("content-disposition", exposed)
        self.assertIn("x-artifact-sha256", exposed)

    def test_markdown_and_html_have_matching_download_extensions(self) -> None:
        for export_format, content, extension in (
            (ExportFormat.MARKDOWN, b"# report", ".md"),
            (ExportFormat.HTML, b"<!doctype html><html></html>", ".html"),
        ):
            task = self.runtime.completed_task(export_format, content=content)
            response = self.runtime.client.get(
                f"/api/v1/tasks/{task.task_id}/artifact"
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(
                f"research-report{extension}", response.headers["content-disposition"]
            )

    def test_mismatched_pdf_artifact_is_rejected(self) -> None:
        task = self.runtime.completed_task(
            ExportFormat.PDF,
            content=b"# not a pdf",
        )
        response = self.runtime.client.get(
            f"/api/v1/tasks/{task.task_id}/artifact"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "ARTIFACT_FORMAT_MISMATCH")

    def test_incomplete_task_returns_409(self) -> None:
        task = self.runtime.save_task(ResearchTaskStatus.RUNNING)
        response = self.runtime.client.get(
            f"/api/v1/tasks/{task.task_id}/artifact"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "ARTIFACT_NOT_READY")

    def test_missing_file_returns_404(self) -> None:
        task = self.runtime.completed_task(ExportFormat.MARKDOWN)
        Path(task.artifact.file_path).unlink()
        response = self.runtime.client.get(
            f"/api/v1/tasks/{task.task_id}/artifact"
        )
        self.assertEqual(response.status_code, 404)

    def test_parent_path_traversal_is_rejected(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as external:
            external.write(b"outside")
            outside = Path(external.name)
        try:
            task = self._save_external_artifact(outside)
            response = self.runtime.client.get(
                f"/api/v1/tasks/{task.task_id}/artifact"
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["code"], "ARTIFACT_PATH_INVALID")
        finally:
            outside.unlink(missing_ok=True)

    def test_forged_absolute_external_path_is_rejected(self) -> None:
        outside = Path(self.runtime.temporary.name).parent / "forged-report.md"
        outside.write_bytes(b"forged")
        try:
            task = self._save_external_artifact(outside)
            response = self.runtime.client.get(
                f"/api/v1/tasks/{task.task_id}/artifact"
            )
            self.assertEqual(response.status_code, 400)
        finally:
            outside.unlink(missing_ok=True)

    def test_checksum_header_is_returned_without_internal_path(self) -> None:
        task = self.runtime.completed_task(
            ExportFormat.MARKDOWN,
            content=b"checksum",
        )
        response = self.runtime.client.get(
            f"/api/v1/tasks/{task.task_id}/artifact"
        )
        expected = hashlib.sha256(b"checksum").hexdigest()
        self.assertEqual(response.headers["x-artifact-sha256"], expected)
        self.assertNotIn(str(self.runtime.artifact_root), response.text)

    def _save_external_artifact(self, outside: Path) -> ResearchTask:
        task_id = uuid4()
        content = outside.read_bytes()
        artifact = ArtifactMetadata(
            format=ExportFormat.MARKDOWN,
            file_path=str(outside),
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            task_id=task_id,
            execution_id=f"{task_id}:1",
        )
        return self.runtime.store.save(
            ResearchTask(
                task_id=task_id,
                run_id=uuid4(),
                question="Forged path",
                status=ResearchTaskStatus.COMPLETED,
                artifact=artifact,
            )
        )


if __name__ == "__main__":
    unittest.main()
