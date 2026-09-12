"""The nine routes, over a real store and a real app.

``moto`` supplies DynamoDB semantics in-process, so these exercise the same
``graphs.service`` functions the deployed path calls. Nothing about the HTTP
layer is mocked.

Tests here are **sync** deliberately. ``asyncio_mode = "auto"`` turns every
async test into a coroutine pytest-asyncio runs on its own loop, and
``TestClient`` drives the app through a portal with a loop of its own -- putting
one inside the other raises before any assertion runs.

Two things are asserted that no other test in the repository covers, and both
were written by watching them fail first:

* the SPA catch-all refuses ``/api``, so a mistyped route 404s instead of
  quietly returning ``index.html`` with a 200;
* a transcription that raises comes back as ``failed`` with the reason attached,
  rather than as a 500 that leaves the browser polling a dead job forever.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from second.api import voice as api_voice
from second.api.app import create_app
from second.graphs import service
from second.settings import DEMO_USER_ID

OFFSET = re.compile(r"[+-]\d{2}:\d{2}$")


@pytest.fixture
def client(store):  # noqa: ARG001 - the fixture wires the store into the service
    """The app over the seeded demo world.

    ``serve_web=False`` because a stale ``web/dist`` on a developer's machine
    must not be able to change what a route returns.
    """
    with TestClient(create_app(serve_web=False), raise_server_exceptions=False) as testing:
        yield testing


class Rejected(Exception):
    """Stands in for ``second.voice.VoiceError``."""


class Broke(Exception):
    """Stands in for ``second.voice.TranscriptionError``."""


def seam(*, start=None, get=None, max_bytes=1024) -> api_voice.VoiceSeam:
    """A voice seam with CONNECTORS' shape and none of its AWS calls.

    Faked at this boundary rather than deeper because what is under test is the
    mapping the HTTP layer performs: the seam raises where the route promises a
    status, and that conversion is SURFACES' to get right.
    """
    return api_voice.VoiceSeam(
        start=start or (lambda payload, content_type, **_: "job-1"),
        get=get or (lambda job_id: ("running", None)),
        max_bytes=max_bytes,
        rejected=Rejected,
        broke=Broke,
    )


def use(monkeypatch, **kwargs) -> None:
    """Point the routes at a fake seam."""
    monkeypatch.setattr("second.api.routes.resolve_voice", lambda: seam(**kwargs))


# --- the graph --------------------------------------------------------------


def test_graph_returns_the_seeded_world(client):
    response = client.get("/api/graph")
    assert response.status_code == 200

    graph = response.json()["graph"]
    assert graph["user_id"] == DEMO_USER_ID
    assert {goal["id"] for goal in graph["goals"]} >= {"g-company", "g-speaking", "g-lisbon"}
    assert graph["person"]["preferences"]["learning_mode"] == "video"


def test_audit_honours_its_limit(client):
    assert client.get("/api/audit?limit=3").status_code == 200
    assert client.get("/api/audit?limit=0").status_code == 422
    assert client.get("/api/audit?limit=501").status_code == 422


# --- the datetime asymmetry, end to end -------------------------------------


def test_slots_stay_naive_across_the_api(client):
    """The Living Graph holds wall-clock time and the API must not invent a zone.

    A plan is what the person reads off their own calendar; storing or sending
    it as UTC would move the plan when they travel. The browser relies on this:
    ``lib/datetime.ts`` formats a slot by reading its characters precisely
    because there is no offset to trust.
    """
    graph = client.get("/api/graph").json()["graph"]
    slots = [
        slot
        for goal in graph["goals"]
        for route in goal["routes"]
        for task in route["tasks"]
        for slot in task["scheduled_slots"]
    ]

    assert slots, "the seeded world has scheduled work"
    assert not [slot for slot in slots if OFFSET.search(slot)], (
        "a scheduled slot arrived with a timezone offset; the browser would "
        "reinterpret it in whatever zone the viewer happens to be in"
    )


def test_freed_blocks_are_timezone_aware(client):
    """The other half of the asymmetry. Anything the API computes is aware."""
    response = client.post("/api/goals/g-speaking/status", json={"status": "retired"})
    assert response.status_code == 200

    freed = response.json()["freed"]
    assert freed, "retiring g-speaking releases its upcoming slots"
    for block in freed:
        assert OFFSET.search(block["start"]), f"{block['start']} lost its offset"


# --- goals ------------------------------------------------------------------


def test_retiring_a_goal_reports_the_time_it_freed(client):
    response = client.post("/api/goals/g-speaking/status", json={"status": "retired"})
    body = response.json()

    assert response.status_code == 200
    assert body["graph"]["goals"], "the graph comes back written"
    assert body["freed_minutes"] == sum(block["duration_min"] for block in body["freed"])
    assert body["note"], "the user is told what becomes of the freed time"

    # The ruling: freed, never redistributed. The Scheduler has not run.
    assert "redistribut" not in body["note"].lower()
    assert "reallocates" in body["note"].lower()

    retired = next(goal for goal in body["graph"]["goals"] if goal["id"] == "g-speaking")
    assert retired["status"] == "retired"


def test_freed_blocks_keep_the_ladder_they_were_serving(client):
    """A struck-through slot has to be able to say what it was for."""
    freed = client.post("/api/goals/g-speaking/status", json={"status": "retired"}).json()["freed"]

    assert all(block["goal_id"] == "g-speaking" for block in freed)
    assert any(block["serves"] for block in freed), (
        "the freed slots carry the goals above them, so the screen can show what was dropped"
    )


def test_an_unknown_goal_is_a_404_that_names_it(client):
    response = client.post("/api/goals/g-nope/status", json={"status": "paused"})

    assert response.status_code == 404
    assert "g-nope" in response.json()["detail"]


def test_an_invalid_status_is_refused(client):
    response = client.post("/api/goals/g-speaking/status", json={"status": "deleted"})
    assert response.status_code == 422


# --- the unfinished edges of the build --------------------------------------


def test_an_unbuilt_daily_run_is_a_503_that_says_what_is_missing(client, monkeypatch):
    """A run that cannot happen yet explains itself, rather than 500-ing.

    Two things are genuinely absent today and either can be hit first: there is
    no ``ANTHROPIC_API_KEY`` in the environment, and ``second.agents`` does not
    exist. Both are edges of an unfinished build rather than faults, so both are
    503 and both carry a sentence that says what to do -- which is the product's
    voice applied to its own incompleteness. A screen reading
    "second.agents.observer does not exist yet (owned by AGENTS)" tells everyone,
    including a judge, where the work stops.

    The key is cleared rather than assumed absent, so this still means something
    on a machine that has one configured.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    response = client.post("/api/daily/run")
    assert response.status_code == 503, response.text

    detail = response.json()["detail"]
    assert any(
        marker in detail for marker in ("ANTHROPIC_API_KEY", "second.agents", "SECOND_MODEL_PROVIDER")
    ), f"a 503 has to say what is missing; got {detail!r}"
    assert "Something went wrong" not in detail


