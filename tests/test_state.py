from backend.state import NestStateMachine, STATE_EMPTY, STATE_FREYA, STATE_MULTIPLE


def test_initial_non_empty_state_commits_as_initial_state():
    machine = NestStateMachine(empty_confirmations=2, state_confirmations=2)
    transition = machine.update(1, "freya")
    assert transition is not None
    assert transition.state_code == STATE_FREYA
    assert transition.event_type == "initial_state"
    assert machine.stable_status == "Freya (Female) is in the nest!"


def test_empty_state_requires_empty_confirmation_then_logs_departure():
    machine = NestStateMachine(empty_confirmations=2, state_confirmations=2)
    machine.update(1, "freya")

    assert machine.update(0) is None
    assert machine.update(0) is None
    transition = machine.update(0)

    assert transition is not None
    assert transition.state_code == STATE_EMPTY
    assert transition.event_type == "departure"


def test_transient_identity_jitter_does_not_change_stable_state():
    machine = NestStateMachine(empty_confirmations=1, state_confirmations=3)
    machine.update(1, "freya")

    assert machine.update(1, "finn") is None
    assert machine.update(1, "freya") is None
    assert machine.stable_state == STATE_FREYA


def test_multiple_generic_birds_do_not_claim_freya_and_finn():
    machine = NestStateMachine(empty_confirmations=1, state_confirmations=1)
    transition = machine.update(2, "unknown")

    assert transition is not None
    assert transition.state_code == STATE_MULTIPLE
    assert transition.event_type == "initial_state"
    assert "Freya" not in transition.status
    assert "Finn" not in transition.status


def test_transition_to_multiple_is_classified_separately():
    machine = NestStateMachine(empty_confirmations=1, state_confirmations=1)
    machine.update(1, "unknown")
    transition = machine.update(2, "unknown")

    assert transition is not None
    assert transition.event_type == "multiple_present"
