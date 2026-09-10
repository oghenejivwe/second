# Second

Tell it what you want. It works out how to fit it into your life, and keeps it moving.

Second is a personal execution agent for people running several long-term goals at once. You speak
your goals aloud. Second works out concrete routes to achieve them, fits them into your real
calendar, runs daily in the background, adapts when reality intervenes, learns you over time, and
asks for feedback that changes the plan.

It does everything it can do without you, then hands you the smallest possible piece. Not "write
your leave email" but a drafted leave email awaiting one click. Not "book flights" but three
options priced and compared. Your job shrinks to a decision.

Built on the [Strands Agents SDK](https://github.com/strands-agents/sdk-python).

> Status: Phase 0. Foundations proved, product not yet built.

## Phase 0 findings

`scripts/phase0_proof.py` runs the real `Graph` — real nodes, real edges, real conditional routing,
real `@tool` dispatch — against a scripted model provider, with no AWS credentials. It proves the
five SDK behaviours the rest of the build stands on:

| # | Claim | Result |
|---|---|---|
| 1 | A node with `structured_output_model` can call its own tools *and* return a typed model in one invocation | holds |
| 2 | A node's typed result reaches dependent nodes as JSON in their prompt | holds |
| 3 | A conditional edge can route on a typed field | holds |
| 4 | `invocation_state` is one mutable dict shared by every node and tool for a run | holds |
| 5 | One hook provider instance can capture every node span and every tool write | holds, with a caveat |

Two of these correct the build spec:

**sdk-python issue #1118 does not apply to 1.55.1.** `AgentResult.__str__`
(`agent_result.py:73-78`) returns `structured_output.model_dump_json()` when structured output is
present, and `Graph._build_node_input` (`graph.py:1236-1242`) stringifies each dependency's
`AgentResult` into the next node's prompt. Typed results propagate. Writing results into shared
state is still worth doing — it is how the Living Graph persists — but it is a design choice now,
not a workaround.

**Graph-level hooks do not see tool calls.** `Graph.hooks` is a separate `HookRegistry`
(`graph.py:553`) that only fires the multi-agent events: node start/stop and invocation start/stop.
Tool events fire on each agent's own registry. `set_hook_providers([audit])` alone logs nothing.
One `AuditLog` instance passed to both `GraphBuilder.set_hook_providers` and every
`Agent(hooks=[...])` gives a single ordered log of node spans and tool writes.

A third finding shapes the agent design: structured output is implemented as a tool. The event loop
registers the output model's schema as one more tool alongside the agent's own
(`event_loop.py:574-575`), and forces it only if the model tries to end its turn without emitting
one (`event_loop.py:369-377`). This is why claim 1 holds, and it means the Diagnostician can read
the graph, search the inbox, and emit a typed `Diagnosis` in a single pass.

## Running the proof

```bash
uv sync
.venv/Scripts/python.exe scripts/phase0_proof.py
```

## Licence

MIT. See [LICENSE](LICENSE).
