import re


class TraceAnalyzer:
    """Analyzes a trace (log text) against a set of conditions.

    The analyzer is stack‑agnostic and does not depend on ESPHome,
    ESP32, or any specific framework.
    """

    def __init__(self, trace: str):
        self._trace = trace
        self._errors: list[str] = []

    # ------------------------------------------------------------------
    # Public condition methods
    # ------------------------------------------------------------------

    def expect_text(self, text: str) -> "TraceAnalyzer":
        """Assert that *text* appears somewhere in the trace."""
        if text not in self._trace:
            self._errors.append(
                f"Expected text '{text}' not found in trace."
            )
        return self

    def forbid_text(self, text: str) -> "TraceAnalyzer":
        """Assert that *text* does NOT appear anywhere in the trace."""
        if text in self._trace:
            self._errors.append(
                f"Forbidden text '{text}' found in trace."
            )
        return self

    def expect_sequence(self, texts: list[str]) -> "TraceAnalyzer":
        """Assert that the given texts appear in the trace in the given order.

        The texts may be separated by other content.
        """
        pos = 0
        for text in texts:
            idx = self._trace.find(text, pos)
            if idx == -1:
                self._errors.append(
                    f"Expected text '{text}' in sequence not found "
                    f"after position {pos}."
                )
                return self
            pos = idx + len(text)
        return self

    def expect_value(
        self,
        pattern: str,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> "TraceAnalyzer":
        """Assert that a numeric value matching *pattern* lies within
        the given range.

        The pattern must contain exactly one capture group that extracts
        a floating‑point number.
        """
        match = re.search(pattern, self._trace)
        if not match:
            self._errors.append(
                f"Pattern '{pattern}' did not match any value in trace."
            )
            return self

        try:
            value = float(match.group(1))
        except (ValueError, IndexError):
            self._errors.append(
                f"Could not extract a numeric value from pattern "
                f"'{pattern}' (match groups: {match.groups()})."
            )
            return self

        if minimum is not None and value < minimum:
            self._errors.append(
                f"Value {value} is below minimum {minimum} "
                f"(pattern '{pattern}')."
            )
        if maximum is not None and value > maximum:
            self._errors.append(
                f"Value {value} exceeds maximum {maximum} "
                f"(pattern '{pattern}')."
            )
        return self

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def result(self) -> dict:
        """Return the analysis result.

        Returns:
            dict with keys:
                success (bool): True if all conditions passed.
                errors (list[str]): List of error messages.
        """
        success = len(self._errors) == 0
        return {"success": success, "errors": list(self._errors)}
