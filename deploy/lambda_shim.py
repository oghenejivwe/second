"""EventBridge Scheduler -> AgentCore. The only way in.

**A Scheduler universal target cannot invoke an AgentCore runtime.** This is
structural, not a limitation someone forgot to test: ``InvokeAgentRuntime`` takes
``runtimeSessionId`` and ``runtimeUserId`` as HTTP *headers*
(``X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`` / ``-User-Id``) and the payload
as a *blob body*. Scheduler's Input is a JSON map of API parameters and can
express neither. Separately, its universal target is synchronous and abandons the
call at roughly 30 seconds, dead-lettering runs that actually succeeded.

So: Scheduler -> this Lambda -> boto3. The same handler also sits behind a
Function URL so a judge can press "run today's cycle now" -- **both paths execute
identical code**, differing only by a ``trigger`` field, so the thing demonstrated
on stage is the thing that runs at 07:00.

Deploy notes:

* Set ``MaximumRetryAttempts=0`` on the Scheduler target. The daily run is not
  idempotent -- it drafts mail and moves calendar entries -- and a retried run
  would do it twice.
* Give this Lambda a timeout above the runtime's cold start plus the graph's own
  ceiling. 300s is the working figure; the graph itself is capped at 300s by
  ``GRAPH_TIMEOUT_SECONDS``.
* Its execution role needs ``bedrock-agentcore:InvokeAgentRuntime`` on the
  runtime ARN, and nothing else.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")
REGION = os.environ.get("AWS_REGION", "us-west-2")
DEMO_USER_ID = os.environ.get("SECOND_USER_ID", "demo")

_client = None


def client():
    """The AgentCore data-plane client, built once per container."""
    global _client
    if _client is None:
        _client = boto3.client("bedrock-agentcore", region_name=REGION)
    return _client


def new_session_id() -> str:
    """A session id AgentCore will accept.

    ``SessionType`` has ``min: 33`` in the service model. ``uuid4().hex`` is 32
    characters and raises ``ValidationException`` -- the hyphenated form is 36 and
    does not. This is a five-minute bug that reads like a permissions problem.
    """
    return str(uuid.uuid4())


def _payload_from(event: dict[str, Any]) -> dict[str, Any]:
    """Work out what to run, from either trigger.

    A Scheduler event carries our own JSON directly. A Function URL event wraps
    the caller's JSON in ``body`` as a string. Both end up here.
    """
    if isinstance(event.get("body"), str):
        try:
            body = json.loads(event["body"] or "{}")
        except json.JSONDecodeError:
            body = {}
        return {"trigger": "manual", **body}
    return {"trigger": "schedule", **event}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Invoke the deployed agent and return its result.

    Returns a Function-URL-shaped response so one handler serves both triggers.
    Errors are returned rather than raised: a scheduled run that fails should
    show up as a logged failure, not as a Lambda error metric that pages nobody
    at 07:00.
    """
    if not AGENT_RUNTIME_ARN:
        logger.error("AGENT_RUNTIME_ARN is not set")
        return _response(500, {"ok": False, "error": "AGENT_RUNTIME_ARN is not configured"})

    request = _payload_from(event)
    trigger = request.pop("trigger", "schedule")
    action = request.get("action", "daily")
    session_id = new_session_id()

    logger.info("trigger=%s action=%s session=%s", trigger, action, session_id)

    try:
        response = client().invoke_agent_runtime(
            agentRuntimeArn=AGENT_RUNTIME_ARN,
            runtimeSessionId=session_id,
            runtimeUserId=DEMO_USER_ID,
            payload=json.dumps({"action": action, **request}).encode("utf-8"),
        )
    except Exception as error:  # noqa: BLE001 - the schedule must not page anyone
        logger.exception("invoke failed")
        return _response(502, {"ok": False, "trigger": trigger, "error": str(error)})

    body = response.get("response")
    raw = body.read() if hasattr(body, "read") else body
    try:
        result = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        result = {"raw": raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)}

    logger.info("ok trigger=%s notify=%s", trigger, result.get("brief", {}).get("notify"))
    return _response(200, {"ok": True, "trigger": trigger, "session_id": session_id, "result": result})


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=str),
    }
