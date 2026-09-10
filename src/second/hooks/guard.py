"""A cap on how many times one node may call the model.

**This replaces a control that did not exist.** ``INVOCATION_LIMITS`` sat in
settings looking like a backstop against a runaway structured-output loop, and
nothing consumed it. AGENTS found it. The reason it could not work is real rather
than an oversight: ``limits`` is an argument to ``Agent.invoke_async``, and inside
a ``Graph`` the SDK makes that call itself -- there is no seam to pass it through.

So the cap is enforced where there is a seam: a hook on every model call.

The loop worth fearing is specific. Structured output is a forced tool call, and
a Pydantic validation failure is fed back to the model as an error tool result
**with no attempt cap of its own**. A model that keeps producing a not-quite-valid
object will keep being asked. ``NODE_TIMEOUT_SECONDS`` bounds that in wall-clock,
but sixty seconds of retries is sixty seconds of tokens, and on a metered API that
is money rather than merely time.

Failure direction: **raise and fail the node.** A graph that dies loudly at call
thirteen is diagnosable. One that silently burns the budget is not.

One thing to know when reading a failed run: **the SDK wraps a hook exception in
``EventLoopException``**, so ``RunawayLoop`` never reaches the caller by type.
The message survives intact, which is what a human debugging a stuck run actually
needs -- but do not write ``except RunawayLoop`` anywhere and expect it to catch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from strands.hooks import BeforeModelCallEvent, HookProvider, HookRegistry

logger = logging.getLogger(__name__)


class RunawayLoop(RuntimeError):
    """One node asked the model more times than any legitimate run needs."""


@dataclass
class RunawayGuard(HookProvider):
    """Counts model calls per agent and stops a node that will not settle.

    Args:
        max_model_calls: Per agent, per run. The default of 12 is deliberately
            generous -- the busiest node in this system is the Preparer, which
            makes at most four tool calls plus the structured-output pass, so
            twelve means something is genuinely wrong rather than merely busy.
    """

    max_model_calls: int = 12
    counts: dict[str, int] = field(default_factory=dict)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Subscribe to every model call. Registered per agent, like the audit hook."""
        registry.add_callback(BeforeModelCallEvent, self._count)

    def _count(self, event: BeforeModelCallEvent) -> None:
        name = getattr(getattr(event, "agent", None), "name", "?")
        self.counts[name] = self.counts.get(name, 0) + 1

        if self.counts[name] > self.max_model_calls:
            logger.error("runaway: %s made %d model calls", name, self.counts[name])
            raise RunawayLoop(
                f"{name} asked the model {self.counts[name]} times, over the cap of "
                f"{self.max_model_calls}. This is almost always a structured-output "
                f"validation loop: the model keeps returning an object Pydantic "
                f"rejects, and the SDK keeps re-asking with no attempt cap."
            )

    def busiest(self) -> tuple[str, int] | None:
        """The agent that worked hardest this run. Useful in a report."""
        if not self.counts:
            return None
        name = max(self.counts, key=lambda key: self.counts[key])
        return name, self.counts[name]
