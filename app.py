"""The Bedrock AgentCore entrypoint.

One deployed runtime, three actions -- the daily cycle, voice intake, and
feedback. Everything behind it is ``second.graphs.service``, so the deployed path
and the local path run identical code.

**The payload guard below is a security control, not input tidying.**

An AgentCore runtime receives the request body as parsed JSON *of any type*. If a
prompt is passed through to the framework without a type check, a caller can send
a structured content block naming a tool instead of a string -- and the framework
will execute that tool directly, skipping the model's reasoning and every
guardrail that lives in the prompt. For a read-only chatbot that is untidy. For
an agent that drafts mail and moves calendar entries, it is a live authorization
hole. So: the prompt must be a string, or the request is refused.

Failure direction throughout: refuse and say why. A refused invocation is a line
in CloudWatch; an invocation that did something unintended is a calendar the user
no longer trusts.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from second.graphs import service
from second.settings import DEMO_USER_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("second")

app = BedrockAgentCoreApp()

ACTIONS = ("daily", "intake", "feedback")
MAX_PROMPT_CHARS = 20_000


class InvalidPayload(ValueError):
    """The request was not something this runtime will act on."""


def parse_payload(payload: Any) -> tuple[str, str, date | None]:
    """Validate an incoming payload into (action, prompt, today).

    Args:
        payload: Whatever the runtime handed us. Explicitly untrusted, and
            explicitly not assumed to be a dict.

    Returns:
        The action to run, the prompt string, and an optional date override.

    Raises:
        InvalidPayload: On anything unexpected -- a non-dict body, an unknown
            action, a missing prompt, a prompt that is not a string, or one that
            is too long.
    """
    if not isinstance(payload, dict):
        raise InvalidPayload(f"body must be a JSON object, got {type(payload).__name__}")

    action = payload.get("action", "daily")
    if action not in ACTIONS:
        raise InvalidPayload(f"unknown action {action!r}; expected one of {ACTIONS}")

    prompt = payload.get("prompt", "")

    # The guard. A structured content block here would be executed as a tool call.
    if not isinstance(prompt, str):
        raise InvalidPayload(
            f"prompt must be a string, got {type(prompt).__name__}. "
            "Structured content is not accepted on this runtime."
        )
    if len(prompt) > MAX_PROMPT_CHARS:
        raise InvalidPayload(f"prompt is {len(prompt)} chars; the limit is {MAX_PROMPT_CHARS}")

    if action == "intake" and not prompt.strip():
        raise InvalidPayload("intake needs a transcript")
    if action == "feedback" and not prompt.strip():
        raise InvalidPayload("feedback needs something the user said")

    raw_date = payload.get("today")
    if raw_date is not None and not isinstance(raw_date, str):
        raise InvalidPayload("today must be an ISO 8601 date string")
    today = date.fromisoformat(raw_date) if raw_date else None

    return action, prompt, today


@app.entrypoint
async def invoke(payload: Any) -> dict[str, Any]:
    """Run one action and return a JSON-serialisable result.

    Errors are returned rather than raised so the caller sees a clear reason
    instead of a 500 with a stack trace, and so a scheduled run that fails does
    not look like an outage.
    """
    try:
        action, prompt, today = parse_payload(payload)
    except InvalidPayload as error:
        logger.warning("rejected payload: %s", error)
        return {"ok": False, "error": str(error)}

    user_id = DEMO_USER_ID
    logger.info("action=%s user=%s", action, user_id)

    try:
        if action == "daily":
            card = await service.run_daily(user_id, today)
            return {
                "ok": True,
                "action": "daily",
                # None is the common case and it is correct: Second had nothing
                # worth interrupting the user about.
                "card": card.model_dump(mode="json") if card else None,
                "spoke": card is not None,
            }

        if action == "intake":
            result = await service.run_intake(user_id, prompt, today=today)
            return {"ok": True, "action": "intake", "result": result.model_dump(mode="json")}

        feedback = await service.run_feedback(user_id, prompt, today=today)
        return {"ok": True, "action": "feedback", "result": feedback.model_dump(mode="json")}

    except Exception as error:  # noqa: BLE001 - the runtime must answer, not crash
        logger.exception("action %s failed", action)
        return {"ok": False, "action": action, "error": f"{type(error).__name__}: {error}"}


if __name__ == "__main__":
    app.run()