def test_voice_upload_without_the_connector_is_a_503_that_names_its_owner(client, monkeypatch):
    """An absent package is explained, not turned into a 500 on an ImportError."""

    def absent():
        raise api_voice.MissingVoice(
            "second.voice does not exist yet (owned by CONNECTORS). "
            "The browser live transcript still works; the accurate one needs this."
        )

    monkeypatch.setattr("second.api.routes.resolve_voice", absent)

    response = client.post("/api/voice", files={"audio": ("intake.webm", b"x" * 64, "audio/webm")})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "second.voice" in detail
    assert "CONNECTORS" in detail


def test_the_upload_is_sent_on_as_bare_audio_webm(client, monkeypatch):
    """An S3 presigned PUT signs the content type.

    ``MediaRecorder.mimeType`` reports ``audio/webm;codecs=opus`` and that fails
    the signature with an opaque 403 that reads like CORS. The browser re-wraps
    the blob; this asserts the server half of the same agreement rather than
    trusting whatever the client happened to send.
    """
    seen = {}

    def start(payload, content_type, **_):
        seen["content_type"] = content_type
        seen["bytes"] = len(payload)
        return "job-9"

    use(monkeypatch, start=start)

    response = client.post(
        "/api/voice",
        files={"audio": ("intake.webm", b"x" * 40, "audio/webm;codecs=opus")},
    )

    assert response.status_code == 200
    assert response.json() == {"job_id": "job-9"}
    assert seen["content_type"] == "audio/webm", "the codecs parameter must not reach S3"
    assert seen["bytes"] == 40


