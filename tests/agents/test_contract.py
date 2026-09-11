"""The module contract, and the isolation the architecture claims.

None of this runs a graph. It is a structural sweep over all twelve agents,
asserting the things that are true before any model is called: that every module
exports the triple PLATFORM imports, that the tools each one declares are tools
that exist, that every agent carries the shared rules into its system prompt, and
that the privilege boundaries are real rather than described.

The sweep iterates ``second.agents.ALL_AGENTS`` rather than a list written out
here. A hardcoded copy drifts, and a drifted copy tests eleven things while
reporting twelve.
"""

from __future__ import annotations

import ast
import importlib
from datetime import date
from pathlib import Path

import pytest

from second.agents import ALL_AGENTS, DAILY_AGENTS, FEEDBACK_AGENTS, INTAKE_AGENTS
from second.agents import _base
from second.core.clock import Clock
from second.core.deps import AgentDeps, ToolPrivilegeError
from second.graphs.composition import TOOL_OWNERS
from second.testing.scripted_model import ScriptedModel, Text

DEMO_TZ = "Europe/London"
AGENTS_DIR = Path(_base.__file__).parent

CONNECTOR_TOOLS = frozenset(
    name for name, owner in TOOL_OWNERS.items() if owner == "CONNECTORS"
)
WRITE_TOOLS = frozenset(
    {"write_graph", "update_person_model", "set_goal_status", "record_completion"}
)


def deps_for(module, registry, **overrides) -> AgentDeps:
    """Dependencies carrying exactly what an agent declared it needs."""
    return AgentDeps(
        model=overrides.pop("model", ScriptedModel([Text("unused")])),
        tools=registry.resolve(overrides.pop("tools", module.REQUIRED_TOOLS)),
        clock=Clock.fixed(date(2026, 9, 10), zone_name=DEMO_TZ),
        user_id="demo",
        **overrides,
    )


def source_of(name: str) -> str:
    return (AGENTS_DIR / f"{name}.py").read_text(encoding="utf-8")


# -- the triple -------------------------------------------------------------


def test_all_twelve_agents_are_accounted_for():
    """The three graphs together are the whole package, with nothing spare."""
    assert len(ALL_AGENTS) == 12
    assert set(ALL_AGENTS) == set(INTAKE_AGENTS) | set(DAILY_AGENTS) | set(FEEDBACK_AGENTS)
    assert len(set(ALL_AGENTS)) == len(ALL_AGENTS), "an agent is listed twice"


@pytest.mark.parametrize("name", ALL_AGENTS)
def test_every_module_exports_the_platform_contract(name):
    """``REQUIRED_TOOLS``, ``OUTPUT_MODEL`` and ``build`` -- the whole seam."""
    module = importlib.import_module(f"second.agents.{name}")

    assert isinstance(module.REQUIRED_TOOLS, tuple)
    assert all(isinstance(tool, str) for tool in module.REQUIRED_TOOLS)
    assert hasattr(module, "OUTPUT_MODEL"), "OUTPUT_MODEL must exist even when it is None"
    assert callable(module.build)


@pytest.mark.parametrize("name", ALL_AGENTS)
def test_every_declared_tool_actually_exists(name):
    """A typo in REQUIRED_TOOLS otherwise surfaces only at graph construction."""
    module = importlib.import_module(f"second.agents.{name}")
    unknown = [tool for tool in module.REQUIRED_TOOLS if tool not in TOOL_OWNERS]
    assert not unknown, f"{name} declares tools nobody owns: {unknown}"


# -- building ---------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_AGENTS)
def test_every_agent_builds_with_exactly_what_it_declared(name, registry):
    module = importlib.import_module(f"second.agents.{name}")
    agent = module.build(deps_for(module, registry))

    assert sorted(agent.tool_names) == sorted(module.REQUIRED_TOOLS)
    assert agent._default_structured_output_model is module.OUTPUT_MODEL


