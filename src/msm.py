"""Manager state machine for the backend lifecycle."""

import logging
from enum import Enum

log = logging.getLogger("manager")


class State(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    OPERATIONAL = "operational"
    ERROR = "error"
    RECOVERING = "recovering"


state = State.STOPPED
last_error = None

# Compatibility flags for existing code while it moves to ``state``.
operationalstate = False
errorstate = False
toggleallow = True
errordetected = False

_TRANSITIONS = {
    State.STOPPED: {State.STARTING},
    State.STARTING: {State.OPERATIONAL, State.ERROR, State.STOPPED},
    State.OPERATIONAL: {State.ERROR, State.STOPPED},
    State.ERROR: {State.RECOVERING, State.STOPPED},
    State.RECOVERING: {State.OPERATIONAL, State.ERROR, State.STOPPED},
}


def transition(new_state):
    """Move to a valid lifecycle state and return it."""
    global state, operationalstate, errorstate, errordetected

    new_state = State(new_state)
    if new_state == state:
        return state
    if new_state not in _TRANSITIONS[state]:
        raise ValueError(f"Invalid lifecycle transition: {state.value} -> {new_state.value}")

    log.info("state %s -> %s", state.value, new_state.value)
    state = new_state
    operationalstate = state is State.OPERATIONAL
    errorstate = state is State.ERROR
    errordetected = errorstate
    return state


def start():
    """Enter startup; callers mark startup complete or failed explicitly."""
    return transition(State.STARTING)


def startup_succeeded():
    return transition(State.OPERATIONAL)


def enter_error(error=None):
    global last_error
    last_error = error
    return transition(State.ERROR)


def begin_recovery():
    return transition(State.RECOVERING)


def recovery_succeeded():
    global last_error
    last_error = None
    return transition(State.OPERATIONAL)


def recovery_failed(error=None):
    global last_error
    if error is not None:
        last_error = error
    return transition(State.ERROR)


def shutdown():
    return transition(State.STOPPED)


def togglestate():
    """Compatibility wrapper for the former operational/error toggle."""
    if not toggleallow:
        return False
    if state is State.OPERATIONAL:
        enter_error()
    elif state is State.ERROR:
        begin_recovery()
    else:
        return False
    return True


def initial_msm():
    """Compatibility startup helper; initialize directly as operational."""
    global state, operationalstate, errorstate, errordetected
    if state is State.STOPPED:
        transition(State.STARTING)
    if state is State.STARTING:
        transition(State.OPERATIONAL)
    operationalstate = state is State.OPERATIONAL
    errorstate = state is State.ERROR
    errordetected = errorstate
    return state


def print_state():
    print(state.value)


def errorcheck():
    """Placeholder for the future watchdog; no checks are implemented yet."""
    return errordetected


def hardstop():
    """Placeholder for stopping active work; state transition is immediate."""
    if state is State.OPERATIONAL:
        return enter_error(last_error)
    return state
