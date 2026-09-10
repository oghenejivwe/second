"""The scheduler shim's pure logic. No AWS involved.

Two of these catch bugs that read like something else entirely: a session id one
character short raises a ValidationException that looks like a permissions
problem, and a Function URL body arrives JSON-encoded inside a string while a
Scheduler event does not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))

from lambda_shim import _payload_from, _response, new_session_id  # noqa: E402


def test_a_session_id_is_long_enough_for_the_service_model():
    """SessionType has min:33. uuid4().hex is 32 and throws.

    This is the five-minute bug that reads like a permissions problem.
    """
    session_id = new_session_id()
    assert len(session_id) >= 33, f"{session_id!r} is {len(session_id)} chars"
    assert len(session_id) == 36


def test_session_ids_are_distinct():
    assert new_session_id() != new_session_id()


def test_a_scheduler_event_is_read_directly():
    parsed = _payload_from({"action": "daily"})
    assert parsed == {"trigger": "schedule", "action": "daily"}


def test_a_function_url_event_is_unwrapped_from_its_body():
    """The judge's 'run now' button. Same handler, same code path."""
    event = {"body": json.dumps({"action": "daily"}), "requestContext": {"http": {"method": "POST"}}}
    assert _payload_from(event) == {"trigger": "manual", "action": "daily"}


@pytest.mark.parametrize("body", ["", "not json at all", "{"])
def test_a_malformed_body_degrades_to_a_default_run(body):
    """Failure direction: run the default, do not crash the schedule."""
    parsed = _payload_from({"body": body})
    assert parsed == {"trigger": "manual"}


def test_both_triggers_reach_the_same_action():
    scheduled = _payload_from({"action": "daily"})
    manual = _payload_from({"body": json.dumps({"action": "daily"})})

    assert scheduled["action"] == manual["action"], (
        "the demo button and the 07:00 schedule must run identical code"
    )
    assert scheduled["trigger"] != manual["trigger"], "only the trigger differs"


def test_a_response_is_function_url_shaped():
    response = _response(200, {"ok": True})
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "application/json"
    assert json.loads(response["body"]) == {"ok": True}
