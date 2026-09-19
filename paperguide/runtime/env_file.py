"""Load a local ``.env`` before settings are read.

The README and ``.env.example`` both tell the reader to configure PaperGuide
through ``.env``, and ``.env.example`` lists the ``PAPERGUIDE_*`` variables by
name. Nothing in this package read that file: only the inherited GPT-Researcher
entrypoints called ``load_dotenv``. A key written there was therefore ignored
without any error, which is the worst shape a configuration failure can take —
the run simply behaves as if nothing was set.

Values already present in the environment win. An ``export`` on the command
line is the more specific instruction, and a shell that has one set should not
have it silently replaced by a stale file.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

LOGGER = logging.getLogger("paperguide.runtime")

ENV_FILENAME = ".env"


def _search_roots(start: Path) -> list[Path]:
    """The working directory and its ancestors, nearest first."""

    return [start, *start.parents]


def find_env_file(start: Path | None = None) -> Path | None:
    """Locate the nearest ``.env`` at or above ``start``."""

    origin = (start or Path.cwd()).resolve()
    for directory in _search_roots(origin):
        candidate = directory / ENV_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_env_file(start: Path | None = None) -> Path | None:
    """Apply the nearest ``.env`` without overriding the existing environment.

    Returns the file that was applied, or ``None`` when there was none. Missing
    files and an unreadable one are not errors: the environment may be supplied
    entirely by the shell or the container.
    """

    path = find_env_file(start)
    if path is None:
        return None
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv ships with the project
        LOGGER.debug("python-dotenv is unavailable; skipping %s", ENV_FILENAME)
        return None
    try:
        load_dotenv(path, override=False)
    except OSError:
        # Only the path is logged. The file holds credentials, so nothing from
        # inside it may reach the log.
        LOGGER.warning("could not read %s", ENV_FILENAME)
        return None
    return path


def env_file_summary(start: Path | None = None) -> str:
    """Describe what was loaded, naming variables but never their values."""

    path = find_env_file(start)
    if path is None:
        return f"no {ENV_FILENAME} found"
    names = sorted(
        key
        for key in os.environ
        if key.startswith("PAPERGUIDE_") or key.endswith("_API_KEY")
    )
    return f"{ENV_FILENAME} loaded; set: {', '.join(names) or 'nothing recognised'}"