def test_agent_names_are_their_node_ids_and_all_distinct(registry):
    """``RunawayGuard`` counts model calls per ``agent.name`` (hooks/guard.py:60-71).

    Two agents sharing a name share one budget, so a node that runs away is
    charged to whichever node happens to run next.
    """
    names = []
    for name in ALL_AGENTS:
        module = importlib.import_module(f"second.agents.{name}")
        agent = module.build(deps_for(module, registry))
        assert agent.name == name, f"{name} built an agent called {agent.name!r}"
        names.append(agent.name)

    assert len(set(names)) == len(ALL_AGENTS)


@pytest.mark.parametrize("name", ALL_AGENTS)
def test_every_system_prompt_carries_the_shared_rules(name, registry):
    """The product promises reach the model on every single agent.

    ``_base.load_prompt`` prepends ``prompts/_shared.md`` to each agent's own
    file, which is what makes "structural, never psychological" a property of
    the package rather than of whichever prompt remembered to say it.

    Mutation: drop the ``_read(SHARED_RULES)`` prepend from ``_base.load_prompt``
    and this fails for all twelve at once.
    """
    module = importlib.import_module(f"second.agents.{name}")
    prompt = module.build(deps_for(module, registry)).system_prompt

    assert "Structural, never psychological" in prompt
    assert "Evidence or silence" in prompt
    assert "Second never takes the irreversible step" in prompt


@pytest.mark.parametrize("name", ALL_AGENTS)
def test_every_prompt_is_substantive_and_localised(name, registry):
    module = importlib.import_module(f"second.agents.{name}")
    prompt = module.build(deps_for(module, registry)).system_prompt

    assert len(prompt) > 4000, "a thin prompt is a vague agent"
    assert "<<" not in prompt, "an unsubstituted placeholder reached the model"
    assert "Europe/London" in prompt, "the agent must know which timezone it reasons in"
    assert "Thursday 10 September 2026" in prompt


# -- least privilege --------------------------------------------------------


def test_the_communicator_has_no_tools_at_all(registry):
    """It cannot look anything up, so it cannot pad.

    Mutation: give ``communicator.REQUIRED_TOOLS`` a single entry and both
    halves of this fail.
    """
    from second.agents import communicator

    assert communicator.REQUIRED_TOOLS == ()

    deps = deps_for(communicator, registry, tools=("read_graph",))
    with pytest.raises(ToolPrivilegeError) as excinfo:
        communicator.build(deps)
    assert "read_graph" in str(excinfo.value)


def test_the_diagnostician_cannot_reach_gmail_or_the_calendar():
    """Its evidence arrives sanitised from the Observer or not at all."""
    from second.agents import diagnostician

    reachable = CONNECTOR_TOOLS & set(diagnostician.REQUIRED_TOOLS)
    assert not reachable, f"the Diagnostician could reach {sorted(reachable)}"


def test_the_interpreter_cannot_write():
    """The node that interprets speech cannot mutate the graph."""
    from second.agents import interpreter

    assert not WRITE_TOOLS & set(interpreter.REQUIRED_TOOLS)


def test_the_graph_updater_cannot_read():
    """It applies what it was handed; it cannot go looking for more.

    This is what makes the partial-write trap in ``write_graph`` survivable:
    an agent that cannot re-read a goal must only write goals it was given
    whole.
    """
    from second.agents import graph_updater

    assert "read_graph" not in graph_updater.REQUIRED_TOOLS


def test_nothing_in_the_system_can_send_or_delete(registry):
    """Structural, not prompted: no such tool exists to be called."""
    every_declared = {
        tool
        for name in ALL_AGENTS
        for tool in importlib.import_module(f"second.agents.{name}").REQUIRED_TOOLS
    }
    assert not any("send" in tool for tool in every_declared)
    assert not any("delete" in tool for tool in every_declared)
    assert not any("delete" in tool for tool in registry.names())


# -- no agent reaches across a domain boundary ------------------------------


@pytest.mark.parametrize("name", ALL_AGENTS)
def test_no_agent_module_imports_a_connector_or_the_platform(name):
    """An agent never imports a connector. Tools arrive through ``deps.tools``.

    Parsed rather than grepped, so a mention in a docstring does not fail and a
    real import cannot hide behind one.

    Mutation: add ``from second.tools import graph_tools`` to any agent module
    and this goes red for that module.
    """
    forbidden = ("second.tools", "second.voice", "second.graphs", "second.persistence")
    tree = ast.parse(source_of(name))

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    leaked = [
        module
        for module in imported
        for root in forbidden
        if module == root or module.startswith(f"{root}.")
    ]
    assert not leaked, f"{name} imports {leaked}"


