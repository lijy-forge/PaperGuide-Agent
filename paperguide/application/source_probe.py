"""Check that a paper source will answer, before a run starts spending.

The pipeline plans its queries with the model and only then searches, so a run
begun while every source is rate-limited pays for the planning call and then
fails with nothing retrieved. The money is spent on work that could not have
led anywhere.

The probe runs first and asks one cheap question of each source. One source
answering is enough: the run can proceed on a smaller pool, which the report
already records. Only when none answer is the run refused, and then no model
call has been made.

A probe cannot prove the sources will keep answering — a limit can begin
between the probe and the search. It is not a guarantee, it is a way to stop
paying for the case that is already lost when the run begins.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

LOGGER = logging.getLogger("paperguide.application")

#: Short, common, and unrelated to any real question, so a source's own cache
#: is as likely to answer it as anything else.
PROBE_QUERY = "learning"


@dataclass(frozen=True)
class SourceAvailability:
    """Which sources answered a probe, and what the others said."""

    answered: tuple[str, ...]
    errors: dict[str, str]

    @property
    def any_available(self) -> bool:
        return bool(self.answered)


class SourceProbeProtocol(Protocol):
    """What the application service needs of a probe."""

    def check(self) -> SourceAvailability: ...


class RetrieverAvailabilityProbe:
    """Ask each retriever for one result to see whether it is reachable."""

    def __init__(self, retrievers: Sequence[object], *, max_results: int = 1) -> None:
        if max_results < 1:
            raise ValueError("max_results must be at least one")
        self._retrievers = list(retrievers)
        self._max_results = max_results

    @staticmethod
    def _name(retriever: object, taken: set[str]) -> str:
        """A key unique within one probe.

        Two retrievers of the same class would otherwise share a key and one
        of their results would silently overwrite the other, hiding a refusal.
        """

        # A retriever declares its source as a PaperSource or, as the search
        # pipeline also allows, a plain string. Accept both rather than
        # falling back to a class name that means less to whoever reads it.
        source = getattr(retriever, "source", None)
        declared = getattr(source, "value", source)
        base = declared.strip() if isinstance(declared, str) and declared.strip() else ""
        base = base or type(retriever).__name__
        if base not in taken:
            return base
        index = 2
        while f"{base}#{index}" in taken:
            index += 1
        return f"{base}#{index}"

    def check(self) -> SourceAvailability:
        answered: list[str] = []
        errors: dict[str, str] = {}
        for retriever in self._retrievers:
            name = self._name(retriever, set(answered) | set(errors))
            try:
                retriever.search(PROBE_QUERY, max_results=self._max_results)
            except Exception as error:  # noqa: BLE001 - any failure means unusable
                # A source that answers with zero results is still available;
                # only an exception says it will not serve this run.
                errors[name] = f"{type(error).__name__}"
                continue
            answered.append(name)
        if not answered:
            LOGGER.warning("no paper source answered a probe", extra={"sources": errors})
        return SourceAvailability(answered=tuple(answered), errors=errors)
