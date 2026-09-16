"""Offline contract checks for the PaperGuide Docker deployment."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_declares_only_paperguide_services() -> None:
    assert set(_compose()["services"]) == {"dashboard", "api", "host"}


def test_compose_uses_one_persistent_data_volume() -> None:
    compose = _compose()
    assert compose["volumes"]["paperguide-data"]["name"] == "paperguide-data"
    for service in ("api", "host"):
        assert "paperguide-data:/app/data" in compose["services"][service]["volumes"]


def test_runtime_paths_share_artifacts_and_sqlite_parent() -> None:
    environment = _compose()["x-python-environment"]
    assert environment["PAPERGUIDE_EXPORT_DIRECTORY"] == "/app/data/artifacts"
    for service in ("api", "host"):
        dockerfile = (ROOT / "docker" / service / "Dockerfile").read_text(encoding="utf-8")
        assert "/app/data/artifacts" in dockerfile
        assert "ln -s runtime.db /app/data/paperguide-runtime.sqlite3" in dockerfile


def test_each_service_has_healthcheck_and_resource_limits() -> None:
    for service in _compose()["services"].values():
        assert service["healthcheck"]["test"]
        assert service["cpus"] > 0
        assert service["mem_limit"]


def test_api_uses_factory_uvicorn_on_container_interface() -> None:
    command = _compose()["services"]["api"]["command"]
    assert command[:2] == ["uvicorn", "paperguide.api.app:create_default_api_app"]
    assert "--factory" in command
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert command[command.index("--port") + 1] == "8000"


def test_host_uses_existing_cli_entrypoint() -> None:
    dockerfile = (ROOT / "docker" / "host" / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["paperguide", "server", "start"]' in dockerfile


def test_dashboard_build_arg_and_nginx_routing() -> None:
    dockerfile = (ROOT / "docker" / "dashboard" / "Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "docker" / "dashboard" / "nginx.conf").read_text(encoding="utf-8")
    assert "ARG VITE_PAPERGUIDE_API_BASE_URL" in dockerfile
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "location /api/" in nginx
    assert "proxy_pass http://api:8000" in nginx
    assert "location = /healthz" in nginx


def test_dockerfiles_do_not_embed_secret_assignments() -> None:
    secret_assignment = re.compile(r"(?i)(api[_-]?key|token|password)\s*=")
    for dockerfile in (ROOT / "docker").glob("*/Dockerfile"):
        assert secret_assignment.search(dockerfile.read_text(encoding="utf-8")) is None


def test_docker_context_excludes_environment_and_runtime_data() -> None:
    patterns = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in patterns
    assert "**/.env" in patterns
    assert "runtime-data/" in patterns
    assert "paperguide-dashboard/node_modules/" in patterns


def test_dashboard_and_api_publish_local_only_ports() -> None:
    services = _compose()["services"]
    assert services["dashboard"]["ports"] == ["127.0.0.1:${PAPERGUIDE_DASHBOARD_PORT:-80}:80"]
    assert services["api"]["ports"] == ["127.0.0.1:${PAPERGUIDE_API_PORT:-8000}:8000"]
