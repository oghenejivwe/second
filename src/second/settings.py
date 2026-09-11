"""Every pinned value in one place.

These are decisions, not preferences. Each carries the reason it was chosen,
because a value without a reason gets quietly changed by the next person who
finds it inconvenient.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# --- Which Claude, and from where ------------------------------------------

MODEL_PROVIDER = os.environ.get("SECOND_MODEL_PROVIDER", "anthropic")
"""``"anthropic"`` (direct API), ``"gemini"`` (free tier) or ``"bedrock"``.

Defaults to the direct API because **Bedrock refuses Anthropic models on this
account**. Verified in CloudShell on 2026-09-10, reproducibly, on both a current
and a two-year-old Claude model:

    ValidationException: Access to Anthropic models is not allowed from
    unsupported countries, regions, or territories.

The account is registered in Nigeria, which **is** on Anthropic's own published
supported-countries list -- for both the commercial API and Claude.ai. So AWS
applies a narrower country list to Anthropic-on-Bedrock than Anthropic applies to
its own API, and the direct API is open to us where Bedrock is not.

Nothing else in the build changes. Strands' ``AnthropicModel`` and
``BedrockModel`` are interchangeable behind ``build_model()``, structured output
works identically on both, and **AgentCore deployment is unaffected** -- it runs
our code, it does not dictate where the model comes from. DynamoDB, S3,
Transcribe, EventBridge and Lambda all stay exactly as they were.

Flip to ``"bedrock"`` the day the block lifts; one environment variable.
"""

ANTHROPIC_MODEL_ID = "claude-sonnet-5"
"""The direct-API model id. No ``global.`` prefix -- that was a Bedrock
inference-profile artifact and means nothing here.

Sonnet 5 rather than 4.6: newer, and cheaper at $2/$10 per MTok. The earlier
reservation about Sonnet 5 was specifically that it drops *Bedrock-native*
structured output -- irrelevant on this route, where Strands implements
structured output as a forced tool call.

**Do not switch this to a Fable model.** Fable returns 400 on forced tool choice,
and forced tool choice is exactly how Strands produces structured output. Typed
output is the spine of this build; a model that cannot be forced into a tool call
breaks every routing decision in the Daily graph."""

ANTHROPIC_CLIENT_ARGS = {"max_retries": 3, "timeout": 30.0}
"""HTTP-level retry and timeout, passed to the Anthropic client.

Separate from ``Agent(retry_strategy=...)``, which governs model-call retries
inside the event loop. Both are wanted: one survives a flaky socket, the other
survives an overloaded model."""

ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
"""Read from the environment, never from a file in this repo."""


# --- The free escape hatch --------------------------------------------------

GEMINI_MODEL_ID = os.environ.get("SECOND_GEMINI_MODEL", "gemini-2.5-flash")
"""Free-tier fallback, if paying for Claude turns out not to be possible.

Genuinely free rather than trial credit, no card, and available in Nigeria --
the opposite of the Bedrock problem. Forced tool choice works, which is the
thing that rules most cheap options out: Strands' ``{"any": {}}`` maps to
``FunctionCallingConfigMode.ANY`` in ``models/gemini.py``, and Strands narrows the
tool list to the output schema in forced mode so ANY cannot wander.

**Two things before relying on it.** Google's unpaid-tier terms say human
reviewers may read API input and output -- and Second quotes real calendar
entries and real email, so a free-tier demo must run on synthetic data. And
Gemini may reject a deeply nested schema under ANY mode; ``ExtractionResult`` is
the one to test first."""

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"


# --- AWS -------------------------------------------------------------------

AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
"""us-west-2. Full AgentCore coverage, and it is also Strands'
``DEFAULT_BEDROCK_REGION`` (models/bedrock.py:46), so a missing AWS_REGION
degrades to the correct region rather than to a split brain."""

BEDROCK_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
"""The ``global.`` prefix is load-bearing. Sonnet 4.6 has no in-region endpoint
outside eu-west-2, so a bare ``anthropic.claude-sonnet-4-6`` fails with
``ValidationException ... on-demand throughput isn't supported``. This is also
the SDK's own default (models/bedrock.py:44)."""

BEDROCK_CHEAP_MODEL_ID = "global.anthropic.claude-haiku-4-5"
"""For classification and extraction sub-steps if the token bill bites. Planning
and diagnosis stay on Sonnet."""

TABLE_NAME = os.environ.get("SECOND_TABLE", "second_graph")
S3_BUCKET = os.environ.get("SECOND_BUCKET", "second-voice-demo")

DEMO_USER_ID = "demo"
"""Single hardcoded user. No auth in this build."""


# --- Run limits ------------------------------------------------------------

MAX_MODEL_CALLS_PER_NODE = 12
"""The real cap on a runaway structured-output loop. Enforced by ``RunawayGuard``.

There was an ``INVOCATION_LIMITS`` here that nothing consumed -- a control that
existed only in settings. AGENTS found it. It could not have worked: ``limits`` is
an argument to ``Agent.invoke_async``, and inside a ``Graph`` the SDK makes that
call itself, so there is no seam to pass it through.

A hook on every model call is the seam that does exist. Twelve is generous on
purpose: the busiest node here is the Preparer at four tool calls plus the
structured-output pass, so twelve means something is wrong rather than busy."""

MAX_NODE_EXECUTIONS = 20
NODE_TIMEOUT_SECONDS = 60.0
GRAPH_TIMEOUT_SECONDS = 300.0
"""A graph with no execution limits only logs a warning and can spin forever.
Note that hitting the cap sets ``status`` to FAILED *silently* -- always check
``result.status is Status.COMPLETED`` explicitly rather than assuming success."""

RETRY_MAX_ATTEMPTS = 3
RETRY_INITIAL_DELAY = 2
RETRY_MAX_DELAY = 8
"""Strands retries 6 times by default on a 4s->240s ladder, which is up to ~124
seconds of silent waiting. On a live demo, fail fast instead."""


# --- Shared run state ------------------------------------------------------

NAMESPACE = "second"
"""Everything Second puts in ``invocation_state`` lives under this key.

Required, not hygiene. The SDK writes reserved names -- ``agent``, ``model``,
``messages``, ``system_prompt``, ``tool_config``, ``request_state`` and
``event_loop_cycle_*`` -- directly onto the dict the caller passed in.
``scripts/phase0_proof.py`` claim 4b asserts this against the live SDK."""


# --- Routing ---------------------------------------------------------------

CONFIDENCE_FLOOR = 0.7
"""Below this, Second asks rather than acts, whatever else the diagnosis says."""


@dataclass(frozen=True)
class GoogleScopes:
    """Two credentials, deliberately.

    The runtime agent can read the calendar and inbox and compose drafts. It
    cannot insert mail, so it cannot manufacture the evidence it later cites.
    The seeder can, and is never deployed.
    """

    runtime: tuple[str, ...] = (
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    )
    seeder: tuple[str, ...] = (
        "https://www.googleapis.com/auth/gmail.insert",
        "https://www.googleapis.com/auth/calendar.events",
    )


GOOGLE_SCOPES = GoogleScopes()
