"""How every agent in this package is built. One factory, twelve callers.

Three things live here because getting any of them wrong once is a defect and
getting them wrong twelve times is a product:

**Prompts are markdown files, not Python strings.** They will be rewritten forty
times before the deadline, and a diff of ``diagnostician.md`` is readable while a
diff of a triple-quoted string is not. :func:`load_prompt` reads
``prompts/<name>.md``, prepends the rules every agent shares, and substitutes the
run's placeholders.

**Placeholders use ``<<TOKEN>>``, not ``{token}``.** Several prompts contain JSON
examples, and ``str.format`` on a prompt containing ``{"task_id": ...}`` raises
:class:`KeyError` at build time -- or worse, silently eats a brace. An
unsubstituted token left in a finished prompt raises rather than shipping: an
agent told "Today is <<WHEN>>" reasons about nothing at all, and the failure is
invisible in the output.

**Every agent is named after its node.** :class:`~second.hooks.guard.RunawayGuard`
counts model calls per ``agent.name``; two agents sharing a name share a budget,
and a runaway in one is charged to the other.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel
from strands import Agent

from second.core.deps import AgentDeps, assert_privileges

PROMPTS = Path(__file__).parent / "prompts"

SHARED_RULES = "_shared"
"""Prepended to every agent prompt. The product promises, in one place."""

_PLACEHOLDER = re.compile(r"<<[A-Z_]+>>")


class PromptNotFound(RuntimeError):
    """An agent has no prompt file.

    Raised at build time rather than tolerated, because an ``Agent`` with
    ``system_prompt=None`` is a perfectly functional general assistant with none
    of this product's constraints, and it fails by being plausible.
    """


class UnresolvedPlaceholder(RuntimeError):
    """A prompt reached the model with a ``<<TOKEN>>`` still in it."""


def _read(name: str) -> str:
    path = PROMPTS / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise PromptNotFound(f"no prompt at {path}") from error
    if not text.strip():
        raise PromptNotFound(f"{path} is empty")
    return text


def when_line(deps: AgentDeps) -> str:
    """One line telling the agent what day it is, in the user's own timezone.

    Falls back to an explicit statement of ignorance rather than to an empty
    string. An agent that silently does not know today's date will still answer,
    and will answer about the wrong week.
    """
    if deps.clock is None:
        return "The current date is not available. Do not state or assume a date."
    return deps.when


def timezone_note(deps: AgentDeps) -> str:
    """Whether times in this run can be trusted to the hour.

    ``Clock.is_trustworthy`` is false when the zone was guessed from the machine
    rather than read from the user's calendar. A 07:00 block placed in the wrong
    zone is a slot the user has never once attended, so an agent that reasons
    about wall-clock times has to know when it is guessing.
    """
    if deps.clock is None or not deps.clock.is_trustworthy:
        return (
            "The timezone was GUESSED, not read from the user's calendar. Do not "
            "commit to precise clock times; say that the time needs confirming."
        )
    return f"Times are in {deps.clock.name}, read from the user's own calendar."


def load_prompt(name: str, deps: AgentDeps, **extra: str) -> str:
    """Build one agent's system prompt: shared rules, then its own.

    Args:
        name: The agent, which is also its prompt filename and its node id.
        deps: The run's dependencies, supplying the date, timezone and user id.
        extra: Additional ``TOKEN=value`` substitutions for ``<<TOKEN>>``.

    Returns:
        The finished system prompt.

    Raises:
        PromptNotFound: The agent has no prompt file, or the file is empty.
        UnresolvedPlaceholder: A ``<<TOKEN>>`` survived substitution.
    """
    text = f"{_read(SHARED_RULES)}\n\n---\n\n{_read(name)}"

    values = {
        "WHEN": when_line(deps),
        "TIMEZONE": timezone_note(deps),
        "USER_ID": deps.user_id,
        **extra,
    }
    for token, value in values.items():
        text = text.replace(f"<<{token}>>", str(value))

    if leftover := _PLACEHOLDER.findall(text):
        raise UnresolvedPlaceholder(
            f"{name}.md still contains {sorted(set(leftover))} after substitution"
        )
    return text


def build_agent(
    name: str,
    deps: AgentDeps,
    required_tools: tuple[str, ...],
    output_model: type[BaseModel] | None,
    *,
    structured_output_prompt: str | None = None,
    **prompt_vars: str,
) -> Agent:
    """Construct one agent from its declaration and the run's dependencies.

    Args:
        name: Node id, prompt filename and ``Agent.name``, all the same string.
        deps: What PLATFORM injected.
        required_tools: The module's ``REQUIRED_TOOLS``, re-asserted here.
        output_model: The module's ``OUTPUT_MODEL``.
        structured_output_prompt: What the model is told on the **forced** pass,
            when it ended a turn without emitting the schema. Worth overriding on
            any agent whose schema has an honest way to say "I don't know": the
            SDK's default says only "format the previous response as structured
            output", and on that pass the agent's own tools are gone, so this
            sentence is its last instruction before it must answer.
        prompt_vars: Extra ``<<TOKEN>>`` substitutions for this agent's prompt.

    Returns:
        The agent, ready for PLATFORM to wire into a node.

    Raises:
        ToolPrivilegeError: The injected toolbox is not exactly what was
            declared. PLATFORM checks this too; checking here as well means a
            factory called directly -- in a test, or in a future entry point --
            cannot skip the check.
    """
    assert_privileges(name, required_tools, deps)

    return Agent(
        name=name,
        model=deps.model,
        tools=list(deps.tools),
        hooks=list(deps.hooks),
        retry_strategy=deps.retry,
        structured_output_model=output_model,
        structured_output_prompt=structured_output_prompt,
        system_prompt=load_prompt(name, deps, **prompt_vars),
        # The SDK's default handler prints every tool call and every token to
        # stdout. That is useful in phase0_proof.py and is noise in a served
        # request, so agents are quiet and the audit hook is the record.
        callback_handler=None,
    )
