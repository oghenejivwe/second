"""Surviving a provider that says "not right now".

Strands' default ``ModelRetryStrategy`` retries exactly one exception type:
``ModelThrottledException``. Bedrock raises it. **Gemini does not** -- it raises
``google.genai.errors.ClientError`` for a 429 and ``ServerError`` for a 503, and
neither is retryable by default, so the graph dies mid-run on a transient refusal.

That is not a Gemini quirk. Every provider signals overload differently, and this
build may end up on any of them: the free tiers worth having are spread across
providers with incompatible SDKs. So the test here is deliberately **structural
rather than type-based** -- it asks what the provider is telling us, not which
class it used to say it.

Retried:
  429  rate limited / quota exhausted      "RESOURCE_EXHAUSTED", "rate limit"
  503  overloaded / temporarily unavailable "UNAVAILABLE", "high demand"
  529  overloaded (Anthropic's code)
  5xx  transient server failure

Not retried: 400, 401, 403, 404. A bad schema, a bad key or a missing model does
not get better by asking again, and retrying them burns a free tier's daily quota
on a request that cannot succeed.

**Failure direction matters here.** Retrying too little loses a run to a blip.
Retrying too much silently spends quota the user cannot see. On a free tier
capped per day, the second is worse -- so the attempt count is low and the errors
that can never succeed are excluded by design rather than by omission.

**Listen to the provider before guessing.** The second live Daily run died at the
Diagnostician even though the 429 was caught and retried, because a fixed
exponential ladder is the wrong instrument for a quota window. Gemini said:

    "Please retry in 40.513907697s"  ...  "retryDelay": "40s"

and we answered after 2s, then 4s -- two more requests thrown at a quota that had
not moved, and then we gave up 34 seconds early. The provider knew the answer and
was ignored.

So a stated delay wins over the ladder. And its *size* carries information the
status code does not: a per-minute window says "40s", an exhausted daily quota
says hours. Waiting out a minute is recovery; waiting out a day is a hang wearing
a retry costume.

**Some refusals are about the model, not the account.** The third live run got
past the quota wall and died on this instead:

    "This model is currently experiencing high demand."

*This* model. The sentence names its own scope, and the right answer to it is not
a longer wait -- it is a different model. Second already runs one model per node
to spread the per-model quota, so alternates exist and were sitting unused while
the graph died. When a refusal is model-scoped and an alternate is available, the
strategy swaps the model underneath the agent and retries at once.

That also rescues the case ``patience`` would otherwise refuse: a daily allowance
exhausted on ``gemini-3.7-flash`` says nothing whatsoever about
``gemini-3.5-flash``. Giving up there was correct only while there was nowhere
else to go.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Sequence
from typing import Any

from strands.event_loop._retry import ModelRetryStrategy

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
"""HTTP statuses worth asking again about."""

PERMANENT_STATUS = frozenset({400, 401, 403, 404, 422})
"""Statuses that will never succeed on a retry. Excluded explicitly, because a
schema the provider rejects would otherwise consume a whole daily quota."""

_SIGNALS = (
    "resource_exhausted",
    "rate limit",
    "ratelimit",
    "too many requests",
    "quota exceeded",
    "overloaded",
    "high demand",
    "unavailable",
    "try again later",
    "temporarily",
)


def _status_of(exception: Exception) -> int | None:
    """Dig a status code out of whatever shape the provider raised.

    Providers disagree about where this lives: an attribute, a nested response, or
    nothing but the message. Try each, then fall back to reading the text.
    """
    for attribute in ("status_code", "code", "http_status"):
        value = getattr(exception, attribute, None)
        if isinstance(value, int):
            return value

    response = getattr(exception, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value

    match = re.search(r"\b([45]\d{2})\b", str(exception)[:200])
    return int(match.group(1)) if match else None


_RETRY_HINT_PATTERNS = (
    # Google:  "retryDelay": "40s"   (also seen unquoted in repr'd dicts)
    re.compile(r"retry[_-]?delay\W{1,6}?(\d+(?:\.\d+)?)s", re.IGNORECASE),
    # Google prose / OpenAI prose: "Please retry in 40.513907697s"
    re.compile(r"retry (?:in|after)\s+(\d+(?:\.\d+)?)\s*s", re.IGNORECASE),
    # OpenAI-compatible: "try again in 1.5s" / "try again in 20ms"
    re.compile(r"try again in\s+(\d+(?:\.\d+)?)\s*s(?!\w)", re.IGNORECASE),
    # Header echoed into the message: "Retry-After: 40"
    re.compile(r"retry-after\W{1,4}(\d+(?:\.\d+)?)", re.IGNORECASE),
)


def _stated_delay(exception: Exception | None) -> float | None:
    """How long the provider itself said to wait, in seconds.

    Checked as an attribute first -- some SDKs surface the ``Retry-After`` header
    directly -- then by reading the message, because Google buries it in a JSON
    blob stringified into the exception text and nowhere else.

    Returns None when the provider said nothing, which is the common case and the
    one the exponential ladder exists for.
    """
    if exception is None:
        return None

    for attribute in ("retry_after", "retry_delay", "retry_after_seconds"):
        value = getattr(exception, attribute, None)
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)

    text = str(exception)[:4000]
    for pattern in _RETRY_HINT_PATTERNS:
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    return None


_MODEL_SCOPED_SIGNALS = (
    "this model is currently experiencing high demand",
    "the model is overloaded",
    "model is currently overloaded",
)
"""Phrasings that name the model as the thing that is unavailable.

