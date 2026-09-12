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
says hours. Above ``patience`` we stop retrying entirely rather than sleeping
through the run -- waiting out a minute is recovery, waiting out a day is a hang
wearing a retry costume.
"""

from __future__ import annotations

import logging
import math
import re

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
    """

    def __init__(
        self,
        *,
        max_attempts: int = 6,
        initial_delay: int = 4,
        max_delay: int = 240,
        patience: float = 65.0,
    ) -> None:
        super().__init__(
            max_attempts=max_attempts, initial_delay=initial_delay, max_delay=max_delay
        )
        self._patience = patience
        self._last_exception: Exception | None = None

    def is_retryable(self, exception: Exception) -> bool:
        """Whether this refusal is worth waiting out."""
        stated = _stated_delay(exception)
        if stated is not None and stated > self._patience:
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
        await super()._handle_after_model_call(event)

    def _calculate_delay(self, attempt: int) -> int:
        """The provider's stated wait if it gave one, otherwise the ladder.

        Rounded up with a second to spare: a quota window that reopens at 40.51s
        is not open at 40.51s, and landing exactly on the boundary spends a
        request to learn nothing.
        """
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