def test_an_empty_upload_is_refused_before_the_seam_is_touched(client, monkeypatch):
    def start(*_args, **_kwargs):
        raise AssertionError("the seam must not be called for an empty upload")

    use(monkeypatch, start=start)

    response = client.post("/api/voice", files={"audio": ("intake.webm", b"", "audio/webm")})

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_an_oversized_upload_is_refused_against_the_connectors_own_limit(client, monkeypatch):
    """One cap, theirs. Two that can disagree is worse than one in the wrong place."""
    use(monkeypatch, max_bytes=32)

    response = client.post("/api/voice", files={"audio": ("intake.webm", b"x" * 64, "audio/webm")})

    assert response.status_code == 413
    assert "limit" in response.json()["detail"]


def test_a_recording_the_seam_rejects_is_a_400_carrying_its_reason(client, monkeypatch):
    def start(*_args, **_kwargs):
        raise Rejected("audio is 0 bytes")

    use(monkeypatch, start=start)

    response = client.post("/api/voice", files={"audio": ("intake.webm", b"x" * 40, "audio/webm")})

    assert response.status_code == 400
    assert response.json()["detail"] == "audio is 0 bytes"


def test_a_job_that_will_not_start_is_a_502_carrying_its_reason(client, monkeypatch):
    def start(*_args, **_kwargs):
        raise Broke("could not start transcribing: AccessDenied")

    use(monkeypatch, start=start)

    response = client.post("/api/voice", files={"audio": ("intake.webm", b"x" * 40, "audio/webm")})

    assert response.status_code == 502
    assert "AccessDenied" in response.json()["detail"]


def test_a_running_job_reports_running_with_no_transcript(client, monkeypatch):
    use(monkeypatch, get=lambda job_id: ("running", None))

    response = client.get("/api/voice/job-1")

    assert response.status_code == 200
    assert response.json() == {"status": "running", "transcript": None}


def test_a_finished_job_reports_the_transcript(client, monkeypatch):
    use(monkeypatch, get=lambda job_id: ("done", "I want to speak to a room."))

    response = client.get("/api/voice/job-1")

    assert response.json() == {"status": "done", "transcript": "I want to speak to a room."}


def test_an_unrecognised_status_is_reported_as_failed_not_passed_through(client, monkeypatch):
    """The seam documents exactly two statuses, so a third means it moved."""
    use(monkeypatch, get=lambda job_id: ("queued", None))

    body = client.get("/api/voice/job-1").json()

    assert body["status"] == "failed"
    assert "queued" in body["detail"]


# --- the two guards ---------------------------------------------------------


def test_the_spa_catch_all_does_not_swallow_the_api(tmp_path, store, monkeypatch):  # noqa: ARG001
    """A mistyped API path must 404, not return the app shell with a 200.

    Watched fail first: dropping the ``api/`` check in ``_mount_web`` makes this
    return 200 and ``<!doctype html>``, which is the most confusing possible
    answer to a wrong URL -- the browser parses HTML as JSON and reports a
    syntax error somewhere far away from the mistake.
    """
    from second.api import app as app_module

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Second</title>", encoding="utf-8")
    monkeypatch.setattr(app_module, "WEB_DIST", dist)

    with TestClient(app_module.create_app(), raise_server_exceptions=False) as serving:
        shell = serving.get("/")
        assert shell.status_code == 200
        assert "doctype html" in shell.text.lower(), "the SPA is being served at all"

        missing = serving.get("/api/nonsense")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "No route /api/nonsense."


