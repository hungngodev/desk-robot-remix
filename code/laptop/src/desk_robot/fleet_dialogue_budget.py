"""One rolling allowance for group dialogue, independent of session lifetime."""

import time
from collections import deque
from collections.abc import Callable

_GROUP_WINDOW_S = 300.0


def group_utterance_limit(group_size: int) -> int:
    if type(group_size) is not int or not 2 <= group_size <= 5:
        raise ValueError("Choose two to five distinct robots")
    return max(6, 2 * group_size)


class RollingGroupBudget:
    """Count attempted logical utterances, not individual audio chunks.

    Owned by the single Mac Conversation instance on its event loop. A new
    topic, participant list or cancellation never resets the allowance.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._attempts: deque[float] = deque()

    def remaining(self, group_size: int) -> int:
        limit = group_utterance_limit(group_size)
        cutoff = self._clock() - _GROUP_WINDOW_S
        while self._attempts and self._attempts[0] <= cutoff:
            self._attempts.popleft()
        return max(0, limit - len(self._attempts))

    def claim(self, group_size: int) -> None:
        if not self.remaining(group_size):
            raise RuntimeError("Rolling fleet dialogue budget exhausted")
        self._attempts.append(self._clock())