Deliberately narrow. A generic "service unavailable" is about the provider, and
switching models cannot help; burning an alternate on it would spend the one
recovery that works when the real model-scoped failure arrives."""


def _names_a_model(exception: Exception) -> bool:
    """Whether the provider blamed a specific model rather than itself.

    Google's quota errors carry ``"model": "gemini-3.7-flash"`` inside
    ``quotaDimensions``, which is the machine-readable version of the same claim.
    """
    text = str(exception)[:4000].lower()
    if any(signal in text for signal in _MODEL_SCOPED_SIGNALS):
        return True
    return "quotadimensions" in text and '"model"' in text


class ResilientRetry(ModelRetryStrategy):
    """Retries on any provider's way of saying "busy", not just Bedrock's.

    Args:
        max_attempts: Total attempts including the first. Kept low on purpose --
            on a per-day quota, a long retry ladder spends requests invisibly.
        initial_delay: Seconds before the first retry; doubles thereafter. Used
            only when the provider states no delay of its own.
        max_delay: Ceiling on the backoff.
        patience: The longest stated wait worth sitting through. A provider
            asking for less than this is describing a per-minute window that will
            reopen; one asking for more is describing an exhausted allowance, and
            sleeping through that is a hang rather than a recovery.
        alternates: Other model ids this node may fall back to when the refusal
            names the model rather than the account. Consumed in order and never
            revisited -- a model that was overloaded ten seconds ago still is.
            Empty means the only recovery available is waiting.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 6,
        initial_delay: int = 4,
        max_delay: int = 240,
        patience: float = 65.0,
        alternates: Sequence[str] = (),
    ) -> None:
        super().__init__(
            max_attempts=max_attempts, initial_delay=initial_delay, max_delay=max_delay
        )
        self._patience = patience
        self._alternates = list(alternates)
        self._last_exception: Exception | None = None
        self._switched_to: str | None = None

    def is_retryable(self, exception: Exception) -> bool:
        """Whether this refusal is worth waiting out."""
        if self._switched_to is not None:
            return True  # the thing that refused is not the thing we will call

        stated = _stated_delay(exception)
        if stated is not None and stated > self._patience:
            if self._alternates:
                return True  # handled by the switch, which runs before this
            logger.warning(
                "not retrying %s: provider asked for %.0fs, longer than the %.0fs "
                "worth waiting -- this is an exhausted allowance, not a busy minute",
                type(exception).__name__,
                stated,
                self._patience,
            )
            return False

        if super().is_retryable(exception):
            return True

        status = _status_of(exception)
        if status in PERMANENT_STATUS:
            logger.info("not retrying %s: status %s will not change", type(exception).__name__, status)
            return False
        if status in RETRYABLE_STATUS:
            logger.warning("retrying after %s (status %s)", type(exception).__name__, status)
            return True

        text = str(exception).lower()
        if any(signal in text for signal in _SIGNALS):
            logger.warning("retrying after %s (matched an overload signal)", type(exception).__name__)
            return True

        return False

    # -- the delay itself ---------------------------------------------------

    async def _handle_after_model_call(self, event) -> None:  # type: ignore[no-untyped-def]
        """Remember what was raised, so the delay can be based on it.

        The base class computes the delay at the top of this method, before it has
        consulted ``is_retryable``, and ``_calculate_delay`` receives only an
        attempt number. Stashing the exception on the way in is the seam that lets
        the provider's own instruction reach the calculation without
        reimplementing the retry policy around it.
        """
        self._last_exception = event.exception
        self._switched_to = None

        if event.exception is not None and self._alternates and _names_a_model(event.exception):
            self._switch_model(event.agent, event.exception)

        await super()._handle_after_model_call(event)

    def _switch_model(self, agent: Any, exception: Exception) -> None:
        """Point the agent at the next alternate, in place.

        ``update_config`` is the provider-agnostic seam for this -- every Strands
        model exposes it -- so the swap works the same on Gemini and on anything
        OpenAI-compatible. The conversation so far is untouched and stays valid:
        the messages are the provider's format, not the model's.

        The attempt counter resets because a different model is a fresh chance,
        not a second go at the one that just refused. The loop is bounded by the
        alternates list rather than by the counter.
        """
        try:
            target = self._alternates.pop(0)
            agent.model.update_config(model_id=target)
        except Exception as failure:  # noqa: BLE001 - a failed switch must not mask the 503
            logger.warning("could not switch model: %s", failure)
            return

        self._switched_to = target
        self._current_attempt = 0
        logger.warning(
            "switching to %s -- %s named the model, not the account",
            target,
            type(exception).__name__,
        )

    def _calculate_delay(self, attempt: int) -> int:
        """The provider's stated wait if it gave one, otherwise the ladder.

        Rounded up with a second to spare: a quota window that reopens at 40.51s
        is not open at 40.51s, and landing exactly on the boundary spends a
        request to learn nothing.
        """
        if self._switched_to is not None:
            return 1  # a different model does not owe the old one's cooldown

        stated = _stated_delay(self._last_exception)
        if stated is None:
            return super()._calculate_delay(attempt)

        honoured = min(math.ceil(stated) + 1, math.ceil(self._patience))
        logger.warning(
            "waiting %ds -- %s asked for %.1fs",
            honoured,
            type(self._last_exception).__name__,
            stated,
        )
        return honoured

    def _reset_retry_state(self) -> None:
        """Forget the last refusal along with the attempt count."""
        super()._reset_retry_state()
        self._last_exception = None
        self._switched_to = None
        # _alternates is deliberately NOT restored: a model that was overloaded
        # a moment ago still is, and cycling back to it wastes the run.
