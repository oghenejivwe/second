"""Wiring agents into graphs, and deciding what each one is allowed to touch.

PLATFORM owns this file because it is the composition root: four owners on one
composition root collide, and because **who gets which tool is a security
decision**, not an implementation detail of the agent that wants them.

The isolation the architecture claims is enforced here and nowhere else:

    Observer        sees raw calendar and raw email
    Diagnostician   sees a sanitised evidence bundle, and cannot reach either
    Adapter         sees the verdict, and can move a calendar event
    Communicator    has no tools at all, so it cannot look anything up to pad with
    Preparer        can draft an email; nothing in the system can send one

An agent declares what it needs; it never imports a connector. If the declaration
and the injection disagree, :func:`~second.core.deps.assert_privileges` raises at
**graph construction** -- loudly, before a run, rather than quietly in front of a
judge.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel
from strands import Agent
from strands.models.model import Model
from strands.types.tools import AgentTool

from second.core.clock import Clock
from second.core.deps import AgentDeps, assert_privileges
from second.settings import (
    ANTHROPIC_API_KEY_ENV,
    ANTHROPIC_CLIENT_ARGS,
    ANTHROPIC_MODEL_ID,
    AWS_REGION,
    BEDROCK_MODEL_ID,
    GEMINI_API_KEY_ENV,
    GEMINI_MODEL_ID,
    MODEL_PROVIDER,
    RETRY_INITIAL_DELAY,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY,
)

logger = logging.getLogger(__name__)

TOOL_OWNERS = {
    "get_calendar_events": "CONNECTORS",
    "find_free_slots": "CONNECTORS",
    "create_event": "CONNECTORS",
    "reschedule_event": "CONNECTORS",
    "search_gmail": "CONNECTORS",
    "draft_email": "CONNECTORS",
    "web_search": "CONNECTORS",
    "read_graph": "PLATFORM",
    "write_graph": "PLATFORM",
    "update_person_model": "PLATFORM",
    "record_diagnosis": "PLATFORM",
    "record_completion": "PLATFORM",
    "set_goal_status": "PLATFORM",
}
"""Every tool in the system and the instance responsible for it.