@pytest.mark.parametrize("name", ALL_AGENTS)
def test_no_agent_module_composes_a_graph_or_builds_its_own_agent(name):
    """Composition is PLATFORM's. Agents are factories, never graphs."""
    tree = ast.parse(source_of(name))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            assert called not in {"Graph", "GraphBuilder", "add_edge", "add_node"}, (
                f"{name} wires a graph at line {node.lineno}"
            )
            assert called != "Agent", (
                f"{name} constructs Agent() directly at line {node.lineno}; use build_agent()"
            )


@pytest.mark.parametrize("name", ALL_AGENTS)
def test_no_agent_sets_model_parameters(name):
    """PLATFORM owns model configuration, including temperature and token caps."""
    source = source_of(name)
    assert "temperature" not in source
    assert "max_tokens" not in source


# -- the prompt loader's own guards -----------------------------------------


def test_a_missing_prompt_file_fails_loudly(monkeypatch, tmp_path):
    """An ``Agent`` with no system prompt is a general assistant with none of
    this product's constraints, and it fails by being plausible.

    Mutation: have ``_base._read`` return ``""`` instead of raising, and this
    goes red.
    """
    (tmp_path / "_shared.md").write_text("shared", encoding="utf-8")
    monkeypatch.setattr(_base, "PROMPTS", tmp_path)

    deps = AgentDeps(model=object(), clock=Clock.fixed(date(2026, 9, 10), zone_name=DEMO_TZ))
    with pytest.raises(_base.PromptNotFound) as excinfo:
        _base.load_prompt("nobody", deps)
    assert "nobody" in str(excinfo.value)


def test_an_empty_prompt_file_fails_loudly(monkeypatch, tmp_path):
    (tmp_path / "_shared.md").write_text("shared", encoding="utf-8")
    (tmp_path / "hollow.md").write_text("   \n\n", encoding="utf-8")
    monkeypatch.setattr(_base, "PROMPTS", tmp_path)

    deps = AgentDeps(model=object(), clock=Clock.fixed(date(2026, 9, 10), zone_name=DEMO_TZ))
    with pytest.raises(_base.PromptNotFound):
        _base.load_prompt("hollow", deps)


def test_an_unsubstituted_placeholder_never_reaches_the_model(monkeypatch, tmp_path):
    """"Today is <<WHEN>>" is an agent reasoning about nothing at all, and the
    failure is invisible in the output unless it is raised here.

    Mutation: delete the ``_PLACEHOLDER.findall`` check in ``_base.load_prompt``
    and this goes red.
    """
    (tmp_path / "_shared.md").write_text("shared", encoding="utf-8")
    (tmp_path / "leaky.md").write_text("Today is <<WHEN>> and <<NOT_A_REAL_TOKEN>>.", encoding="utf-8")
    monkeypatch.setattr(_base, "PROMPTS", tmp_path)

    deps = AgentDeps(model=object(), clock=Clock.fixed(date(2026, 9, 10), zone_name=DEMO_TZ))
    with pytest.raises(_base.UnresolvedPlaceholder) as excinfo:
        _base.load_prompt("leaky", deps)
    assert "NOT_A_REAL_TOKEN" in str(excinfo.value)


def test_an_agent_with_no_clock_says_so_rather_than_guessing():
    """Failure direction: state the ignorance. An agent that silently does not
    know the date still answers, and answers about the wrong week.
    """
    blind = AgentDeps(model=object())
    assert "not available" in _base.when_line(blind)
    assert "GUESSED" in _base.timezone_note(blind)


def test_a_guessed_timezone_is_declared_to_the_agent():
    """``Clock.detect`` falling back to the machine is not trustworthy, and the
    Scheduler has to know before it places an 07:00 block.
    """
    guessed = Clock.detect(now=None)
    if guessed.is_trustworthy:  # pragma: no cover - depends on the host
        pytest.skip("this machine resolved a trustworthy zone")
    assert "GUESSED" in _base.timezone_note(AgentDeps(model=object(), clock=guessed))
