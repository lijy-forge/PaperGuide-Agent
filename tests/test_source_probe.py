"""A run that cannot retrieve anything must not pay to find that out."""

import unittest

from paperguide.application import RetrieverAvailabilityProbe, SourceAvailability


class _Answering:
    def search(self, query: str, max_results: int = 10):
        return [object()]


class _Empty:
    """Reachable, but has nothing for this query."""

    def search(self, query: str, max_results: int = 10):
        return []


class _Refusing:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def search(self, query: str, max_results: int = 10):
        raise self._error


class RetrieverAvailabilityProbeTests(unittest.TestCase):
    def test_one_answering_source_is_enough(self) -> None:
        # The run can proceed on a smaller pool, and the report records that
        # a source was missing; refusing here would be stricter than needed.
        probe = RetrieverAvailabilityProbe(
            [_Refusing(RuntimeError("429")), _Answering()]
        )
        availability = probe.check()

        self.assertTrue(availability.any_available)
        self.assertEqual(availability.answered, ("_Answering",))
        self.assertIn("_Refusing", availability.errors)

    def test_zero_results_still_counts_as_available(self) -> None:
        # An empty answer is an answer: the source is up and simply has
        # nothing for the probe's throwaway query.
        self.assertTrue(RetrieverAvailabilityProbe([_Empty()]).check().any_available)

    def test_every_source_refusing_is_reported(self) -> None:
        probe = RetrieverAvailabilityProbe(
            [_Refusing(RuntimeError("406")), _Refusing(TimeoutError())]
        )
        availability = probe.check()

        self.assertFalse(availability.any_available)
        # Two retrievers of one class must not collapse onto a single key, or
        # one refusal would silently overwrite the other.
        self.assertEqual(len(availability.errors), 2)

    def test_a_source_attribute_names_the_entry(self) -> None:
        class _Named(_Refusing):
            source = "arxiv"

        errors = RetrieverAvailabilityProbe(
            [_Named(RuntimeError("406"))]
        ).check().errors
        self.assertIn("arxiv", errors)

    def test_the_error_text_is_reduced_to_a_type(self) -> None:
        # A provider's own message can carry anything; only the exception type
        # is kept so nothing from a remote service is stored or logged.
        probe = RetrieverAvailabilityProbe(
            [_Refusing(RuntimeError("key=abc123 leaked into the message"))]
        )
        errors = probe.check().errors

        self.assertEqual(errors["_Refusing"], "RuntimeError")

    def test_max_results_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            RetrieverAvailabilityProbe([_Answering()], max_results=0)


class RefusalBeforeAnyModelCallTests(unittest.TestCase):
    """The probe has to run before the graph, which plans with the model."""

    def test_the_run_fails_without_invoking_the_graph(self) -> None:
        from paperguide.application import (
            InMemoryTaskStore,
            ResearchApplicationService,
            ResearchRequest,
        )

        class _ExplodingGraph:
            invoked = False

            def invoke(self, state):
                type(self).invoked = True
                raise AssertionError("the graph must not run without a source")

        class _NoSources:
            def check(self) -> SourceAvailability:
                return SourceAvailability(answered=(), errors={"Arxiv": "HTTPError"})

        service = ResearchApplicationService(
            _ExplodingGraph(),
            report_generator=object(),
            export_service=object(),
            task_store=InMemoryTaskStore(),
            source_probe=_NoSources(),
        )
        result = service.run(ResearchRequest(question="anything", max_papers=1))

        self.assertFalse(_ExplodingGraph.invoked)
        self.assertEqual(result.task.status.value, "failed")
        self.assertEqual(result.task.error, "NO_SOURCE_AVAILABLE")
        self.assertIsNone(result.report)
