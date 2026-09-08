from __future__ import annotations

from dataclasses import dataclass


STATE_EMPTY = 0
STATE_FREYA = 1
STATE_FINN = 2
STATE_MULTIPLE = 3
STATE_UNKNOWN_HAWK = 4

# Backwards-compatible alias for code/tests written against the first refactor.
STATE_BOTH = STATE_MULTIPLE


@dataclass(frozen=True)
class StableTransition:
    state_code: int
    status: str
    hawk_count: int
    event_type: str


class NestStateMachine:
    """Debounce noisy detector output into a stable nest state."""

    def __init__(self, empty_confirmations: int = 8, state_confirmations: int = 3) -> None:
        self.empty_confirmations = max(1, empty_confirmations)
        self.state_confirmations = max(1, state_confirmations)
        self.stable_state: int | None = None
        self.pending_state: int | None = None
        self.pending_count = 0
        self.empty_count = 0

    def _candidate(self, hawk_count: int, identity: str) -> int | None:
        if hawk_count <= 0:
            self.empty_count += 1
            if self.empty_count < self.empty_confirmations:
                return None
            return STATE_EMPTY

        self.empty_count = 0
        if hawk_count >= 2:
            return STATE_MULTIPLE
        if identity == "freya":
            return STATE_FREYA
        if identity == "finn":
            return STATE_FINN
        return STATE_UNKNOWN_HAWK

    @staticmethod
    def describe(state_code: int) -> tuple[str, int]:
        if state_code == STATE_EMPTY:
            return "Nest appears empty", 0
        if state_code == STATE_FREYA:
            return "Freya (Female) is in the nest!", 1
        if state_code == STATE_FINN:
            return "Finn (Male) is in the nest!", 1
        if state_code == STATE_MULTIPLE:
            return "Multiple birds are in the nest", 2
        return "A hawk is in the nest (identity uncertain)", 1

    @classmethod
    def event_type_for(cls, previous: int | None, current: int) -> str:
        if previous is None:
            return "initial_state"

        _, previous_count = cls.describe(previous)
        _, current_count = cls.describe(current)

        if previous_count == 0 and current_count > 0:
            return "arrival"
        if previous_count > 0 and current_count == 0:
            return "departure"
        if previous_count < 2 and current_count >= 2:
            return "multiple_present"
        if previous_count >= 2 and current_count == 1:
            return "one_remaining"
        if previous_count == current_count == 1 and previous != current:
            return "identity_change"
        return "state_change"

    def _transition(self, previous: int | None, current: int) -> StableTransition:
        status, count = self.describe(current)
        return StableTransition(
            state_code=current,
            status=status,
            hawk_count=count,
            event_type=self.event_type_for(previous, current),
        )

    def update(self, hawk_count: int, identity: str = "unknown") -> StableTransition | None:
        candidate = self._candidate(hawk_count, identity)
        if candidate is None:
            return None

        if self.stable_state is None:
            previous = self.stable_state
            self.stable_state = candidate
            self.pending_state = None
            self.pending_count = 0
            return self._transition(previous, candidate)

        if candidate == self.stable_state:
            self.pending_state = None
            self.pending_count = 0
            return None

        if candidate == self.pending_state:
            self.pending_count += 1
        else:
            self.pending_state = candidate
            self.pending_count = 1

        if self.pending_count < self.state_confirmations:
            return None

        previous = self.stable_state
        self.stable_state = candidate
        self.pending_state = None
        self.pending_count = 0
        return self._transition(previous, candidate)

    @property
    def stable_status(self) -> str | None:
        if self.stable_state is None:
            return None
        return self.describe(self.stable_state)[0]
