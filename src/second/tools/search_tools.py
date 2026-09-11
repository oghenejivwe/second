"""Web search, for the one agent that needs it.

The Resource Finder uses this to find material for a route -- a video on structuring
a five-minute talk, an article on what to expect at a speaking club. It is the
lowest-priority tool in this domain because that agent is first on the project's cut
list.

No SDK. ``tavily-python`` was pinned in the brief and is not installed; the API is
one POST and ``requests`` 2.34.2 is already present as a transitive dependency of
``google-api-python-client``. Adding a package to ``pyproject.toml`` and ``uv.lock``
-- both PLATFORM's -- to save four lines is the wrong trade three days out.

Two things that are easy to get wrong here
------------------------------------------

**The key goes in a header.** ``Authorization: Bearer tvly-...``. The JSON-body
``api_key`` field that almost every sample online still shows returns 401 on a
free-tier key. Verified against the current API reference.

**There is no field saying video or article.** A Tavily result is ``{title, url,
content, score, raw_content}`` -- no ``type``, no ``kind``, no content type. The
contract requires ``kind``, so it is inferred from the host, and the default is
``"article"`` because claiming something is a video when it is not sends a user who
learns by video to a wall of text.

Note the rename: Tavily's field is ``content`` and this contract's is ``snippet``.
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from strands import tool

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
TAVILY_KEY_ENV = "TAVILY_API_KEY"

REQUEST_TIMEOUT = 15.0
"""Seconds. The Resource Finder runs inside a graph with a 60-second node timeout,
so a hop that can hang for longer than this would spend the node's whole budget on
one search. Stepping over it costs a slow search; not having it costs the node."""

MAX_ATTEMPTS = 3
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
"""429 carries a ``retry-after`` header, which is honoured. 432 (plan limit) and 433
(pay-as-you-go limit) are **not** retryable: the quota is gone and retrying spends
three attempts to confirm it."""

VIDEO_HOSTS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "dailymotion.com",
    "ted.com",
    "loom.com",
)


class SearchError(RuntimeError):
    """A web search could not be completed. Raised, never returned.

    An empty list would be indistinguishable from "nothing found", and the Resource
    Finder would report that no material exists rather than that it could not look.
    """


class SearchNotConfigured(SearchError):
    """No search API key. Says which variable to set."""


def _kind(url: str) -> str:
    """``"video"`` or ``"article"``, inferred from the host.

    Tavily returns nothing that distinguishes them. Defaults to ``"article"``:
    promising a video and delivering prose is worse than the reverse, because the
    Person layer routes on ``learning_mode`` and a user who learns by video would
    be sent to a wall of text.
    """
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return "video" if any(host == v or host.endswith(f".{v}") for v in VIDEO_HOSTS) else "article"


def _detail(payload: Any) -> str:
    """Tavily's error message, which nests two levels down.

    The body is ``{"detail": {"error": "..."}}``. Reading ``payload["error"]``
    raises ``KeyError`` on top of the HTTP failure and the real cause vanishes.
    """
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            return str(detail.get("error") or detail)
        if detail:
            return str(detail)
    return ""


@tool
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web for material.

    Args:
        query: What to search for. Describe the material wanted, not just the
            topic -- "how to structure a five-minute talk" finds better results
            than "public speaking".
        max_results: How many results to return. At most 20.

    Returns:
        Results, each with title, url, snippet and kind ("video" or "article").

    Raises:
        SearchNotConfigured: If no API key is set.
        SearchError: If the query is empty, or the search could not be completed.
            Never an empty list on failure -- the Resource Finder must be able to
            tell "no material exists" from "I could not look".
    """
    if not query.strip():
        raise SearchError("a web search needs a query")
    if max_results <= 0:
        raise SearchError(f"max_results must be positive; got {max_results}")

    payload = _post(
        {
            "query": query.strip(),
            "max_results": min(max_results, 20),
            "search_depth": "basic",
            "include_answer": False,
        }
    )

    results = payload.get("results")
    if not isinstance(results, list):
        raise SearchError(
            f"the search API returned no results array; top-level keys were "
            f"{sorted(payload) if isinstance(payload, dict) else type(payload).__name__}"
        )

    return [
        {
            "title": str(item.get("title") or "(untitled)"),
            "url": str(item.get("url") or ""),
            # Tavily's field is `content`; this contract's is `snippet`.
            "snippet": str(item.get("content") or ""),
            "kind": _kind(str(item.get("url") or "")),
        }
        for item in results[:max_results]
        if isinstance(item, dict)
    ]


def _post(
    body: dict[str, Any],
    *,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> dict[str, Any]:
    """One search, retried only where retrying helps.

    Exponential backoff with full jitter, three attempts, honouring ``retry-after``
    when the server sends one. ``sleep`` and ``jitter`` are injected so the tests
    neither wait nor flake.
    """
    import requests  # noqa: PLC0415 - lazy, so importing this module needs no network stack

    key = os.environ.get(TAVILY_KEY_ENV, "").strip()
    if not key:
        raise SearchNotConfigured(
            f"no web search key. Set ${TAVILY_KEY_ENV} (tavily.com, free tier is "
            f"1,000 credits a month and needs no card)."
        )

    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                TAVILY_URL,
                json=body,
                # The header, not a body field. A body `api_key` returns 401 on a
                # free-tier key, and almost every sample online still shows it.
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as error:
            last = f"{type(error).__name__}: {error}"
            if attempt == MAX_ATTEMPTS:
                break
            sleep(jitter() * 2**attempt)
            continue

        if response.status_code == 200:
            try:
                return response.json()
            except ValueError as error:
                raise SearchError("the search API returned a body that is not JSON") from error

        try:
            described = _detail(response.json())
        except ValueError:
            described = response.text[:200]
        last = f"HTTP {response.status_code}: {described or '(no detail)'}"

        if response.status_code == 401:
            raise SearchNotConfigured(f"the search API rejected the key: {last}")
        if response.status_code in (432, 433):
            raise SearchError(
                f"the search API quota is exhausted ({last}). Not retried -- the "
                f"quota will not return within this run."
            )
        if response.status_code not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
            break

        wait = _retry_after(response) or jitter() * 2**attempt
        logger.warning("web search got %s; retry %d/%d in %.1fs", response.status_code, attempt, MAX_ATTEMPTS, wait)
        sleep(wait)

    raise SearchError(f"could not search the web after {MAX_ATTEMPTS} attempt(s). Last: {last}")


def _retry_after(response: Any) -> float | None:
    """The server's own wait, in seconds, when it sends one."""
    raw = response.headers.get("retry-after") if hasattr(response, "headers") else None
    try:
        return max(0.0, float(raw)) if raw else None
    except (TypeError, ValueError):
        return None


ALL_SEARCH_TOOLS = (web_search,)
