"""Web search, with the HTTP layer faked at ``requests.post``.

There is no network here and no key. The failure cases get more attention than the
happy path, because the Resource Finder's whole value is telling "no material
exists" apart from "I could not look", and an empty list says both.
"""

from __future__ import annotations

import pytest

from second.tools import search_tools
from second.tools.search_tools import SearchError, SearchNotConfigured, web_search


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv(search_tools.TAVILY_KEY_ENV, "tvly-test-key")


def _respond(monkeypatch, *responses, record=None):
    """Answer successive posts with the given responses."""
    queue = list(responses)

    def post(url, json=None, headers=None, timeout=None):
        if record is not None:
            record.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    import requests

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(search_tools.time, "sleep", lambda _: None)


def _post(monkeypatch, *responses, record=None):
    """Drive ``_post`` directly with injected sleep and jitter.

    The retry tests use this rather than patching the global clock, because
    ``_post`` takes ``sleep`` and ``jitter`` as parameters for exactly this reason:
    no real waiting, and no flaking on a random value.
    """
    _respond(monkeypatch, *responses, record=record)
    waited: list[float] = []
    return waited, lambda body=None: search_tools._post(
        body or {"query": "anything", "max_results": 5},
        sleep=waited.append,
        jitter=lambda: 0.5,
    )


RESULTS = {
    "query": "five minute talk",
    "results": [
        {
            "title": "How to structure a five-minute talk",
            "url": "https://www.youtube.com/watch?v=abc",
            "content": "A simple three-beat structure for very short talks.",
            "score": 0.94,
            "raw_content": None,
        },
        {
            "title": "Speaking club formats explained",
            "url": "https://example.com/club-formats",
            "content": "What to expect from a first visit.",
            "score": 0.81,
        },
    ],
    "response_time": 1.2,
}


def test_results_come_back_in_the_contract_shape(key, monkeypatch):
    _respond(monkeypatch, FakeResponse(payload=RESULTS))
    video, article = web_search("five minute talk")

    assert set(video) == {"title", "url", "snippet", "kind"}
    assert video["kind"] == "video"
    assert video["snippet"] == "A simple three-beat structure for very short talks.", (
        "Tavily's field is `content`; forgetting the rename to `snippet` gives a "
        "KeyError deep inside an agent loop that reads as a model failure"
    )
    assert article["kind"] == "article"


def test_the_key_goes_in_a_header_not_the_body(key, monkeypatch):
    """A body ``api_key`` field returns 401 on a free-tier key, and almost every
    sample online still shows it that way."""
    sent = []
    _respond(monkeypatch, FakeResponse(payload=RESULTS), record=sent)
    web_search("anything")

    assert sent[0]["headers"]["Authorization"] == "Bearer tvly-test-key"
    assert "api_key" not in sent[0]["json"]
    assert sent[0]["timeout"] == search_tools.REQUEST_TIMEOUT, "an untimed hop can spend the node's whole budget"


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://www.youtube.com/watch?v=x", "video"),
        ("https://youtu.be/x", "video"),
        ("https://vimeo.com/123", "video"),
        ("https://www.ted.com/talks/x", "video"),
        ("https://m.youtube.com/watch?v=x", "video"),
        ("https://example.com/an-article", "article"),
        ("https://notyoutube.com/x", "article"),
        ("https://youtube.com.evil.example/x", "article"),
        ("", "article"),
    ],
)
def test_kind_is_inferred_from_the_host(url, kind):
    """Tavily returns no field distinguishing video from article.

    The last two cases matter: a substring check would call
    ``youtube.com.evil.example`` a video, and the default is ``"article"`` because
    promising a video and delivering prose sends someone who learns by video to a
    wall of text.
    """
    assert search_tools._kind(url) == kind


def test_max_results_is_capped_and_respected(key, monkeypatch):
    sent = []
    _respond(monkeypatch, FakeResponse(payload=RESULTS), record=sent)
    web_search("anything", max_results=50)
    assert sent[0]["json"]["max_results"] == 20, "Tavily's range is 0-20"

    assert len(web_search("anything", max_results=1)) == 1


def test_a_missing_key_says_which_variable_to_set(monkeypatch):
    monkeypatch.delenv(search_tools.TAVILY_KEY_ENV, raising=False)
    with pytest.raises(SearchNotConfigured, match="TAVILY_API_KEY"):
        web_search("anything")


def test_a_rejected_key_is_not_retried(key, monkeypatch):
    """401 is permanent. Retrying spends three attempts confirming it."""
    sent = []
    _respond(monkeypatch, FakeResponse(401, {"detail": {"error": "Unauthorized: missing or invalid API key"}}), record=sent)

    with pytest.raises(SearchNotConfigured, match="invalid API key"):
        web_search("anything")
    assert len(sent) == 1


