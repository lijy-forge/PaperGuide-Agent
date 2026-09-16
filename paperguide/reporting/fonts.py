"""Platform-aware font resolution for portable CJK survey PDFs."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Iterable


class CJKFontResolutionError(RuntimeError):
    """Raised when a Chinese report has no embeddable local CJK font."""


class CJKFontResolver:
    """Resolve an installed CJK font without bundling font binaries.

    An explicit ``PAPERGUIDE_CJK_FONT_PATH`` takes precedence. Windows uses
    installed Microsoft fonts, while Linux/Docker uses the paths provided by
    the ``fonts-noto-cjk`` package.
    """

    _SUPPORTED_SUFFIXES = frozenset({".ttf", ".ttc", ".otf", ".otc"})

    def __init__(self, explicit_path: str | Path | None = None) -> None:
        self.explicit_path = Path(explicit_path) if explicit_path else None

    def resolve(self) -> Path:
        """Return an existing font file or fail with a safe configuration error."""

        configured = self.explicit_path or self._environment_path()
        if configured is not None:
            return self._validate(configured, configured=True)
        for candidate in self._platform_candidates():
            if candidate.is_file() and candidate.suffix.casefold() in self._SUPPORTED_SUFFIXES:
                return candidate.resolve()
        raise CJKFontResolutionError(
            "No embeddable CJK font was found. Configure PAPERGUIDE_CJK_FONT_PATH "
            "or install Noto Sans CJK."
        )

    @staticmethod
    def _environment_path() -> Path | None:
        value = os.getenv("PAPERGUIDE_CJK_FONT_PATH", "").strip()
        return Path(value) if value else None

    @classmethod
    def _validate(cls, path: Path, *, configured: bool) -> Path:
        resolved = path.expanduser().resolve(strict=False)
        if not resolved.is_file() or resolved.suffix.casefold() not in cls._SUPPORTED_SUFFIXES:
            source = "Configured" if configured else "Resolved"
            raise CJKFontResolutionError(f"{source} CJK font is not a supported font file.")
        return resolved

    @staticmethod
    def _platform_candidates() -> Iterable[Path]:
        system = platform.system().casefold()
        if system == "windows":
            font_root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
            return (
                font_root / "NotoSansCJKsc-Regular.otf",
                font_root / "NotoSansCJK-Regular.ttc",
                font_root / "msyh.ttc",
                font_root / "simsun.ttc",
                font_root / "simhei.ttf",
            )
        if system == "darwin":
            return (
                Path("/System/Library/Fonts/PingFang.ttc"),
                Path("/Library/Fonts/NotoSansCJK-Regular.ttc"),
                Path("/Library/Fonts/NotoSansCJKsc-Regular.otf"),
            )
        return (
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/local/share/fonts/NotoSansCJK-Regular.ttc"),
        )
