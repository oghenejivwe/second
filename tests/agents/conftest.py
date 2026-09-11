"""One scripted model for a whole graph, routed to the node that asked.

``build_daily_graph(model=...)`` hands the same provider to every node, so a
flat sequence of turns is only usable for a single-node run. These tests run the
real graphs with the real agent modules, which means the script has to know
*which* node is calling.

It works this out from the tool specs on offer. Every node is given exactly its
own ``REQUIRED_TOOLS`` plus -- when it has a structured output -- one more spec
named after the Pydantic model (``structured_output_tool.py:60-66``). That set is
unique per node and, because it is derived from the agent modules themselves
rather than written out here, it cannot drift away from them.
"""

from __future__ import annotations

import importlib

import pytest

from second.agents import ALL_AGENTS
from second.testing.scripted_model import ScriptedModel, ScriptedTurnsExhausted, Structured


def _offered_signature(name: str) -> frozenset[str]:
    """The exact set of tool names a node is offered, from its own declaration."""
    module = importlib.import_module(f"second.agents.{name}")
    names = set(module.REQUIRED_TOOLS)
    if module.OUTPUT_MODEL is not None:
        names.add(module.OUTPUT_MODEL.__name__)
    return frozenset(names)


SIGNATURES: dict[frozenset[str], str] = {_offered_signature(n): n for n in ALL_AGENTS}


def test_signatures_are_unique_per_node():
    """The router only works because no two agents are offered the same set."""
    assert len(SIGNATURES) == len(ALL_AGENTS)


class NodeRouter:
    """A ``ScriptedModel`` script that serves each node its own turns, in order.

    Args:
        scripts: Turns keyed by node id. A node that is asked for more turns than
            it was scripted raises, which is a real finding rather than a harness
            annoyance -- it means the node looped.
    """

    def __init__(self, scripts: dict[str, list]) -> None:
        unknown = set(scripts) - set(ALL_AGENTS)
        assert not unknown, f"scripted a node that does not exist: {sorted(unknown)}"
        self.scripts = scripts
        self.cursors: dict[str, int] = {}
        self.prompts: dict[str, list[str]] = {}
        self.calls: list[str] = []

    def __call__(self, messages, tool_specs):
        offered = frozenset(spec["name"] for spec in (tool_specs or []))
        node = SIGNATURES.get(offered)
        if node is None:
            raise ScriptedTurnsExhausted(f"no agent is offered exactly {sorted(offered)}")

        turns = self.scripts.get(node)
        if turns is None:
            raise ScriptedTurnsExhausted(f"{node!r} ran but was not scripted")

        index = self.cursors.get(node, 0)
        if index >= len(turns):
            raise ScriptedTurnsExhausted(
                f"{node!r} has {len(turns)} scripted turn(s) and asked for turn {index + 1}; "
                "the node is looping more than the scenario expects"
            )

        self.cursors[node] = index + 1
        self.calls.append(node)
        text = "\n".join(
            str(block["text"])
            for message in messages
            for block in message.get("content", [])
            if isinstance(block, dict) and "text" in block
        )
        self.prompts.setdefault(node, []).append(text)

        turn = turns[index]
        if isinstance(turn, Structured) and turn.name is None:
            module = importlib.import_module(f"second.agents.{node}")
            turn = Structured(turn.payload, name=module.OUTPUT_MODEL.__name__)
        return turn

    # -- assertions the tests make against a finished run ------------------

    def ran(self, node: str) -> int:
        """How many model calls that node made."""
        return self.cursors.get(node, 0)

    def prompt_for(self, node: str) -> str:
        """Everything that reached a node's first model call, as text."""
        return self.prompts.get(node, [""])[0]


@pytest.fixture
def router():
    """Build a :class:`NodeRouter` and the ``ScriptedModel`` wrapping it."""

    def make(scripts: dict[str, list]) -> tuple[NodeRouter, ScriptedModel]:
        routed = NodeRouter(scripts)
        return routed, ScriptedModel(routed)

    return make
