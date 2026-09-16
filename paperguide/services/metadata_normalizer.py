"""Deterministic normalization helpers for paper metadata."""

import re
import unicodedata
from urllib.parse import unquote, urlsplit, urlunsplit


class MetadataNormalizer:
    """Normalize common paper identifiers and descriptive metadata."""

    _WHITESPACE_RE = re.compile(r"\s+")
    _DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s<>]+$", re.IGNORECASE)
    _ARXIV_NEW_RE = re.compile(r"^\d{4}\.\d{4,5}$")
    _ARXIV_OLD_RE = re.compile(r"^[a-z][a-z0-9.\-]*/\d{7}$", re.IGNORECASE)
    _ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
    _DOI_PREFIX_RE = re.compile(r"^doi\s*:\s*", re.IGNORECASE)

    @classmethod
    def normalize_title(cls, title: str) -> str:
        """Return a case-folded title suitable for deterministic matching."""

        normalized = unicodedata.normalize("NFKC", title).casefold().strip()
        characters: list[str] = []
        for character in normalized:
            category = unicodedata.category(character)
            if character == "_" or category.startswith("P") or character.isspace():
                characters.append(" ")
            elif category[0] in {"L", "N", "M"}:
                characters.append(character)
            else:
                characters.append(" ")
        return cls._WHITESPACE_RE.sub(" ", "".join(characters)).strip()

    @classmethod
    def normalize_doi(cls, doi: str | None) -> str | None:
        """Normalize a DOI value or DOI URL, returning ``None`` if invalid."""

        if doi is None:
            return None
        value = unicodedata.normalize("NFKC", doi).strip()
        if not value:
            return None

        lowered = value.casefold()
        if lowered.startswith(("http://", "https://")):
            try:
                parts = urlsplit(value)
            except ValueError:
                return None
            if (parts.hostname or "").casefold() not in {
                "doi.org",
                "www.doi.org",
                "dx.doi.org",
            }:
                return None
            value = unquote(parts.path).lstrip("/")
        else:
            value = cls._DOI_PREFIX_RE.sub("", value)

        value = cls._strip_doi_trailing_punctuation(value.strip().casefold())
        if not value or cls._DOI_RE.fullmatch(value) is None:
            return None
        return value

    @classmethod
    def normalize_arxiv_id(cls, arxiv_id: str | None) -> str | None:
        """Normalize modern and legacy arXiv identifiers without versions."""

        if arxiv_id is None:
            return None
        value = unicodedata.normalize("NFKC", arxiv_id).strip()
        if not value:
            return None

        if value.casefold().startswith(("http://", "https://")):
            try:
                parts = urlsplit(value)
            except ValueError:
                return None
            if (parts.hostname or "").casefold() not in {
                "arxiv.org",
                "www.arxiv.org",
                "export.arxiv.org",
            }:
                return None
            path = unquote(parts.path).strip("/")
            for prefix in ("abs/", "pdf/"):
                if path.casefold().startswith(prefix):
                    path = path[len(prefix) :]
                    break
            value = path
        else:
            value = re.sub(r"^arxiv\s*:\s*", "", value, flags=re.IGNORECASE)

        value = re.sub(r"\.pdf$", "", value, flags=re.IGNORECASE)
        value = cls._ARXIV_VERSION_RE.sub("", value).strip().casefold()
        if cls._ARXIV_NEW_RE.fullmatch(value) or cls._ARXIV_OLD_RE.fullmatch(value):
            return value
        return None

    @classmethod
    def normalize_author_name(cls, name: str) -> str:
        """Normalize basic ``First Last`` and ``Last, First`` author forms."""

        value = unicodedata.normalize("NFKC", name).casefold().strip()
        value = cls._WHITESPACE_RE.sub(" ", value)
        if value.count(",") == 1:
            last_name, first_name = (part.strip() for part in value.split(",", 1))
            if first_name and last_name:
                value = f"{first_name} {last_name}"
        return cls._WHITESPACE_RE.sub(" ", value).strip()

    @classmethod
    def normalize_url(cls, url: str | None) -> str | None:
        """Normalize an HTTP URL while preserving its query and dropping fragments."""

        if url is None:
            return None
        value = unicodedata.normalize("NFKC", url).strip()
        if not value:
            return None
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError:
            return None
        scheme = parts.scheme.casefold()
        hostname = (parts.hostname or "").casefold()
        if scheme not in {"http", "https"} or not hostname or parts.username:
            return None

        if hostname in {"doi.org", "www.doi.org", "dx.doi.org"}:
            normalized_doi = cls.normalize_doi(value)
            if normalized_doi is None:
                return None
            return urlunsplit(
                ("https", "doi.org", f"/{normalized_doi}", parts.query, "")
            )

        if hostname in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
            normalized_arxiv_id = cls.normalize_arxiv_id(value)
            if normalized_arxiv_id is None:
                return None
            is_pdf = parts.path.casefold().startswith("/pdf/") or parts.path.casefold().endswith(
                ".pdf"
            )
            path = (
                f"/pdf/{normalized_arxiv_id}.pdf"
                if is_pdf
                else f"/abs/{normalized_arxiv_id}"
            )
            return urlunsplit(("https", "arxiv.org", path, parts.query, ""))

        default_port = (scheme == "http" and port == 80) or (
            scheme == "https" and port == 443
        )
        formatted_host = f"[{hostname}]" if ":" in hostname else hostname
        netloc = formatted_host if port is None or default_port else f"{formatted_host}:{port}"
        return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))

    @staticmethod
    def _strip_doi_trailing_punctuation(value: str) -> str:
        value = value.rstrip(".,;:")
        for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
            while value.endswith(closing) and value.count(closing) > value.count(opening):
                value = value[:-1].rstrip(".,;:")
        return value
