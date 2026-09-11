"""The twelve agents. What each one is for, what it may see, what it returns.

Every module here exports the same triple, and that triple is the whole contract
between AGENTS and PLATFORM::

    REQUIRED_TOOLS: tuple[str, ...]        the tool names this agent needs
    OUTPUT_MODEL: type[BaseModel] | None   its structured output, or None
    def build(deps: AgentDeps) -> Agent    the factory

**No module in this package constructs a ``Graph``, an edge or a condition**, and
none of them imports a connector. Tools arrive through ``deps.tools``, chosen by
PLATFORM from the declaration above and asserted to match it exactly. That is
context isolation as a security property: the Observer sees raw email, the
Diagnostician sees only the Observer's sanitised report, and the Communicator has
no tools at all so it cannot look anything up to pad with.

The three graphs and the agents in each:

======================  ===================================================
Intake                  extractor, cascader, route_planner, scheduler,
                        resource_finder
Daily                   observer, diagnostician, adapter, preparer,
                        communicator
Feedback                interpreter, graph_updater
======================  ===================================================
"""

from __future__ import annotations

INTAKE_AGENTS: tuple[str, ...] = (
    "extractor",
    "cascader",
    "route_planner",
    "scheduler",
    "resource_finder",
)

DAILY_AGENTS: tuple[str, ...] = (
    "observer",
    "diagnostician",
    "adapter",
    "preparer",
    "communicator",
)

FEEDBACK_AGENTS: tuple[str, ...] = ("interpreter", "graph_updater")

ALL_AGENTS: tuple[str, ...] = INTAKE_AGENTS + DAILY_AGENTS + FEEDBACK_AGENTS
"""Every agent module in this package, for tests that sweep all of them.

Kept as data rather than discovered by walking the directory, so that deleting a
module makes the sweep fail loudly instead of quietly testing eleven things."""