Kept here so a missing tool produces "CONNECTORS has not landed search_gmail yet"
rather than a KeyError three frames deep."""


class MissingTool(RuntimeError):
    """An agent declared a tool nobody has built yet."""


class MissingAgent(RuntimeError):
    """A graph node references an agent module that does not exist yet."""


class ModelProviderNotConfigured(RuntimeError):
    """No usable route to a model. Says which one is missing and how to fix it."""


# ---------------------------------------------------------------------------


class ToolRegistry:
    """Resolves tool names to the actual callables, or says who owes them."""

    def __init__(self, tools: Iterable[AgentTool] = ()) -> None:
        self._tools: dict[str, AgentTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: AgentTool) -> None:
        """Add a tool under its own declared name."""
        self._tools[tool.tool_name] = tool

    def names(self) -> set[str]:
        """Every tool currently available."""
        return set(self._tools)

    def resolve(self, required: tuple[str, ...]) -> list[AgentTool]:
        """Return exactly the named tools, in the order declared.

        Raises:
            MissingTool: Naming the tools and which instance owns each, so the
                message is actionable rather than a stack trace.
        """
        missing = [name for name in required if name not in self._tools]
        if missing:
            owed = ", ".join(f"{name} ({TOOL_OWNERS.get(name, 'unknown owner')})" for name in missing)
            raise MissingTool(f"not available yet: {owed}")
        return [self._tools[name] for name in required]


def default_registry() -> ToolRegistry:
    """Every tool that currently exists.

    PLATFORM's graph tools always load. The connectors are imported optionally,
    so PLATFORM can be developed and tested before CONNECTORS lands -- a missing
    connector surfaces as a clear ``MissingTool`` at composition time rather than
    an ImportError at startup.
    """
    from second.tools.graph_tools import ALL_GRAPH_TOOLS

    registry = ToolRegistry(ALL_GRAPH_TOOLS)

    for module_name in ("calendar_tools", "gmail_tools", "search_tools"):
        try:
            module = importlib.import_module(f"second.tools.{module_name}")
        except ImportError:
            logger.info("second.tools.%s not built yet; its tools are unavailable", module_name)
            continue
        for attribute in vars(module).values():
            if isinstance(attribute, AgentTool):
                registry.register(attribute)

    return registry


# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentSpec:
    """What an agent module declares about itself."""

    node_id: str
    required_tools: tuple[str, ...]
    output_model: type[BaseModel] | None
    factory: Callable[[AgentDeps], Agent]


def load_agent_spec(node_id: str, module_name: str | None = None) -> AgentSpec:
    """Read an agent module's declaration.

    Every module in ``second.agents`` exports ``REQUIRED_TOOLS``,
    ``OUTPUT_MODEL`` and ``build(deps) -> Agent``. That triple is the contract
    between PLATFORM and AGENTS.

    Raises:
        MissingAgent: The module does not exist, or does not export the triple.
    """
    target = f"second.agents.{module_name or node_id}"
    try:
        module = importlib.import_module(target)
    except ImportError as error:
        raise MissingAgent(f"{target} does not exist yet (owned by AGENTS)") from error

    try:
        return AgentSpec(
            node_id=node_id,
            required_tools=tuple(module.REQUIRED_TOOLS),
            output_model=module.OUTPUT_MODEL,
            factory=module.build,
        )
    except AttributeError as error:
        raise MissingAgent(
            f"{target} must export REQUIRED_TOOLS, OUTPUT_MODEL and build(deps)"
        ) from error


def resolve_clock(explicit_timezone: str | None = None) -> Clock:
    """Work out what time it is for this user, without asking them.

    Tries the user's own Google Calendar first, because that is where their
    timezone actually lives and it follows them when they travel. Falls back to
    the machine, then to UTC -- and :attr:`Clock.is_trustworthy` records which,
    so an agent can decline to be precise about times it guessed.

    CONNECTORS supplies ``get_calendar_timezone() -> str`` returning an IANA name
    such as ``"Europe/London"``. Until that lands, this quietly falls through to
    the machine's timezone, which is right for local development.
    """
    calendar_timezone: str | None = None
    try:
        from second.tools.calendar_tools import get_calendar_timezone

        calendar_timezone = get_calendar_timezone()
    except (ImportError, AttributeError):
        logger.info("calendar timezone unavailable; falling back to the machine")
    except Exception:  # noqa: BLE001 - a clock lookup never breaks a run
        logger.warning("calendar timezone lookup failed; falling back", exc_info=True)

    return Clock.detect(explicit=explicit_timezone, calendar_timezone=calendar_timezone)


def build_model(
    model_id: str | None = None,
    region: str = AWS_REGION,
    provider: str | None = None,
) -> Model:
    """Construct the model provider. Claude either way.

    Two routes to the same model, chosen by ``SECOND_MODEL_PROVIDER``:

    * ``"anthropic"`` (default) -- Anthropic's own API. **Bedrock refuses
      Anthropic models on this account**, reproducibly, on both a current and a
      two-year-old Claude model: *"Access to Anthropic models is not allowed from
      unsupported countries, regions, or territories."* The account is registered
      in Nigeria, which is on Anthropic's own published supported list, so the
      direct API is open where Bedrock is not.
    * ``"bedrock"`` -- kept working, and one environment variable away, for the
      day that block lifts.

    Retries are NOT configured here. ``retry_strategy`` is an ``Agent`` argument,
    not a model config key -- passing it to either provider is silently discarded
    with only a UserWarning, which is exactly the kind of "I configured that"
    that turns out to be false on stage. It arrives via ``AgentDeps.retry``.

    **This changes nothing else.** Strands treats both as ``Model``; structured
    output goes through the same tool-call machinery on both; every graph, tool,
    condition and test is provider-agnostic. AgentCore still deploys our code --
    it runs the app, it does not decide where the model comes from -- and
    DynamoDB, S3, Transcribe, EventBridge and Lambda are untouched.
    """
    chosen = (provider or MODEL_PROVIDER).lower()

    if chosen == "anthropic":
        import os

        from strands.models.anthropic import AnthropicModel

        if not os.environ.get(ANTHROPIC_API_KEY_ENV):
            raise ModelProviderNotConfigured(
                f"{ANTHROPIC_API_KEY_ENV} is not set. Get a key at console.anthropic.com "
                f"and export it; or set SECOND_MODEL_PROVIDER=bedrock to use Bedrock instead."
            )
        # max_tokens is REQUIRED here. Bedrock did not require it; omitting it
        # fails at construction rather than at call time.
        return AnthropicModel(
            client_args=dict(ANTHROPIC_CLIENT_ARGS),
            model_id=model_id or ANTHROPIC_MODEL_ID,
            max_tokens=8192,
        )

    if chosen == "gemini":
        import os

        from strands.models.gemini import GeminiModel

        if not os.environ.get(GEMINI_API_KEY_ENV):
            raise ModelProviderNotConfigured(
                f"{GEMINI_API_KEY_ENV} is not set. Get a free key at aistudio.google.com "
                f"-- no card required."
            )
        return GeminiModel(
            model_id=model_id or GEMINI_MODEL_ID,
            params={"max_output_tokens": 8192},
        )

    if chosen != "bedrock":
        raise ModelProviderNotConfigured(
            f"SECOND_MODEL_PROVIDER must be 'anthropic', 'gemini' or 'bedrock'; got {chosen!r}"
        )

    from strands.models.bedrock import BedrockModel

    # model_id is always explicit: the SDK's "you are using the default model"
    # warning is dead code, so nothing would catch a missing one at runtime.
    # Note region_name and boto_session are mutually exclusive.
    return BedrockModel(model_id=model_id or BEDROCK_MODEL_ID, region_name=region)


def build_node_agent(
    spec: AgentSpec,
    *,
    model: Model,
    registry: ToolRegistry,
    hooks: list[Any],
    user_id: str,
    clock: Clock | None = None,
    context: dict[str, Any] | None = None,
) -> Agent:
    """Build one node's agent with exactly the tools it declared -- no more.

    The privilege assertion runs before the factory, so an agent that has grown
    a dependency it did not declare fails here rather than at run time.
    """
    from strands.event_loop._retry import ModelRetryStrategy

    deps = AgentDeps(
        model=model,
        retry=ModelRetryStrategy(
            max_attempts=RETRY_MAX_ATTEMPTS,
            initial_delay=RETRY_INITIAL_DELAY,
            max_delay=RETRY_MAX_DELAY,
        ),
        tools=registry.resolve(spec.required_tools),
        hooks=hooks,
        user_id=user_id,
        clock=clock,
        context=context or {},
    )
    assert_privileges(spec.node_id, spec.required_tools, deps)
    return spec.factory(deps)


# ---------------------------------------------------------------------------


def apply_guardrails(builder: Any) -> Any:
    """Put the standard execution ceilings on a graph builder.

    A graph with no limits and any cycle only logs a warning and can spin
    forever. Note that hitting the cap sets the result status to ``FAILED``
    **silently** -- which is why :meth:`ComposedGraph.run` checks the status
    explicitly rather than assuming a returned result is a successful one.
    """
    from second.settings import GRAPH_TIMEOUT_SECONDS, MAX_NODE_EXECUTIONS, NODE_TIMEOUT_SECONDS

    builder.set_max_node_executions(MAX_NODE_EXECUTIONS)
    builder.set_node_timeout(NODE_TIMEOUT_SECONDS)
    builder.set_execution_timeout(GRAPH_TIMEOUT_SECONDS)
    return builder


class GraphRunFailed(RuntimeError):
    """A graph finished without completing."""


@dataclass
class ComposedGraph:
    """A built graph, its audit log, and everything a run needs injected."""

    graph: Any
    audit: Any
    store: Any
    user_id: str
    clock: Any = None

    async def run(self, task: str, **extra_state: Any) -> Any:
        """Invoke the graph and flush its audit log.

        The store is injected under ``invocation_state["second"]`` -- namespaced
        because the SDK writes reserved keys straight onto the caller's own dict
        mid-run, so a bare ``{"store": ...}`` would sit next to ``agent`` and
        ``messages`` and eventually collide.
        """
        from strands.multiagent.base import Status
        from second.settings import NAMESPACE

        state = {
            NAMESPACE: {
                "store": self.store,
                "user_id": self.user_id,
                "clock": self.clock,
                **extra_state,
            }
        }
        try:
            result = await self.graph.invoke_async(task, state)
        finally:
            self.audit.flush()

        if result.status is not Status.COMPLETED:
            # Hitting max_node_executions raises nothing; it just sets FAILED.
            raise GraphRunFailed(
                f"graph finished with status {result.status} after "
                f"{result.execution_count} node execution(s); "
                f"completed {[node.node_id for node in result.execution_order]}"
            )
        return result
