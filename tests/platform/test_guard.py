"""The runaway cap, proved by making a node run away.

This replaces INVOCATION_LIMITS, which sat in settings looking like a control and
was consumed by nothing. A control nobody tested is the same thing.
"""

from __future__ import annotations

import pytest
from strands import Agent

from second.hooks.guard import RunawayGuard, RunawayLoop
from second.testing.scripted_model import ScriptedModel, Text, ToolUse


def test_a_node_that_will_not_settle_is_stopped(registry):
    """A structured-output validation loop, simulated.

    The model keeps calling a tool and never finishing. Without the guard this
    runs until the node timeout, burning tokens the whole way.
    """
    guard = RunawayGuard(max_model_calls=5)
    forever = lambda messages, tool_specs: ToolUse("read_graph", {"user_id": "demo", "layer": "goals"})

    agent = Agent(
        name="stuck",
        model=ScriptedModel(forever, agent_tool_names=list(registry.names())),
        tools=registry.resolve(("read_graph",)),
        hooks=[guard],
        system_prompt="stub",
    )

    # The SDK wraps a hook exception in EventLoopException, so RunawayLoop never
    # reaches the caller by type. The message survives, which is what a human
    # reading a failed run actually needs.
    from strands.types.exceptions import EventLoopException

    with pytest.raises((RunawayLoop, EventLoopException)) as excinfo:
        agent("go")

    assert "stuck" in str(excinfo.value)
    assert "validation loop" in str(excinfo.value), "the message names the likely cause"
    assert guard.counts["stuck"] == 6, "stopped one past the cap, not later"


def test_a_normal_run_is_untouched(registry):
    guard = RunawayGuard(max_model_calls=12)
    agent = Agent(
        name="ordinary",
        model=ScriptedModel(
            [ToolUse("read_graph", {"user_id": "demo", "layer": "goals"}), Text("done")],
            agent_tool_names=list(registry.names()),
        ),
        tools=registry.resolve(("read_graph",)),
        hooks=[guard],
        system_prompt="stub",
    )

    agent("go", invocation_state={"second": {}})
    assert guard.counts["ordinary"] <= 12
    assert guard.busiest()[0] == "ordinary"


def test_the_cap_is_per_agent_not_global(registry):
    """One busy node must not starve the next one."""
    guard = RunawayGuard(max_model_calls=3)
    guard.counts = {"observer": 3}

    class _Event:
        agent = type("A", (), {"name": "diagnostician"})()

    guard._count(_Event())
    assert guard.counts["diagnostician"] == 1, "a fresh node starts at zero"
