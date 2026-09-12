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


# -- the trap that looks like the obvious path ------------------------------


def test_a_provider_that_discards_forced_tool_choice_is_refused():
    """Six Strands providers accept a tool choice and throw it away.

    mistral, ollama, llamacpp, llamaapi, writer and sagemaker all call
    warn_on_tool_choice_not_supported and then drop it -- a Python warning and
    nothing else. `strands-agents[mistral]` plus MistralModel(...) installs
    clean, runs clean, and silently un-forces every structured output.

    Second routes on a typed field, so that failure is not an error. It is a
    routing decision made on a field nothing filled in. Refusing at construction
    is the only place it can be caught.
    """
    from second.graphs.composition import ModelProviderNotConfigured, build_model
    from second.settings import TOOL_CHOICE_DISCARDING_PROVIDERS

    for provider in sorted(TOOL_CHOICE_DISCARDING_PROVIDERS):
        with pytest.raises(ModelProviderNotConfigured) as excinfo:
            build_model(provider=provider)
        assert "discards forced tool choice" in str(excinfo.value)


def test_the_discard_list_matches_the_installed_sdk():
    """Pinned to reality, so an SDK upgrade that fixes one of these shows up here."""
    import pathlib

    from second.settings import TOOL_CHOICE_DISCARDING_PROVIDERS

    models_dir = pathlib.Path("src").resolve().parent / ".venv/Lib/site-packages/strands/models"
    if not models_dir.exists():
        pytest.skip("installed SDK not found")

    discarding = {
        path.stem
        for path in models_dir.glob("*.py")
        if not path.stem.startswith("_")
        and "warn_on_tool_choice_not_supported" in path.read_text(encoding="utf-8")
    }
    assert discarding == set(TOOL_CHOICE_DISCARDING_PROVIDERS), (
        f"the SDK changed: installed={sorted(discarding)} "
        f"expected={sorted(TOOL_CHOICE_DISCARDING_PROVIDERS)}"
    )


def test_an_openai_compatible_provider_needs_its_key():
    from second.graphs.composition import ModelProviderNotConfigured, build_model

    import os
    os.environ.pop("GROQ_API_KEY", None)
    with pytest.raises(ModelProviderNotConfigured) as excinfo:
        build_model(provider="groq")
    assert "GROQ_API_KEY" in str(excinfo.value)


# -- listening to the provider instead of guessing --------------------------
#
# The second live Daily run died at the Diagnostician even though the 429 was
# caught and retried. A fixed ladder answered after 2s and 4s -- two more
# requests at a quota that had not moved -- and then gave up 34 seconds before
# the window reopened. Gemini had said "retry in 40.5s" and was ignored.


class _Event:
    """The shape ``AfterModelCallEvent`` presents to a retry hook."""

    def __init__(self, exception: Exception | None) -> None:
        self.exception = exception
        self.retry = False
        self.stop_response = None


@pytest.fixture
def slept(monkeypatch) -> list[float]:
    """Record what the strategy waits for, without waiting for it."""
    import asyncio

    recorded: list[float] = []

    async def _record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _record)
    return recorded


GEMINI_429 = (
    "429 Too Many Requests. {'message': '{\n  \"error\": {\n    \"code\": 429,\n"
    '    "message": "You exceeded your current quota, please check your plan and '
    "billing details. \\n* Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
    'limit: 5, model: gemini-3.7-flash\\nPlease retry in 40.513907697s.",\n'
    '    "status": "RESOURCE_EXHAUSTED",\n    "details": [{"@type": '
    '"type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "40s"}]}}\'}'
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ('"retryDelay": "40s"', 40.0),
        ("retryDelay: 7s", 7.0),
        ("Please retry in 40.513907697s.", 40.513907697),
        ("Rate limit reached. Please try again in 1.5s", 1.5),
        ("Retry-After: 30", 30.0),
    ],
)
def test_a_stated_delay_is_found_wherever_the_provider_put_it(message, expected):
    from second.core.retry import _stated_delay

    assert _stated_delay(Exception(message)) == pytest.approx(expected)


def test_no_stated_delay_reads_as_none():
    """The common case, and the one the exponential ladder exists for."""
    from second.core.retry import _stated_delay

    assert _stated_delay(Exception("503 overloaded")) is None
    assert _stated_delay(None) is None


def test_an_sdk_that_exposes_the_header_directly_is_read_first():
    from second.core.retry import _stated_delay

    error = Exception("429")
    error.retry_after = 12  # type: ignore[attr-defined]
    assert _stated_delay(error) == 12.0


@pytest.mark.asyncio
async def test_the_real_gemini_wait_is_honoured_not_guessed(strategy, slept):
    """The whole point. 2s was the old answer; the provider said 40.5s."""
    await strategy._handle_after_model_call(_Event(Exception(GEMINI_429)))

    assert slept == [41], f"waited {slept} instead of honouring the stated delay"


@pytest.mark.asyncio
async def test_the_ladder_still_runs_when_nothing_was_stated(strategy, slept):
    """A provider that says only "busy" gets the backoff it always got."""
    await strategy._handle_after_model_call(_Event(Exception("503 overloaded")))

    assert slept == [1]  # the fixture's initial_delay


@pytest.mark.asyncio
async def test_an_exhausted_allowance_fails_now_rather_than_hanging(slept):
    """A day-quota 429 asks for hours. Sleeping through it is a hang in costume."""
    strategy = ResilientRetry(max_attempts=3, initial_delay=1, max_delay=4, patience=65)
    event = _Event(Exception('429 quota exceeded. "retryDelay": "3600s"'))

    await strategy._handle_after_model_call(event)

    assert slept == []
    assert event.retry is False


def test_patience_is_what_separates_a_busy_minute_from_a_closed_door():
    strategy = ResilientRetry(max_attempts=3, initial_delay=1, max_delay=4, patience=65)

    assert strategy.is_retryable(Exception('429. "retryDelay": "40s"')) is True
    assert strategy.is_retryable(Exception('429. "retryDelay": "64s"')) is True
    assert strategy.is_retryable(Exception('429. "retryDelay": "66s"')) is False


def test_a_stated_delay_never_exceeds_patience_even_when_honoured():
    """Belt and braces: is_retryable already refuses these, but if that check
    ever moves, the sleep must not become unbounded."""
    strategy = ResilientRetry(max_attempts=3, initial_delay=1, max_delay=4, patience=65)
    strategy._last_exception = Exception('"retryDelay": "3600s"')

    assert strategy._calculate_delay(0) == 65


def test_the_remembered_exception_is_dropped_when_the_call_succeeds():
    """Otherwise one 429 sets the delay for every later unrelated failure."""
    strategy = ResilientRetry(max_attempts=3, initial_delay=1, max_delay=4)
    strategy._last_exception = Exception('"retryDelay": "40s"')

    strategy._reset_retry_state()

    assert strategy._calculate_delay(0) == 1


def test_the_node_timeout_outlasts_a_wait_we_agreed_to_sit_through():
    """A timeout shorter than the provider's recovery interval is a scheduled
    failure. 60s killed nodes that waited 40s correctly and then thought."""
    from second.settings import (
        GRAPH_TIMEOUT_SECONDS,
        NODE_TIMEOUT_SECONDS,
        RETRY_PATIENCE_SECONDS,
    )

    assert NODE_TIMEOUT_SECONDS > RETRY_PATIENCE_SECONDS + 30
    assert GRAPH_TIMEOUT_SECONDS >= NODE_TIMEOUT_SECONDS * 3
