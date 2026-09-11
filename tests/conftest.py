"""Fixtures shared by every domain's tests.

PLATFORM owns this file because the seams it fakes -- the store, the tool
registry, the model -- are PLATFORM's. Use these rather than rolling your own:
three instances each inventing a DynamoDB fixture is three subtly different
DynamoDBs, and the bug will be in the difference.

Nothing here touches AWS or Google. ``moto`` runs real DynamoDB semantics
in-process, and the connectors are the fakes from
:mod:`second.testing.fake_connectors`.
"""

from __future__ import annotations

from datetime import date

import boto3
import pytest
from moto import mock_aws

from second.graphs import service
from second.graphs.composition import ToolRegistry
from second.persistence.store import LivingGraphStore
from second.testing import demo_scenario
from second.testing.fake_connectors import ALL_FAKE_CONNECTORS
from second.tools.graph_tools import ALL_GRAPH_TOOLS

REGION = "us-west-2"
TABLE = "second_graph"


@pytest.fixture(autouse=True)
def _pin_the_date(monkeypatch):
    """Make the whole system agree with the seeded world's date.

    The demo scenario is built relative to one date. Left to the real clock, a
    test that goes through HTTP -- and so cannot pass ``today`` -- reads the
    actual date, and every seeded "upcoming" slot is in the past the moment the
    day rolls over. Three API tests started failing overnight for exactly that
    reason, which is the cheap version of the same thing happening on stage.
    """
    monkeypatch.setenv("SECOND_DEMO_TODAY", demo_scenario.TODAY.isoformat())


@pytest.fixture
def today() -> date:
    """The scenario's fixed "now".

    Injected everywhere as ``deps.today``. A test that passes on Tuesday and
    fails on Wednesday is worse than no test.
    """
    return demo_scenario.TODAY


@pytest.fixture
def empty_store():
    """A Living Graph store with a real table and nothing in it."""
    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
        store = LivingGraphStore(table=table)
        service.set_store(store)
        yield store
        service.set_store(None)


@pytest.fixture
def store(empty_store):
    """A store holding the seeded demo world.

    Three active goals, three weeks of history, a recurring 6pm conflict, a task
    dragged across four days, a booking blocked by an unsent leave request, and
    one slip nothing in the evidence explains.
    """
    empty_store.save(demo_scenario.living_graph())
    return empty_store


@pytest.fixture
def registry() -> ToolRegistry:
    """Every tool in the system: PLATFORM's real ones, CONNECTORS' fakes.

    Swap ``ALL_FAKE_CONNECTORS`` for the real module once CONNECTORS lands; the
    names and signatures are identical, so nothing that uses this changes.
    """
    return ToolRegistry([*ALL_GRAPH_TOOLS, *ALL_FAKE_CONNECTORS])


@pytest.fixture
def graph_tools_only() -> ToolRegistry:
    """Only PLATFORM's tools -- for asserting that a connector is genuinely absent."""
    return ToolRegistry(ALL_GRAPH_TOOLS)
