import pytest
from app.trace_analyzer import TraceAnalyzer


class TestTraceAnalyzer:

    # ------------------------------------------------------------------
    # Helper traces
    # ------------------------------------------------------------------
    @pytest.fixture
    def normal_trace(self) -> str:
        return (
            "[D][fsm]: Update aktiv, State: RUNNING\n"
            "[I][sensor]: Temperatur: 23.4 °C\n"
            "[I][wifi]: Connected\n"
        )

    @pytest.fixture
    def empty_trace(self) -> str:
        return ""

    # ------------------------------------------------------------------
    # 1. expected text present -> PASS
    # ------------------------------------------------------------------
    def test_expect_text_present(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .expect_text("State: RUNNING")
            .result()
        )
        assert result["success"] is True
        assert result["errors"] == []

    # ------------------------------------------------------------------
    # 2. expected text missing -> FAIL
    # ------------------------------------------------------------------
    def test_expect_text_missing(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .expect_text("State: ERROR")
            .result()
        )
        assert result["success"] is False
        assert any("Expected text" in err for err in result["errors"])

    # ------------------------------------------------------------------
    # 3. correct sequence -> PASS
    # ------------------------------------------------------------------
    def test_expect_sequence_correct(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .expect_sequence([
                "State: RUNNING",
                "Temperatur: 23.4 °C",
                "Connected",
            ])
            .result()
        )
        assert result["success"] is True

    # ------------------------------------------------------------------
    # 4. wrong sequence order -> FAIL
    # ------------------------------------------------------------------
    def test_expect_sequence_wrong_order(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .expect_sequence([
                "Connected",
                "State: RUNNING",
            ])
            .result()
        )
        assert result["success"] is False
        assert any("sequence" in err for err in result["errors"])

    # ------------------------------------------------------------------
    # 5. forbidden text present -> FAIL
    # ------------------------------------------------------------------
    def test_forbid_text_present(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .forbid_text("Connected")
            .result()
        )
        assert result["success"] is False
        assert any("Forbidden text" in err for err in result["errors"])

    # ------------------------------------------------------------------
    # 6. forbidden text absent -> PASS
    # ------------------------------------------------------------------
    def test_forbid_text_absent(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .forbid_text("ERROR")
            .result()
        )
        assert result["success"] is True

    # ------------------------------------------------------------------
    # 7. numeric value within range -> PASS
    # ------------------------------------------------------------------
    def test_expect_value_within_range(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .expect_value(
                pattern=r"Temperatur: ([0-9.]+)",
                minimum=20.0,
                maximum=25.0,
            )
            .result()
        )
        assert result["success"] is True

    # ------------------------------------------------------------------
    # 8. numeric value outside range -> FAIL
    # ------------------------------------------------------------------
    def test_expect_value_outside_range(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .expect_value(
                pattern=r"Temperatur: ([0-9.]+)",
                minimum=30.0,
                maximum=40.0,
            )
            .result()
        )
        assert result["success"] is False
        assert any("below minimum" in err for err in result["errors"])

    # ------------------------------------------------------------------
    # 9. multiple successful conditions -> PASS
    # ------------------------------------------------------------------
    def test_multiple_successful_conditions(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .expect_text("State: RUNNING")
            .expect_text("Connected")
            .forbid_text("ERROR")
            .expect_value(
                pattern=r"Temperatur: ([0-9.]+)",
                minimum=20.0,
                maximum=25.0,
            )
            .result()
        )
        assert result["success"] is True

    # ------------------------------------------------------------------
    # 10. multiple errors are reported
    # ------------------------------------------------------------------
    def test_multiple_errors(self, normal_trace: str):
        result = (
            TraceAnalyzer(normal_trace)
            .expect_text("State: ERROR")
            .forbid_text("Connected")
            .expect_value(
                pattern=r"Temperatur: ([0-9.]+)",
                minimum=30.0,
                maximum=40.0,
            )
            .result()
        )
        assert result["success"] is False
        # At least three distinct errors
        assert len(result["errors"]) >= 3

    # ------------------------------------------------------------------
    # 11. empty trace is handled cleanly
    # ------------------------------------------------------------------
    def test_empty_trace(self, empty_trace: str):
        result = (
            TraceAnalyzer(empty_trace)
            .expect_text("anything")
            .forbid_text("nothing")
            .result()
        )
        assert result["success"] is False
        assert any("Expected text" in err for err in result["errors"])

    # ------------------------------------------------------------------
    # 12. normal ESPHome‑like log text can be processed
    # ------------------------------------------------------------------
    def test_esphome_like_log(self):
        trace = (
            "[D][fsm]: Update aktiv, State: STARTING\n"
            "[I][sensor]: Temperatur: 22.1 °C\n"
            "[D][fsm]: Update aktiv, State: RUNNING\n"
            "[W][sensor]: Retry 1\n"
            "[I][wifi]: Connected\n"
        )
        result = (
            TraceAnalyzer(trace)
            .expect_sequence([
                "State: STARTING",
                "State: RUNNING",
                "Connected",
            ])
            .forbid_text("ERROR")
            .expect_value(
                pattern=r"Temperatur: ([0-9.]+)",
                minimum=20.0,
                maximum=25.0,
            )
            .result()
        )
        assert result["success"] is True
