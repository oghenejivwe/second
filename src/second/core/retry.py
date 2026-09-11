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
"""

from __future__ import annotations

import logging
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


class ResilientRetry(ModelRetryStrategy):
    """Retries on any provider's way of saying "busy", not just Bedrock's.

    Args:
        max_attempts: Total attempts including the first. Kept low on purpose --
            on a per-day quota, a long retry ladder spends requests invisibly.
        initial_delay: Seconds before the first retry; doubles thereafter.
        max_delay: Ceiling on the backoff.
    """

    def is_retryable(self, exception: Exception) -> bool:
        """Whether this refusal is worth waiting out."""
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
