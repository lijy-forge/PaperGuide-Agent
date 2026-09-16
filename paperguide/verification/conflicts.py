"""Conservative rule-based conflict detection across verified evidence claims."""

import re
from collections import defaultdict

from .models import ConflictRecord, VerificationStatus, VerifiedEvidence


class EvidenceConflictDetector:
    """Detect explicit direction, numeric, and support conflicts without an LLM."""

    _NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?%?")
    _POSITIVE = ("higher", "increase", "improve", "outperform", "better", "提升", "提高", "优于")
    _NEGATIVE = ("lower", "decrease", "reduce", "worse", "下降", "降低", "减少")

    def detect(self, items: list[VerifiedEvidence]) -> list[ConflictRecord]:
        """Return stable conflict records while leaving verification items unchanged."""

        conflicts: list[ConflictRecord] = []
        seen: set[tuple] = set()
        by_claim: dict[str, list[VerifiedEvidence]] = defaultdict(list)
        by_evidence: dict[object, list[VerifiedEvidence]] = defaultdict(list)
        by_metric: dict[str, list[VerifiedEvidence]] = defaultdict(list)
        for item in items:
            by_claim[self._normalize(item.claim)].append(item)
            by_evidence[item.evidence.id].append(item)
            if item.source_field and item.source_field.startswith("experiment.metric:"):
                base = re.sub(r"#\d+$", "", item.source_field.casefold())
                by_metric[base].append(item)

        for group in by_claim.values():
            if len(group) > 1:
                self._compare_group(group, "same_claim", conflicts, seen)
                self._numeric_group(
                    group,
                    "same_claim_numeric",
                    conflicts,
                    seen,
                    use_quote=True,
                )
        supported_statuses = {
            VerificationStatus.VERIFIED,
            VerificationStatus.PARTIALLY_SUPPORTED,
        }
        for group in by_evidence.values():
            supported_group = [
                item for item in group if item.status in supported_statuses
            ]
            if len({item.claim for item in supported_group}) > 1:
                self._compare_group(
                    supported_group,
                    "same_evidence",
                    conflicts,
                    seen,
                )
        for group in by_metric.values():
            if len(group) > 1:
                self._numeric_group(group, "metric_value", conflicts, seen)
        return conflicts

    def _compare_group(
        self,
        group: list[VerifiedEvidence],
        prefix: str,
        conflicts: list[ConflictRecord],
        seen: set[tuple],
    ) -> None:
        directions = {
            direction
            for item in group
            for direction in (
                self._direction(item.claim),
                self._direction(item.evidence.quote),
            )
            if direction is not None
        }
        if len(directions) > 1:
            self._record(group, f"{prefix}_direction", "Opposing comparison directions.", conflicts, seen)
        statuses = {item.status for item in group}
        if (
            VerificationStatus.REJECTED in statuses
            and statuses & {VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_SUPPORTED}
        ):
            self._record(group, f"{prefix}_support", "Evidence decisions explicitly disagree.", conflicts, seen)
        if any(item.contradiction_score >= 0.7 for item in group):
            self._record(group, f"{prefix}_contradiction", "High contradiction score detected.", conflicts, seen)

    def _numeric_group(
        self,
        group: list[VerifiedEvidence],
        conflict_type: str,
        conflicts: list[ConflictRecord],
        seen: set[tuple],
        *,
        use_quote: bool = False,
    ) -> None:
        values = {
            tuple(
                self._NUMBER_RE.findall(
                    item.evidence.quote if use_quote else item.claim
                )
            )
            for item in group
            if self._NUMBER_RE.findall(item.evidence.quote if use_quote else item.claim)
        }
        if len(values) > 1:
            self._record(group, conflict_type, "Different values reported for the same metric field.", conflicts, seen)

    @staticmethod
    def _record(
        group: list[VerifiedEvidence],
        conflict_type: str,
        description: str,
        conflicts: list[ConflictRecord],
        seen: set[tuple],
    ) -> None:
        evidence_ids = list(dict.fromkeys(item.evidence.id for item in group))
        claims = list(dict.fromkeys(item.claim for item in group))
        signature = (conflict_type, tuple(evidence_ids), tuple(claims))
        if signature in seen:
            return
        seen.add(signature)
        conflicts.append(
            ConflictRecord(
                evidence_ids=evidence_ids,
                claims=claims,
                conflict_type=conflict_type,
                description=description,
                confidence=0.8,
                warnings=["Conflict requires human or higher-level review."],
            )
        )

    @classmethod
    def _direction(cls, text: str) -> str | None:
        folded = text.casefold()
        positive = any(term in folded for term in cls._POSITIVE)
        negative = any(term in folded for term in cls._NEGATIVE)
        if positive == negative:
            return None
        return "positive" if positive else "negative"

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.casefold().split())