def test_a_failed_transcription_is_a_200_saying_failed_not_a_500(client, monkeypatch):
    """The reason has to reach the browser, or it polls a dead job forever.

    ``get_transcription`` never returns ``"failed"``: CONNECTORS raises
    ``TranscriptionError`` carrying Transcribe's own FailureReason, and argues
    correctly that it is the only explanation that exists. But the route promises
    a status, and a browser in a polling loop needs to be told to stop.
    Converting is the HTTP layer's job.

    Watched fail first: removing the ``except seam.broke`` in
    ``api/voice.read_job`` makes this a 500 with a generic detail, and the Record
    screen polls a dead job forever.
    """

    def get(job_id):
        raise Broke("transcription failed: The media format is not supported")

    use(monkeypatch, get=get)

    response = client.get("/api/voice/job-1")

    assert response.status_code == 200, "a dead job is an answer, not a server error"
    body = response.json()
    assert body["status"] == "failed"
    assert body["transcript"] is None
    assert "media format is not supported" in body["detail"]


# --- the happy path for the day, once AGENTS lands --------------------------


def test_brief_shape(client, monkeypatch):
    """``/api/today`` serialises a ``DailyBrief`` exactly as pydantic would.

    Stubbed at the service boundary rather than at the graph, because what is
    being asserted is the HTTP layer's serialisation: no re-encoding, no
    dropped defaults, and ``check_in`` present-but-null rather than absent.
    """
    from second.core.clock import Clock
    from second.graphs.brief import assemble
    from second.testing import demo_scenario

    brief = assemble(
        graph=demo_scenario.living_graph(),
        clock=Clock.fixed(demo_scenario.TODAY, zone_name="Europe/London"),
        judgement=None,
    )

    async def fake_run_daily(*_args, **_kwargs):
        return brief

    monkeypatch.setattr(service, "run_daily", fake_run_daily)

    response = client.get("/api/today")
    assert response.status_code == 200

    body = response.json()
    assert body == brief.model_dump(mode="json"), "the route sends the model's own JSON, unaltered"

    # Every field is present even when it is empty or null, because the browser
    # types are generated on that promise.
    for field in (
        "on",
        "blocks",
        "prepared",
        "at_risk",
        "reminders",
        "decisions",
        "check_in",
        "notify",
        "silence_reason",
    ):
        assert field in body, f"{field} was dropped on the way out"


# -- a read must stay a read -------------------------------------------------


def test_getting_today_does_not_run_the_graph(client, monkeypatch):
    """``GET /api/today`` used to invoke five agents. A browser refresh could
    spend a day's free-tier quota, and nothing in the response said so.

    Asserted by making run_daily explode: if the route still reaches for it, this
    test says so instead of quietly costing tokens on every poll.
    """

    async def _explode(*args, **kwargs):
        raise AssertionError("GET /api/today ran the Daily graph")

    monkeypatch.setattr(service, "run_daily", _explode)

    response = client.get("/api/today")

    assert response.status_code == 200
    assert "blocks" in response.json()


def test_running_the_day_is_still_a_post(client):
    """The expensive thing keeps a verb that cannot be triggered by a link,
    a prefetch or a refresh."""
    assert client.get("/api/daily/run").status_code == 405


def test_today_is_served_from_the_cached_brief_when_there_is_one(client, store, today):
    """A brief computed by the morning run is what the day shows, unchanged."""
    from second.graphs import service as svc

    brief = svc.get_today(DEMO_USER_ID, today=today)
    brief.silence_reason = "nothing needed saying"
    store.save_brief(DEMO_USER_ID, brief)

    assert client.get("/api/today").json()["silence_reason"] == "nothing needed saying"


# -- health ------------------------------------------------------------------


def test_health_reports_the_store_and_the_provider(client):
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["store"] == "ok"
    assert body["provider"]


def test_health_does_not_call_a_model(client, monkeypatch):
    """A health check that spends quota causes the outage it watches for."""
    from second.graphs import composition

    def _explode(*args, **kwargs):
        raise AssertionError("/api/health built a model")

    monkeypatch.setattr(composition, "build_model", _explode)

    assert client.get("/api/health").status_code == 200


def test_health_says_degraded_when_the_store_is_gone(client, monkeypatch):
    """It reports rather than raising -- a 500 from a health check tells a load
    balancer nothing about what is wrong."""

    def _unreachable(*args, **kwargs):
        raise RuntimeError("table not found")

    monkeypatch.setattr(service, "load_living_graph", _unreachable)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert "RuntimeError" in response.json()["store"]
