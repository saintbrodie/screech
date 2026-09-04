from backend.state import NestStateMachine, STATE_EMPTY, STATE_FREYA


def test_initial_non_empty_state_commits_immediately():
    machine = NestStateMachine(empty_confirmations=2, state_confirmations=2)
    transition = machine.update(1, "freya")
    assert transition is not None
    assert transition.state_code == STATE_FREYA
    assert machine.stable_status == "Freya (Female) is in the nest!"


def test_empty_state_requires_empty_confirmation_then_transition_debounce():
    machine = NestStateMachine(empty_confirmations=2, state_confirmations=2)
    machine.update(1, "freya")

    assert machine.update(0) is None
    assert machine.update(0) is None
    transition = machine.update(0)

    assert transition is not None
    assert transition.state_code == STATE_EMPTY


def test_transient_identity_jitter_does_not_change_stable_state():
    machine = NestStateMachine(empty_confirmations=1, state_confirmations=3)
    machine.update(1, "freya")

    assert machine.update(1, "finn") is None
    assert machine.update(1, "freya") is None
    assert machine.stable_state == STATE_FREYA