@pytest.mark.parametrize("status", [432, 433])
def test_an_exhausted_quota_is_not_retried(key, monkeypatch, status):
    """432 is the plan limit and 433 the pay-as-you-go limit. Neither returns
    within a run, so retrying is three attempts spent confirming bad news."""
    sent = []
    _respond(monkeypatch, FakeResponse(status, {"detail": {"error": "usage limit exceeded"}}), record=sent)

    with pytest.raises(SearchError, match="quota is exhausted"):
        web_search("anything")
    assert len(sent) == 1


def test_a_throttle_is_retried_and_honours_retry_after(key, monkeypatch):
    waited, post = _post(
        monkeypatch,
        FakeResponse(429, {"detail": {"error": "rate limited"}}, headers={"retry-after": "7"}),
        FakeResponse(payload=RESULTS),
    )
    assert len(post()["results"]) == 2
    assert waited == [7.0], "the server said how long to wait; guessing would be worse"


def test_a_malformed_retry_after_falls_back_to_backoff(key, monkeypatch):
    """A header the server sent but we cannot parse must not become a crash or a
    zero-second retry storm."""
    waited, post = _post(
        monkeypatch,
        FakeResponse(429, {"detail": {"error": "rate limited"}}, headers={"retry-after": "soon"}),
        FakeResponse(payload=RESULTS),
    )
    post()
    assert waited == [1.0], "jitter 0.5 * 2**1"


def test_a_server_error_is_retried_then_raises(key, monkeypatch):
    sent = []
    waited, post = _post(monkeypatch, FakeResponse(503, {"detail": {"error": "upstream"}}), record=sent)

    with pytest.raises(SearchError, match="after 3 attempt"):
        post()
    assert len(sent) == search_tools.MAX_ATTEMPTS
    assert waited == [1.0, 2.0], "backoff doubles, and the third attempt does not sleep after failing"


def test_a_network_error_is_retried_then_raises(key, monkeypatch):
    import requests

    attempts = []

    def post(url, **kwargs):
        attempts.append(url)
        raise requests.ConnectionError("name resolution failed")

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(search_tools.time, "sleep", lambda _: None)

    with pytest.raises(SearchError, match="ConnectionError"):
        web_search("anything")
    assert len(attempts) == search_tools.MAX_ATTEMPTS


def test_a_failure_never_degrades_to_an_empty_list(key, monkeypatch):
    """The failure direction this domain is written around.

    An empty list would have the Resource Finder report that no material exists,
    when in fact it could not look -- and the route would be planned without
    resources on the strength of a confident nothing.
    """
    _respond(monkeypatch, FakeResponse(500, {"detail": {"error": "boom"}}))
    with pytest.raises(SearchError):
        web_search("anything")


def test_a_body_without_a_results_array_raises(key, monkeypatch):
    _respond(monkeypatch, FakeResponse(payload={"query": "x", "response_time": 0.4}))
    with pytest.raises(SearchError, match="no results array"):
        web_search("anything")


def test_a_non_json_body_raises(key, monkeypatch):
    _respond(monkeypatch, FakeResponse(payload=None, text="<html>502 Bad Gateway</html>"))
    with pytest.raises(SearchError, match="not JSON"):
        web_search("anything")


def test_an_error_body_in_an_unexpected_shape_still_reports_the_status(key, monkeypatch):
    """Tavily nests its message under ``detail``. Reading ``payload['error']``
    raises KeyError on top of the HTTP failure and the real cause vanishes."""
    _respond(monkeypatch, FakeResponse(503, {"error": "flat shape, not Tavily's"}))
    with pytest.raises(SearchError, match="HTTP 503"):
        web_search("anything")


def test_an_empty_query_raises(key, monkeypatch):
    _respond(monkeypatch, FakeResponse(payload=RESULTS))
    with pytest.raises(SearchError, match="needs a query"):
        web_search("   ")
    with pytest.raises(SearchError, match="must be positive"):
        web_search("anything", max_results=0)


def test_no_new_dependency_was_added():
    """``tavily-python`` was pinned in the brief and deliberately not installed.

    Adding a package to pyproject.toml and uv.lock -- both PLATFORM's -- to save
    four lines of HTTP would be the wrong trade, and this pins the decision so it
    is not quietly reversed.
    """
    import importlib.util

    assert importlib.util.find_spec("tavily") is None
    source = (
        __import__("pathlib").Path(search_tools.__file__).read_text(encoding="utf-8")
    )
    assert "import tavily" not in source and "from tavily" not in source
