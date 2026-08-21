class TraceCollector:
    """Collects text fragments and assembles them into a complete trace string.

    The collector is stack‑agnostic and does not depend on ESPHome,
    ESP32, or any specific framework.
    """

    def __init__(self):
        self._parts: list[str] = []

    def feed(self, data: str) -> None:
        """Append a text fragment to the collected trace."""
        self._parts.append(data)

    def get_trace(self) -> str:
        """Return the complete trace assembled from all fragments fed so far."""
        return "".join(self._parts)

    def clear(self) -> None:
        """Remove all previously collected fragments."""
        self._parts.clear()
