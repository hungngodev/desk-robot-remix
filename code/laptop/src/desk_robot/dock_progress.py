"""Bound repeated approach pulses without granting motion authority."""


class DockApproachProgress:
    """Count observations that fail to improve the closest accepted range."""

    def __init__(self) -> None:
        self.best_distance_mm: float | None = None
        self.failed_attempts = 0

    def observe(self, distance_mm: float) -> bool:
        """Return True at the third consecutive non-improving observation."""
        if self.best_distance_mm is None or distance_mm < self.best_distance_mm:
            self.best_distance_mm = distance_mm
            self.failed_attempts = 0
        else:
            self.failed_attempts += 1
        return self.failed_attempts >= 3
