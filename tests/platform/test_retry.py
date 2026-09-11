"""Retrying what a provider can actually recover from, and nothing else.

Strands retries one exception type: ModelThrottledException. Gemini raises
google.genai.errors.ClientError for a 429, so nothing caught it and the graph died
mid-run. This is deliberately structural rather than type-based, because the free
tiers worth having are spread across providers with incompatible SDKs.
"""

from __future__ import annotations

import pytest

from second.core.retry import ResilientRetry


class FakeStatusError(Exception):
    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(message or f"{status} error")
        self.status_code = status


@pytest.fixture
def strategy() -> ResilientRetry:
    return ResilientRetry(max_attempts=3, initial_delay=1, max_delay=4)


@pytest.mark.parametrize("status", [429, 503, 529, 500, 502, 504])
def test_transient_refusals_are_retried(strategy, status):
    assert strategy.is_retryable(FakeStatusError(status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_permanent_failures_are_not_retried(strategy, status):
    """A rejected schema or a bad key does not improve on the second ask.

    This matters more than it looks: on a per-day quota, retrying something that
    can never succeed spends requests the user cannot see.
    """
    assert strategy.is_retryable(FakeStatusError(status)) is False


def test_a_status_buried_in_the_message_is_still_found(strategy):
    """Some providers put it nowhere but the text."""
    assert strategy.is_retryable(Exception("429 Too Many Requests. RESOURCE_EXHAUSTED")) is True


@pytest.mark.parametrize(
    "message",
    [
        "This model is currently experiencing high demand.",
        "Rate limit reached for requests",
        "The service is temporarily unavailable",
        "Overloaded",
        "quota exceeded for metric generate_content_free_tier_requests",
    ],
)
def test_overload_phrasing_is_recognised_without_a_status(strategy, message):
    """Providers disagree about status codes but agree about saying 'busy'."""
    assert strategy.is_retryable(Exception(message)) is True


def test_an_ordinary_bug_is_not_retried(strategy):
    assert strategy.is_retryable(ValueError("task_id must be a string")) is False
    assert strategy.is_retryable(KeyError("evidence")) is False


def test_a_permanent_status_wins_over_a_misleading_word(strategy):
    """A 400 that happens to mention a limit is still a 400."""
    assert strategy.is_retryable(FakeStatusError(400, "rate limit field is invalid")) is False


def test_the_real_gemini_429_shape_is_retried(strategy):
    """The actual error that killed the first live Daily run."""
    real = Exception(
        "429 Too Many Requests. {'message': '{\"error\": {\"code\": 429, \"message\": "
        '"You exceeded your current quota", "status": "RESOURCE_EXHAUSTED"}}\'}'
    )
    assert strategy.is_retryable(real) is True


def test_the_real_gemini_503_shape_is_retried(strategy):
    real = Exception(
        "503 Service Unavailable. {'message': '{\"error\": {\"code\": 503, \"message\": "
        '"This model is currently experiencing high demand."}}\'}'
    )
    assert strategy.is_retryable(real) is True
