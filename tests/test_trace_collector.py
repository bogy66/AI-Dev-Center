import pytest
from app.trace_collector import TraceCollector


class TestTraceCollector:

    def test_new_collector_has_empty_trace(self):
        collector = TraceCollector()
        assert collector.get_trace() == ""

    def test_single_feed_is_stored(self):
        collector = TraceCollector()
        collector.feed("Hello, world!")
        assert collector.get_trace() == "Hello, world!"

    def test_multiple_feeds_are_concatenated_in_order(self):
        collector = TraceCollector()
        collector.feed("[D][fsm]: START\n")
        collector.feed("[I][wifi]: Connected\n")
        collector.feed("[D][fsm]: STOP\n")
        expected = "[D][fsm]: START\n[I][wifi]: Connected\n[D][fsm]: STOP\n"
        assert collector.get_trace() == expected

    def test_empty_feed_does_nothing(self):
        collector = TraceCollector()
        collector.feed("")
        assert collector.get_trace() == ""

    def test_unicode_is_preserved(self):
        collector = TraceCollector()
        collector.feed("Temperatur: 23.4 °C\n")
        assert collector.get_trace() == "Temperatur: 23.4 °C\n"

    def test_clear_empties_trace(self):
        collector = TraceCollector()
        collector.feed("some data")
        collector.clear()
        assert collector.get_trace() == ""

    def test_after_clear_can_collect_again(self):
        collector = TraceCollector()
        collector.feed("first")
        collector.clear()
        collector.feed("second")
        assert collector.get_trace() == "second"

    def test_newlines_are_preserved(self):
        collector = TraceCollector()
        collector.feed("line1\n")
        collector.feed("line2\n")
        assert collector.get_trace() == "line1\nline2\n"

    def test_esphome_like_logs_are_collected_unchanged(self):
        collector = TraceCollector()
        collector.feed("[D][fsm]: Update aktiv, State: STARTING\n")
        collector.feed("[I][sensor]: Temperatur: 22.1 °C\n")
        collector.feed("[D][fsm]: Update aktiv, State: RUNNING\n")
        collector.feed("[W][sensor]: Retry 1\n")
        collector.feed("[I][wifi]: Connected\n")
        expected = (
            "[D][fsm]: Update aktiv, State: STARTING\n"
            "[I][sensor]: Temperatur: 22.1 °C\n"
            "[D][fsm]: Update aktiv, State: RUNNING\n"
            "[W][sensor]: Retry 1\n"
            "[I][wifi]: Connected\n"
        )
        assert collector.get_trace() == expected

    def test_large_number_of_fragments(self):
        collector = TraceCollector()
        fragments = [f"line{i}\n" for i in range(1000)]
        for frag in fragments:
            collector.feed(frag)
        expected = "".join(fragments)
        assert collector.get_trace() == expected
