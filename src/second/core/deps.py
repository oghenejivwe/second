"""How an agent receives everything it is allowed to touch.

Context isolation is a security property of this architecture, not a style
preference. The Observer sees raw calendar entries and raw email. The
Diagnostician sees a sanitised evidence bundle. The Adapter sees only the
verdict. None of them can widen that on their own, because **an agent never
imports a connector**. PLATFORM builds a ``ToolBox`` per agent and injects it.

Each agent module in ``second.agents`` exports three things:

    REQUIRED_TOOLS: tuple[str, ...]      the tool names this agent needs
    OUTPUT_MODEL: type[BaseModel] | None the structured output, or None
    def build(deps: AgentDeps) -> Agent  the factory

PLATFORM asserts that the injected toolbox matches ``REQUIRED_TOOLS`` exactly --
no more, no less -- before wiring the agent into a graph. An agent that quietly
grows a dependency fails that assertion instead of shipping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from strands.hooks import HookProvider
from strands.models.model import Model
from strands.types.tools import AgentTool

from second.core.clock import Clock


@dataclass(frozen=True)
class AgentDeps:
    """Everything an agent factory is given. It gets nothing else."""

    model: Model
    """The model provider. ``BedrockModel`` in production, ``ScriptedModel`` in tests."""

    tools: list[AgentTool] = field(default_factory=list)
    """Exactly the tools this agent may call, injected by PLATFORM."""

    hooks: list[HookProvider] = field(default_factory=list)
    """The shared audit log. Pass straight through to ``Agent(hooks=...)``."""

    user_id: str = "demo"
    """Single hardcoded demo user for this build."""

    clock: Clock | None = None
    """The current moment in the user's own timezone.

    Nobody is asked what timezone they are in -- it is read from their Google
    Calendar, which is the authority and which follows them when they travel.
    See :mod:`second.core.clock`.

    Injected rather than read from the system clock at the point of use, so a
    seeded scenario reproduces.
    """

    context: dict[str, Any] = field(default_factory=dict)
    """Sanitised, agent-specific context. See each agent's brief for its shape."""

    @property
    def today(self) -> date | None:
        """The user's today, which is not necessarily UTC's."""
        return self.clock.today if self.clock else None

    @property
    def when(self) -> str:
        """One line to put in a system prompt, so the agent reasons in local time."""
        return self.clock.describe() if self.clock else ""

    def tool_names(self) -> set[str]:
        """The names of the tools actually injected."""
        return {tool.tool_name for tool in self.tools}


class ToolPrivilegeError(RuntimeError):
    """Raised when an agent is wired with the wrong tools.

    Fails loudly at graph construction rather than quietly at runtime, because a
    Diagnostician that can reach ``draft_email`` is a defect that would otherwise
    only surface in front of a judge.
    """


def assert_privileges(agent_name: str, required: tuple[str, ...], deps: AgentDeps) -> None:
    """Check the injected toolbox is exactly what the agent declared.

    Args:
        agent_name: The agent being wired, for the error message.
        required: The agent module's ``REQUIRED_TOOLS``.
        deps: The dependencies about to be handed to its factory.

    Raises:
        ToolPrivilegeError: If any declared tool is missing, or any undeclared
            tool was injected.
    """
    injected = deps.tool_names()
    expected = set(required)
    if injected == expected:
        return

    missing = sorted(expected - injected)
    extra = sorted(injected - expected)
    parts = [f"{agent_name} tool privileges do not match its declaration."]
    if missing:
        parts.append(f"missing: {missing}")
    if extra:
        parts.append(f"not permitted: {extra}")
    raise ToolPrivilegeError(" ".join(parts))
