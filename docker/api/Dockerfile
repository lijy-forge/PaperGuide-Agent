FROM python:3.11-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv

RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build
COPY pyproject.toml README.md ./
COPY paperguide ./paperguide
COPY gpt_researcher ./gpt_researcher
RUN pip install --upgrade pip && pip install .

FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PAPERGUIDE_EXPORT_DIRECTORY=/app/data/artifacts

RUN apt-get update && apt-get install --yes --no-install-recommends \
      fonts-dejavu-core \
      fonts-noto-cjk \
      libglib2.0-0 \
      libmagic1 \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      shared-mime-info \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 paperguide \
    && useradd --uid 10001 --gid paperguide --create-home paperguide

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=paperguide:paperguide paperguide ./paperguide
COPY --chown=paperguide:paperguide gpt_researcher ./gpt_researcher
RUN mkdir -p /app/data/artifacts /app/data/logs /app/data/paperguide-downloads \
    && ln -s runtime.db /app/data/paperguide-runtime.sqlite3 \
    && chown -R paperguide:paperguide /app/data

USER paperguide
EXPOSE 8000
CMD ["uvicorn", "paperguide.api.app:create_default_api_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
