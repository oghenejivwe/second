"""An offline Strands model provider that replays a scripted sequence of turns.

Second's graphs are expensive to exercise against Bedrock: one run of the Daily
Graph is six agent invocations. During development we want to run the real
``Graph`` -- real nodes, real edges, real conditional routing, real tools -- with
a model whose answers we choose.

This provider speaks the Bedrock ``converse`` stream event shapes, so it drives
exactly the same parsing path in ``strands.event_loop.streaming`` that the real
``BedrockModel`` does. Nothing about the graph knows it is being faked.

Usage::

    model = ScriptedModel([
        ToolUse("read_graph", {"user_id": "demo", "layer": "goals"}),
        Structured({"task_id": "t1", "blocker_type": "UNMET_DEPENDENCY", ...}),
    ])
    agent = Agent(model=model, tools=[read_graph], structured_output_model=Diagnosis)
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from strands.models.model import Model
from strands.types.content import Message
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolSpec

T = TypeVar("T", bound=BaseModel)


@dataclass
class Text:
    """A plain assistant reply that ends the turn."""

    text: str


@dataclass
class ToolUse:
    """A request to call one of the agent's tools."""

    name: str
    input: dict[str, Any] = field(default_factory=dict)
    tool_use_id: str = "scripted-tool-use"


@dataclass
class Structured:
    """A structured-output emission.

    The event loop registers the structured-output tool under a name derived from
    the Pydantic model. The script should not have to know that name, so ``name``
    is left unset and resolved at stream time against the tool specs the agent
    actually offered -- whichever spec is not one of the agent's own tools.
    """

    payload: dict[str, Any]
    name: str | None = None
    tool_use_id: str = "scripted-structured-output"


Turn = Text | ToolUse | Structured
Script = Sequence[Turn] | Callable[[list[Message], list[ToolSpec] | None], Turn]


def _render_text(messages: list[Message]) -> str:
    """Flatten the text blocks of a conversation, for assertions about prompts."""
    parts: list[str] = []
    for message in messages:
        for block in message.get("content", []):
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
    return "\n".join(parts)


class ScriptedTurnsExhausted(RuntimeError):
    """Raised when the graph asked for more model turns than the script supplies.

    This is usually a real finding rather than a harness annoyance: it means a
    node looped more than the scenario expects, so the message is deliberately
    loud about which turn was requested.
    """


class ScriptedModel(Model):
    """A ``Model`` that returns pre-written turns instead of calling a provider."""

    def __init__(self, script: Script, *, agent_tool_names: Sequence[str] = ()) -> None:
        """Build a scripted model.

        Args:
            script: Either a fixed sequence of turns consumed in order, or a
                callable that picks a turn from the conversation so far and the
                tool specs on offer. The callable form handles branching.
            agent_tool_names: Names of the agent's own tools, used to identify
                which offered spec is the structured-output one. Optional.
        """
        self._script = script
        self._agent_tool_names = set(agent_tool_names)
        self._cursor = 0
        self._config: dict[str, Any] = {"model_id": "scripted"}
        self.calls: list[dict[str, Any]] = []

    # -- Model interface ------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        """Return the model configuration."""
        return self._config

    def update_config(self, **model_config: Any) -> None:
        """Update the model configuration."""
        self._config.update(model_config)

    async def stream(
        self,
        messages: list[Message],
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        """Replay the next scripted turn as Bedrock-shaped stream events."""
        turn = self._next_turn(messages, tool_specs)
        offered = [spec["name"] for spec in (tool_specs or [])]
        self.calls.append(
            {
                "turn": turn,
                "message_count": len(messages),
                "tool_specs": offered,
                "prompt_text": _render_text(messages),
            }
        )

        if isinstance(turn, Text):
            for event in self._text_events(turn.text):
                yield event
            return

        if isinstance(turn, Structured):
            name = turn.name or self._resolve_structured_tool_name(offered)
            for event in self._tool_use_events(turn.tool_use_id, name, turn.payload):
                yield event
            return

        for event in self._tool_use_events(turn.tool_use_id, turn.name, turn.input):
            yield event

    async def structured_output(
        self,
        output_model: type[T],
        prompt: list[Message],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, T | Any], None]:
        """Serve ``agent.structured_output(...)``, which bypasses the event loop."""
        turn = self._next_turn(prompt, None)
        if not isinstance(turn, Structured):
            raise ScriptedTurnsExhausted(
                f"structured_output() needs a Structured turn, script gave {type(turn).__name__}"
            )
        yield {"output": output_model(**turn.payload)}

    # -- internals ------------------------------------------------------

    def _next_turn(self, messages: list[Message], tool_specs: list[ToolSpec] | None) -> Turn:
        if callable(self._script):
            return self._script(messages, tool_specs)

        if self._cursor >= len(self._script):
            raise ScriptedTurnsExhausted(
                f"script has {len(self._script)} turn(s); the agent asked for turn {self._cursor + 1}. "
                "A node is looping more than the scenario expects."
            )

        turn = self._script[self._cursor]
        self._cursor += 1
        return turn

    def _resolve_structured_tool_name(self, offered: list[str]) -> str:
        candidates = [name for name in offered if name not in self._agent_tool_names]
        if not candidates:
            raise ScriptedTurnsExhausted(
                "a Structured turn was scripted but no structured-output tool spec was offered. "
                f"Offered: {offered}"
            )
        return candidates[-1]

    @staticmethod
    def _usage_event() -> StreamEvent:
        return {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "metrics": {"latencyMs": 0},
            }
        }

    @classmethod
    def _text_events(cls, text: str) -> list[StreamEvent]:
        return [
            {"messageStart": {"role": "assistant"}},
            {"contentBlockDelta": {"delta": {"text": text}, "contentBlockIndex": 0}},
            {"contentBlockStop": {"contentBlockIndex": 0}},
            {"messageStop": {"stopReason": "end_turn"}},
            cls._usage_event(),
        ]

    @classmethod
    def _tool_use_events(cls, tool_use_id: str, name: str, payload: dict[str, Any]) -> list[StreamEvent]:
        return [
            {"messageStart": {"role": "assistant"}},
            {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": tool_use_id, "name": name}},
                    "contentBlockIndex": 0,
                }
            },
            {
                "contentBlockDelta": {
                    "delta": {"toolUse": {"input": json.dumps(payload)}},
                    "contentBlockIndex": 0,
                }
            },
            {"contentBlockStop": {"contentBlockIndex": 0}},
            {"messageStop": {"stopReason": "tool_use"}},
            cls._usage_event(),
        ]
