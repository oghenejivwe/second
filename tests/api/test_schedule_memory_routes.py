"""The schedule, memory and question routes, over a real store and a real app.

Two reads and two writes. The reads carry the rule ``GET /api/today`` was changed to obey: a GET
never calls a model and never writes, because a browser polls it. That is asserted here rather
than trusted, by making every model and graph entrypoint explode and by counting the rows in the
table before and after.

Sync tests, for the reason given at the top of ``test_routes.py``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from second.api.app import create_app
from second.core.clock import Clock
from second.core.models import BriefJudgement, IntakeResult, Reminder
from second.graphs import composition, memory, service
from second.graphs.brief import assemble
from second.settings import DEMO_USER_ID
from second.testing import demo_scenario
from second.testing.fake_connectors import read_fake_calendar
from second.tools._google import GoogleCredentialsMissing

TODAY = demo_scenario.TODAY


@pytest.fixture
def hermetic(monkeypatch):
    """No real Google from these tests: a pinned zone, and the fake connector for the calendar."""
    monkeypatch.setattr(
        service, "resolve_clock", lambda *_args, **_kwargs: Clock.fixed(TODAY, zone_name="Europe/London")
    )
    monkeypatch.setattr(memory, "live_calendar", read_fake_calendar)


@pytest.fixture
def client(store, hermetic):  # noqa: ARG001 - the fixtures wire the store and the fakes
    with TestClient(create_app(serve_web=False), raise_server_exceptions=False) as testing:
        yield testing


@pytest.fixture
def no_model(monkeypatch):
    """Any reach for a model or a graph run fails the request loudly."""

    def explode(*_args, **_kwargs):
        raise AssertionError("a GET reached for a model")

    async def explode_async(*_args, **_kwargs):
        raise AssertionError("a GET ran a graph")

    monkeypatch.setattr(composition, "build_model", explode)
    monkeypatch.setattr(composition, "model_for", explode)
    for name in ("run_daily", "run_intake", "run_feedback"):
        monkeypatch.setattr(service, name, explode_async)


def stored(store) -> tuple[int, int]:
    """The graph's version and the number of rows in the table: anything written moves one."""
    return store.load(DEMO_USER_ID).version, len(store.table.scan()["Items"])


def by_name(body, name):
    return next(source for source in body["sources"] if source["name"] == name)


# -- reads stay reads --------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/schedule", "/api/schedule?days=28", "/api/memory"])
def test_reading_calls_no_model_and_writes_nothing(client, store, no_model, path):
    """Mutation-tested: making ``get_memory`` record ``asked_on`` for the questions it shows moves
    the graph version and this fails."""
    before = stored(store)

    response = client.get(path)

    assert response.status_code == 200, response.text
    assert stored(store) == before


# -- the schedule ------------------------------------------------------------


def test_the_schedule_is_a_week_with_proposals_and_refusals(client):
    body = client.get("/api/schedule").json()

    assert [day["on"] for day in body["days"]][0] == TODAY.isoformat()
    assert len(body["days"]) == 7

    blocks = [block for day in body["days"] for block in day["blocks"]]
    assert {block["status"] for block in blocks} == {"placed", "proposed"}
    assert all(block["why"] for block in blocks if block["status"] == "proposed")

    refusals = [skip for day in body["days"] for skip in day["skipped"]]
    assert any("abandoned" in skip["reason"] for skip in refusals)
    assert [skip["route_id"] for skip in body["skipped"]] == ["r-travel"]


def test_the_schedule_span_is_bounded(client):
    assert len(client.get("/api/schedule?days=1").json()["days"]) == 1
    assert client.get("/api/schedule?days=0").status_code == 422
    assert client.get("/api/schedule?days=29").status_code == 422


# -- memory ------------------------------------------------------------------


def test_memory_lists_every_source_and_why(client):
    body = client.get("/api/memory").json()

    assert [source["name"] for source in body["sources"]] == ["graph", "calendar", "email"]
    assert by_name(body, "graph")["connected"] is True
    assert by_name(body, "calendar")["connected"] is True
    email = by_name(body, "email")
    # No morning run yet is not a broken inbox: connected, empty, and saying why.
    assert email == {
        "name": "email",
        "connected": True,
        "reason": "The morning run has not read your email yet today.",
        "items": 0,
    }
    assert all(item["evidence"] for item in body["items"])
    today = [item for item in body["items"] if item["kind"] == "event"]
    assert [(item["what"], item["source"]) for item in today] == [
        ("Record five minutes and listen back", "graph"),
        ("Draft the talk pitch", "graph"),
        ("Gym session", "graph"),
    ], "On today matches the blocks Today and Schedule show"
    assert [question["horizon"] for question in body["questions"]] == ["week", "month"]


def test_memory_after_the_morning_run_carries_email_reminders(client, store):
    clock = Clock.fixed(TODAY, zone_name="Europe/London")
    reminder = Reminder(
        what="Your sister asked whether the flights are booked.",
        evidence="m-wedding, 'Wedding week - are you booked yet?'",
        source="email",
    )
    brief = assemble(
        graph=store.load(DEMO_USER_ID),
        clock=clock,
        judgement=BriefJudgement(reminders=[reminder], notify=True),
    )
    store.save_brief(DEMO_USER_ID, brief)

    body = client.get("/api/memory").json()

    assert by_name(body, "email")["connected"] is True
    assert [item["what"] for item in body["items"] if item["source"] == "email"] == [reminder.what]


def test_a_calendar_that_cannot_be_read_says_so_over_http(client, monkeypatch):
    def no_credentials(start, end):
        raise GoogleCredentialsMissing("no runtime Google token at 'token.json'")

    monkeypatch.setattr(memory, "live_calendar", no_credentials)

    response = client.get("/api/memory")

    assert response.status_code == 200, "one unreadable source is not a failed request"
    calendar = by_name(response.json(), "calendar")
    assert calendar["connected"] is False
    assert "GoogleCredentialsMissing" in calendar["reason"]
    assert any(item["kind"] == "deadline" for item in response.json()["items"])


# -- the recurring question --------------------------------------------------


def test_skipping_records_asked_on_and_the_question_goes_quiet(client, store):
    assert "week" in [question["horizon"] for question in client.get("/api/memory").json()["questions"]]

    response = client.post("/api/questions/skip", json={"horizon": "week"})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "horizon": "week",
        "asked_on": TODAY.isoformat(),
        "next_due": "2026-09-12",
    }
    assert store.load(DEMO_USER_ID).person.asked_on == {"week": TODAY}
    assert [question["horizon"] for question in client.get("/api/memory").json()["questions"]] == ["month"]


def test_answering_goes_through_intake_and_records_asked_on(client, store, monkeypatch):
    heard = {}

    async def intake(user_id, transcript, **_kwargs):
        heard["transcript"] = transcript
        return IntakeResult(graph=store.load(user_id))

    monkeypatch.setattr(service, "run_intake", intake)

    response = client.post(
        "/api/questions/answer", json={"horizon": "month", "text": "Give a talk at the club by the 30th"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"graph", "clarifying_questions", "schedule"}, "the IntakeResult, verbatim"
    assert body["graph"]["person"]["asked_on"] == {"month": TODAY.isoformat()}
    assert "Give a talk at the club by the 30th" in heard["transcript"]


def test_a_question_route_refuses_what_it_cannot_record(client):
    assert client.post("/api/questions/skip", json={"horizon": "decade"}).status_code == 422
    assert client.post("/api/questions/answer", json={"horizon": "week", "text": ""}).status_code == 422
    assert client.get("/api/questions/skip").status_code == 405
