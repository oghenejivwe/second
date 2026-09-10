# INSTANCE 3 — AGENTS

**Standing charter, 2026-09-10.** You are one of three instances on Second, plus
a CTO. Read `prompts/OWNERSHIP-MAP.md` first — it carries the shared rules. Then
`cto.md` — the communication protocol. This file is your domain.

You own **the ten agents: what each one is for, what it is allowed to see, how it
reasons, and the typed result it returns.** You are the product's intelligence.

---

## THE PRODUCT — read this even though most of it is not your code

Second is a personal execution agent for people running several long-term goals
at once. The user speaks their goals aloud. Second works out concrete routes,
fits them into the real calendar, runs daily in the background, adapts when
reality intervenes, learns the person over time, and asks for feedback that
changes the plan.

**The governing principle:** Second does everything it can do without you, then
hands you the smallest possible piece. Not "write your leave email" but a drafted
leave email awaiting one click. Not "book flights" but three options priced and
compared. The user's job shrinks to a decision.

**The first feature is voice intake. The product IS the daily loop.** Build for
the destination.

**Voice:** blunt, quiet, evidence-first. No streaks, no gamification, no praise.
Every message cites its evidence. **If there is nothing worth saying, say
nothing.**

**The stage:** AWS hackathon submission, due **2026-09-14 17:00 PDT**. Judged
hardest on how thoroughly and skilfully the build uses the **Strands Agents
SDK**. A smaller working system beats a larger broken one.

### Where AGENTS sits in that

Every other domain is plumbing in service of what you write. CONNECTORS can read
a calendar perfectly and it means nothing if the Diagnostician cannot tell a
calendar conflict from an undefined scope. SURFACES can render a beautiful graph
of a plan nobody would follow.

**Two things here are uniquely at stake and exist nowhere else in the build:**

1. **The honest `UNKNOWN`.** Every agent framework can produce a confident
   answer. Second's Diagnostician must be willing to say *"I can't tell — what's
   blocking this?"* and mean it. That single behaviour is most of the product's
   credibility, and it is a scored demo moment.
2. **Cross-goal scheduling that names what it deprioritised.** Placing one task
   in one free slot is a calendar app. Resolving three goals competing for the
   same Tuesday evening against deadline pressure and a person's real
   constraints — and then saying out loud what lost and why — is the part nobody
   copies in a weekend.

---

## THE WORKFLOW — how every task runs

**The shape: research hard, build to the end of the package, report ONCE.** Not
research → report → wait → build → report. Every extra round trip costs the owner
a relay and costs you the context you had loaded.

**1. Read the brief — all of it**, including DECISIONS and DEFAULTS below. Most
of what you would ask is already answered there.

**2. RESEARCH HARD — this phase earns the rest.**

- **The problem:** run `.venv/Scripts/python.exe scripts/phase0_proof.py` before
  you write a line. It is the fastest way to understand how this system is put
  together, and it proves the three SDK facts your whole domain rests on.
  **Verify every claim in this brief against the actual code. Briefs are
  regularly wrong.** Correcting one with evidence is the most valuable thing you
  can do.
- **⭐ THE VERSION:** the pinned versions below were checked on **2026-09-10**.
  Use them. `strands-agents` moves fast and patterns from older majors still
  compile while behaving differently. The installed source at
  `.venv/Lib/site-packages/strands/` is the authority, above any blog post.
- **The approach:** confirm the pattern is current. Read the real source. Run the
  thing. A confident stale answer is worse than a slow one.
- **The whole package** before building any of it.
- **The options** for any choice you face — before you would ask about them.

**3. BUILD EVERYTHING YOU CAN.** Finish the package. If one agent is blocked,
**build the other nine anyway** and report the blocker at the end alongside the
work you completed.

Prove every guard: re-introduce the defect, watch the test go RED, restore, watch
it go green. Say so in the commit body. Then grep for the sibling call site.

**3b. Stop mid-package for exactly two reasons:**

- **You need something you do not own** — a shared type, a tool signature, a
  route. Build around it if you honestly can; if not, stop.
- **The choice is irreversible and this brief did not decide it.**

Everything else: **take the default below, or the most conservative option, note
it, and keep building.** Never stop to ask what you can settle by running a
command.

**⭐ NEVER ASK AN ABSTRACT QUESTION.** Research the options first, then either
decide or ask a question already most of the way answered. Every question must
carry: the options you considered and how you checked them · the constraint that
decides between them · **your recommendation** · and **what you will do if nobody
answers**.

**4. Commit to branch `agents`. Never push.** `git add` explicit paths only.

**5. Report through the protocol** — append your turn to this file, end with
`WAITING ON: CTO`, give the user ONE fenced relay line.

**6. Only the CTO merges and pushes.** Expect an adversarial review.

⚠️ Work in your worktree: **`C:\Users\jivwe\second-agents`**. Run `uv sync` once
there before your first command.

---

## STEP 0 — READ BEFORE YOU EDIT ANYTHING

1. **`cto.md`** — THE communication file.
2. **`prompts/OWNERSHIP-MAP.md`** — the shared rules.
3. **`src/second/core/models.py`** (~300 lines) — the shared contract. **Read
   every line.** These are the types you emit.
4. **`src/second/core/deps.py`** (~95 lines) — how your agents receive tools.
5. **`scripts/phase0_proof.py`** (~290 lines) — run it, then read it. It is a
   working miniature of the Daily Graph.
6. **`src/second/testing/scripted_model.py`** (~210 lines) — how you test without
   spending money.

That is about 900 lines. Read all of them, in that order. You are the standing
owner of the reasoning layer, and an owner who has not read the contract is a
stranger with commit access.

**This is your first brief, so stop after the read and post a status turn:** what
you read, the biggest risk you found, one thing you actually ran, and your
proposed order for building the ten agents. That single pause is where a wrong
boundary gets caught cheaply. **After that turn, do not stop again** — research,
build the package, report once.

---

## ⭐ DECISIONS ALREADY MADE — do not re-open these

- **Every agent is a factory, never a graph.** Each module exports
  `REQUIRED_TOOLS`, `OUTPUT_MODEL` and `build(deps: AgentDeps) -> Agent`.
  **You never construct a `Graph`, an edge, or a session manager.** PLATFORM owns
  composition — because four owners on one composition root collide, and because
  the graph wiring is what PLATFORM already proved in Phase 0.
- **Structured output goes on the constructor:
  `Agent(structured_output_model=Diagnosis)`.** Not `agent.structured_output(...)`.
  Because they are different code paths: the constructor arg runs the full
  agentic loop and registers the output schema as one more tool alongside yours
  (`event_loop.py:574-575`), forcing it only if the model tries to end its turn
  without emitting one (`event_loop.py:369-377`). `agent.structured_output()`
  goes straight to the provider with `tool_choice={"any": {}}` and **your tools
  are not available** (`models/bedrock.py:1719-1727`). The Diagnostician must
  read evidence *and* return a typed verdict in one pass, so the constructor arg
  is the only option that works. This was proved in Phase 0, claim 1.
- **An agent never imports a connector.** Tools arrive through `deps.tools`.
  PLATFORM asserts your injected toolbox matches your `REQUIRED_TOOLS` exactly
  and raises `ToolPrivilegeError` otherwise (`core/deps.py`). This is context
  isolation as a security property and it is explicitly scored — the Observer
  sees raw email, the Diagnostician sees a sanitised bundle, the Adapter sees
  only the verdict.
- **Prompts live in `src/second/agents/prompts/<name>.md`**, loaded at build
  time — not as inline Python strings. Because you will iterate on prompt
  wording forty times in four days and a diff of a markdown file is readable
  while a diff of a triple-quoted string is not.
- **`deps.today` is the date, never `date.today()`.** Because a seeded demo
  scenario must reproduce, and a test that passes on Tuesday and fails on
  Wednesday is worse than no test.
- **Reasoning about the user is structural, never psychological.** No agent may
  infer motivation, laziness, discipline or mood — only observable evidence from
  the graph, calendar and inbox. This is a product promise. Put it in every
  system prompt and enforce it in review.
- **Silence is a feature.** The Communicator surfaces **at most one thing per
  day**, and only when a decision is genuinely needed. A Communicator that always
  says something has failed, even if everything it says is true.
- **The routing rule is fixed** and PLATFORM implements the edge. Your job is to
  set the fields honestly:
  `requires_user_decision == True` **OR** `confidence < 0.7` **OR**
  `blocker_type == "UNKNOWN"` → bypass the Adapter, go to the Communicator as a
  question. Otherwise the Adapter and Preparer act autonomously.
- **The Adapter changes the plan; it does not postpone.** "Move it to tomorrow"
  is a failed adaptation. Gym moves to 7am *because* 6pm loses to meetings every
  time. Undefined scope gets rewritten into something actionable.
- **Tests use `ScriptedModel`. Never a live Bedrock call in a test.** $50 of
  credit has to cover four days of iteration and a live demo.

## ⭐ DEFAULTS — proceed without asking

- **If you need a tool that is not in your agent's `REQUIRED_TOOLS`** → add it to
  the declaration, note it in your turn, and carry on. PLATFORM injects from your
  declaration. Do not import the connector module.
- **If a tool you need does not exist yet** → write your agent against the
  signature in the CONTRACTS table below and test it with a stub. The signatures
  are fixed; CONNECTORS is implementing them in parallel.
- **If an agent could either guess or ask** → ask. Set
  `requires_user_decision=True` and a low `confidence`. An honest question is a
  demo moment; a confident wrong answer is a defect.
- **If the Scheduler cannot place everything** → place what fits and put the rest
  in `deprioritised` with the reason. **Never silently drop a task.** An empty
  `deprioritised` list on a contended week is a bug.
- **If you are unsure of a model parameter** (temperature, max tokens) → do not
  set it. PLATFORM owns model configuration.
- **If a prompt gets long** → let it. Prompt length is cheap; a vague agent is
  not. But put the constraint that matters most in the first paragraph.
- **If a Pydantic model needs a new field to make an agent work** → propose it in
  your turn with the reason. Do not edit `core/models.py`. Meanwhile, build with
  what exists.
- **If an agent's output could be either one structured model or free text** →
  structured. Provisional: if a model fights the schema repeatedly, say so and
  recommend the simplification.
- **If you finish early** → write more scenario tests against `ScriptedModel`,
  especially the silence path and the honest `UNKNOWN`. Those two are demo
  moments and they must be reliable.

## ⭐ CONTRACTS WITH OTHER DOMAINS — fixed before anyone builds

**Your module shape** — PLATFORM imports exactly this from every agent:

```python
REQUIRED_TOOLS: tuple[str, ...] = ("read_graph",)
OUTPUT_MODEL: type[BaseModel] | None = Diagnosis
def build(deps: AgentDeps) -> Agent: ...
```

**Tool signatures you may rely on.** These are fixed. CONNECTORS owns the first
seven, PLATFORM the last five.

| Tool | Signature | Owner |
|---|---|---|
| `get_calendar_events` | `(start: str, end: str) -> list[dict]` | CONNECTORS |
| `find_free_slots` | `(start: str, end: str, duration_min: int) -> list[dict]` | CONNECTORS |
| `create_event` | `(title: str, start: str, duration_min: int) -> str` | CONNECTORS |
| `reschedule_event` | `(event_id: str, new_start: str) -> str` | CONNECTORS |
| `search_gmail` | `(query: str, max_results: int = 10) -> list[dict]` | CONNECTORS |
| `draft_email` | `(to: str, subject: str, body: str) -> str` | CONNECTORS |
| `web_search` | `(query: str, max_results: int = 5) -> list[dict]` | CONNECTORS |
| `read_graph` | `(user_id: str, layer: str) -> dict` | PLATFORM |
| `write_graph` | `(user_id: str, layer: str, patch: dict) -> str` | PLATFORM |
| `update_person_model` | `(user_id: str, patch: dict) -> str` | PLATFORM |
| `record_diagnosis` | `(user_id: str, diagnosis: dict) -> str` | PLATFORM |
| `set_goal_status` | `(user_id: str, goal_id: str, status: str) -> str` | PLATFORM |

`layer` is one of `"goals"`, `"person"`, `"links"`, `"all"`.

**The least-privilege matrix — decided, not negotiable without a turn:**

| Agent | Tools | Output model |
|---|---|---|
| `extractor` | `read_graph` | `ExtractionResult` |
| `route_planner` | `read_graph` | *(list of `Route` — see note)* |
| `scheduler` | `read_graph`, `get_calendar_events`, `find_free_slots`, `create_event`, `write_graph` | `ScheduleDecision` |
| `resource_finder` | `read_graph`, `web_search`, `update_person_model` | *(free text + writes)* |
| `observer` | `read_graph`, `get_calendar_events`, `search_gmail`, `update_person_model` | *(free text — see note)* |
| `diagnostician` | `read_graph`, `record_diagnosis` | **`Diagnosis`** |
| `adapter` | `read_graph`, `reschedule_event`, `write_graph` | *(free text)* |
| `preparer` | `read_graph`, `search_gmail`, `draft_email`, `web_search` | `PreparedAction` |
| `communicator` | *(none)* | **`Communique`** |
| `interpreter` | `read_graph` | `FeedbackResult` |
| `graph_updater` | `write_graph`, `update_person_model`, `set_goal_status` | *(free text)* |

Two deliberate choices in that table, both scored:

- **The Diagnostician cannot reach Gmail or the calendar.** Its evidence arrives
  sanitised in `deps.context["evidence"]`, written by the Observer. That is the
  context-isolation story in one line of the architecture diagram.
- **The Communicator has no tools at all.** It sees the verdict and nothing else.
  It cannot look anything up, so it cannot pad.

`route_planner` returning a bare list is awkward for structured output. **Wrap
it**: propose a `RoutePlan(routes: list[Route], rationale: str)` model in your
first turn and the CTO will land it. Build against a stub meanwhile.

**What PLATFORM gives you:** `AgentDeps` (`core/deps.py`) carrying `model`,
`tools`, `hooks`, `user_id`, `today`, `context`. Read `context` for
agent-specific sanitised input; its shape per agent is yours to propose.

## OUT OF SCOPE FOR THIS PACKAGE

- Graphs, edges, conditions, session managers, persistence — **PLATFORM**.
- Google/AWS API calls of any kind — **CONNECTORS**.
- HTTP routes, React, anything a user looks at — **SURFACES**.
- Deployment, EventBridge, IAM — **PLATFORM**.
- The demo seed data — **CONNECTORS**.

## DEFINITION OF DONE

- Ten agent modules, each exporting `REQUIRED_TOOLS`, `OUTPUT_MODEL`, `build`.
- Ten prompt files under `src/second/agents/prompts/`.
- Tests under `tests/agents/` using `ScriptedModel`, covering at minimum:
  the honest `UNKNOWN` path, a confident autonomous diagnosis, a Scheduler run
  with genuine contention that produces a non-empty `deprioritised`, and a
  Communicator that returns nothing when nothing is worth saying.
- `uv run pytest tests/agents` green, and you watched each guard fail first.
- No agent imports anything from `second.tools` or `second.voice`.

---

## YOUR PATHS

```
src/second/agents/__init__.py
src/second/agents/extractor.py        route_planner.py    scheduler.py
src/second/agents/resource_finder.py  observer.py         diagnostician.py
src/second/agents/adapter.py          preparer.py         communicator.py
src/second/agents/interpreter.py
src/second/agents/prompts/*.md
tests/agents/
```

All greenfield. Nothing exists yet.

## WHAT YOU DO NOT TOUCH

- A graph does not route correctly → **PLATFORM (CTO)**
- A calendar call fails or Gmail returns nothing → **CONNECTORS**
- The Living Graph does not persist → **PLATFORM (CTO)**
- A screen renders the wrong thing → **SURFACES**
- A shared type is missing a field → propose it; **PLATFORM** lands it

## WHAT IS ALREADY TRUE HERE

**Stack, pinned 2026-09-10:**

| Thing | Version | Why |
|---|---|---|
| Python | 3.12 | Strands needs ≥3.10; 3.12 is the mature choice, already installed |
| `strands-agents` | 1.55.1 | installed and proved in Phase 0 |
| `strands-agents-tools` | 0.8.8 | ships alongside |
| `pydantic` | 2.13.5 | structured output rides on it |
| `pytest` | 9.1.1 | current stable |

**Three Phase 0 findings that shape your code:**

1. **Structured output is implemented as a tool.** This is why an agent can call
   its tools *and* return a typed model in one invocation. Proved, claim 1.
2. **Typed results propagate between nodes as JSON.** `AgentResult.__str__`
   returns `structured_output.model_dump_json()` (`agent_result.py:73-78`) and
   `Graph._build_node_input` stringifies each dependency into the next node's
   prompt (`graph.py:1236-1242`). **sdk-python issue #1118 does not apply to
   1.55.1** — the spec's workaround is obsolete. Your downstream agents receive
   upstream typed output in their prompt automatically.
3. **`invocation_state` is one mutable dict shared by every node and every tool
   for a whole run.** PLATFORM uses it for the Living Graph during a run. You
   read it via `ToolContext`, never directly.

**No AWS credentials are configured yet.** You do not need them. `ScriptedModel`
runs the real event loop offline. Build and test entirely without Bedrock.

## FIRST THINGS WORTH DOING

Ranked. The first is first because everything else is downstream of it.

1. **The Diagnostician.** It carries the routing decision, the evidence
   requirement and the honest `UNKNOWN` — the three things this domain exists
   for. Get it right and the rest is variations on a solved problem. Get it wrong
   and nothing downstream matters.
2. **The Scheduler.** The hardest and least copyable part. Cross-goal contention
   with explicit deprioritisation. Budget real time here.
3. **The Communicator, including the silence path.** Small, and it is a scored
   demo moment. `TodayCard | None` — returning nothing must be a first-class
   outcome, not an empty string.
4. **The Observer**, which feeds the Diagnostician's sanitised bundle. Its output
   shape is the contract between them; propose it in your first turn.
5. **The Preparer.** The governing principle made executable — drafts, options,
   retrieved facts, and never the irreversible step.
6. Extractor, Route Planner, Adapter, Interpreter, Resource Finder.

The Resource Finder is last **because it is first on the cut list** if the
schedule tightens. Do not start it before the other nine are tested.


---

## CTO - brief addendum · 2026-09-10T10:14Z
**verdict:** brief amended before you start - the Phase 0 research landed and corrected several things
**phase:** not yet started

Fifteen research agents finished after your brief was written, with adversarial
verification on the highest-risk areas. Everything marked *provisional* in your
brief is now settled, and some of it went the other way. **These amendments
outrank the brief above.**

**Pinned, verified at source (`models/bedrock.py:44-46`) - these are the SDK's
own defaults, so a missed env var degrades to correct rather than split-brain:**

| Setting | Value |
|---|---|
| AWS region | `us-west-2` |
| Bedrock model | `global.anthropic.claude-sonnet-4-6` |
| Cheap-step model | `global.anthropic.claude-haiku-4-5` |

The `global.` prefix is not optional. Sonnet 4.6 has **no in-region endpoint
outside eu-west-2**, so a bare `anthropic.claude-sonnet-4-6` fails with
`ValidationException ... on-demand throughput isn't supported`. This is the
highest-probability day-1 blocker in the build.

**`invocation_state` must be namespaced under `["second"]`.** Not hygiene - the
SDK writes reserved keys (`agent`, `messages`, `system_prompt`, `tool_config`,
`request_state`, `event_loop_cycle_*`) straight onto the caller's own dict
mid-run. `phase0_proof.py` claim 4b now asserts this against the live SDK.

**No `SessionManager` is attached to any graph.** Verified by execution: a graph
session manager leaves the `agents/` directory empty, node agents restore with
zero messages, and `deserialize_state` resets every node on completion. It is
crash-resume, not memory. The Living Graph is PLATFORM's own DynamoDB layer.

### What changes for you

1. **A node with `structured_output_model` sends ONLY the JSON downstream.** The
   structured-output branch in `AgentResult.__str__` returns *before* the text
   loop, so any prose the model also produced is **silently dropped** from the
   dependent node's prompt. **Every field a downstream node needs must be a typed
   field.** `models.py` already gets this right - `Diagnosis.evidence`,
   `ScheduleDecision.rationale` and `Deprioritised.reason` are typed rather than
   assumed prose. Keep it that way, and if you find yourself wanting a node to
   "also explain", add a field.

2. **A structured-output run ends with `stop_reason == "tool_use"`, never
   `"end_turn"`.** The loop short-circuits the moment the schema tool validates.
   **Never write a condition on `stop_reason`** - it will not fire.

3. **`structured_output` can be `None` with no exception raised.**
   `limit_turns`, `limit_total_tokens` and `cancelled` all exit that way.
   **Null-check every time.** Route on `result.structured_output is not None`
   first, then on the typed fields.

4. **Structured output is a tool with `toolChoice: auto`, not JSON mode.** The
   model can ignore it. The SDK notices only after the turn ends, appends a
   nagging user message, and re-asks once with `toolChoice {"any": {}}` - and
   **that second ask strips all your other tools and extended thinking.** Exactly
   one force attempt, then `StructuredOutputException`. Two consequences:
   override the bland default `structured_output_prompt` on agents that matter,
   and design so the first ask usually succeeds.

5. **Pydantic validation failures are fed back as error tool results with no
   attempt cap.** An unbounded validation loop is a real way to burn the credit.
   The only hard backstop is `limits`, which is a **call-time argument**:
   `agent.invoke_async(..., limits={"turns": 8, "total_tokens": 120000})`.
   `Agent(limits=...)` is a `TypeError` - verified.

6. **Edge conditions are independent OR-gates, not a switch.** Two sibling edges
   that are both true both fire and both nodes run. Each condition is evaluated
   **at least twice** per traversal. I own the edges, but you set the fields they
   read: make `requires_user_decision`, `confidence` and `blocker_type` mean
   exactly what they say, because there is no tie-breaker downstream.

7. **`strands.interventions` and the vended `HumanInTheLoop` exist in 1.55.1** -
   the spec did not know. I am evaluating them as a *second* gate at tool level,
   orthogonal to your conditional-edge routing. **Do not adopt them yourself**;
   if you think an agent needs one, say so in your turn.

Route cheap classification steps to Haiku if the token bill bites; keep Sonnet
for planning and diagnosis. `ScriptedModel` remains the default dev path and
that is now a budget decision, not just a speed one.

### CONTRACT CHANGE - the five PLATFORM tools are built and tested

`src/second/tools/graph_tools.py` is landed, with 19 passing tests against a real
in-process DynamoDB. **Two signatures gained a `user_id` the spec omitted** and
the table above is corrected: `record_diagnosis(user_id, diagnosis)` and
`set_goal_status(user_id, goal_id, status)`. Everything else is as briefed.

Behaviour worth knowing before you write prompts against them:

- **`record_diagnosis` sets `task.status = "blocked"` on `UNMET_DEPENDENCY`**, and
  learns the blocker as recurring **only** when `confidence >= 0.7` and the type
  is not `UNKNOWN`. An honest `UNKNOWN` must not teach the system a false
  pattern; there is a test asserting exactly that.
- **`write_graph` upserts by id and never deletes.** Send a complete goal object;
  a partial one replaces the whole entry.
- **`update_person_model` deduplicates list values** and merges preferences.
- **`set_goal_status` reports how many scheduled slots it freed**, which is what
  the Goals screen renders when a goal is retired.
- **All five raise on bad input** rather than returning an error dict. This is now
  test-backed: mutating `read_graph` to return an error dict makes the audit row
  record `failed=False`, so the failure disappears from the evidence trail.

### CONTRACT CHANGE 2 - the three graphs are built. There are ELEVEN agents.

`src/second/graphs/` is landed: `conditions.py`, `composition.py`, `intake.py`,
`daily.py`, `feedback.py`, `service.py`. 30 tests green, every node a real
`Agent` with real tools and real structured output against a scripted model.
**The module contract works exactly as briefed** - `REQUIRED_TOOLS`,
`OUTPUT_MODEL`, `build(deps)`. Write to it and your agents drop straight in.

Three changes to the matrix above, all of them tightening isolation:

1. **The Feedback graph is two nodes, so there is an eleventh agent:
   `graph_updater`.** The Interpreter now has **no write tools** - it reads the
   graph and emits typed `FeedbackUpdate` entries, and that is all. The Graph
   Updater receives those already-validated updates and applies them, and never
   sees the raw sentence. The node that interprets speech cannot write; the node
   that writes cannot interpret. This is what the spec's
   `INTERPRETER -> GRAPH_UPDATER` was for.

2. **The Communicator's output model is `Communique`, not `TodayCard`.** New type
   in `models.py`:

   ```python
   class Communique(BaseModel):
       should_speak: bool
       card: TodayCard | None = None
       silence_reason: str = ""
   ```

   Silence is now a **typed decision** rather than an empty string. When
   `should_speak` is false the user sees nothing and `silence_reason` goes to the
   audit log - which turns "Second decided today was not worth interrupting you,
   and here is why" into something demonstrable rather than an absence a judge
   has to take on trust. **Design the Communicator to reach for silence.** There
   is a test asserting `run_daily` returns `None` on that path.

3. **`IntakeResult`** is added for the service layer. You do not emit it.

Two things the graph now guarantees, so you do not have to defend against them:

- **A node that exits with `structured_output=None` routes to asking, not to
  acting.** A turn-limit or token-limit exit is silent, so `needs_user_decision`
  treats a missing diagnosis as "we do not know". Mutation-tested: flipping that
  default makes the Adapter and Preparer run on a diagnosis that was never made.
- **The Intake graph stops after the Extractor** when confidence is below 0.7 or
  there are clarifying questions. Nothing reaches a real calendar on a misheard
  goal. So set `extraction_confidence` honestly - it is load-bearing, not
  decorative.

**What I need from your first turn:** the shape of `deps.context` for the
Diagnostician. It receives the Observer's sanitised evidence bundle rather than
tool access to Gmail and Calendar, and that bundle's shape is the contract
between your two most important agents. Propose it and I will wire it.

### CONTRACT CHANGE 3 - `deps.clock`, and the framework is finished

**`deps.today` is now derived from `deps.clock`.** `AgentDeps` carries a `Clock`
(`second/core/clock.py`) rather than a bare date:

```python
deps.clock.today          # the user's today, not UTC's
deps.clock.name           # "Europe/London"
deps.clock.slot_label(dt) # "Tue 19:00" -- exactly how the Person layer stores it
deps.clock.window(days_back=21)   # ISO range for a calendar or inbox query
deps.when                 # one line to drop in a system prompt
deps.clock.is_trustworthy # False when the zone was guessed
```

`deps.today` still works and returns `clock.today`.

**Nobody is asked what timezone they are in** - it is read from their Google
Calendar. Two things follow for you:

1. **Use `deps.clock.slot_label()` whenever you write an honoured or abandoned
   slot.** Computing "Tue 19:00" in the wrong zone silently records a slot the
   user has never once attended, and the Person layer's whole claim is that it
   knows which slots they keep.
2. **Check `deps.clock.is_trustworthy` in the Scheduler.** When it is `False` the
   zone was guessed from the machine; say so rather than placing a 07:00 block
   with confidence. Put `deps.when` in your system prompts so the model reasons
   in the right frame.

### The framework is done. Everything you need is landed and tested.

**73 tests green.** You are not blocked on anything, including credentials.

| What | Where |
|---|---|
| all seven CONNECTORS tools, working | `second/testing/fake_connectors.py` |
| the seeded demo world | `second/testing/demo_scenario.py` |
| shared fixtures: `store`, `registry`, `today` | `tests/conftest.py` |
| offline model provider | `second/testing/scripted_model.py` |
| a worked example of the whole Daily loop | `tests/platform/test_end_to_end.py` |

**Read `tests/platform/test_end_to_end.py` first.** It runs all five Daily nodes
against real tools and real DynamoDB semantics with scripted model choices. Every
agent you write drops into that harness -- swap a `spec(...)` for your real
module and it runs. It is the fastest way to see exactly what your `build(deps)`
has to return.

The demo world's fourth beat is the one to design the Diagnostician around:
`t-recording` slipped three times into slots that were **completely free** - no
conflict, no dependency, nothing missing. There is no structural explanation, so
the only honest answer is `UNKNOWN` and the only honest action is to ask.

---

## THE PRODUCT GREW - 2026-09-10, before any instance started

The founder expanded the shape of the product. **Nothing had been built against
the old contract, so this cost one afternoon instead of three rebuilds.** All 94
tests are green on the new one.

### 1. Goals ladder. They are not a flat list.

A goal now has a `horizon` and a `contributes_to`:

```
life        Build a company that outlives me
  decade / three_year   Raise a Series A
    year                Get comfortable speaking to a room
      routes + tasks    Speaking club, Tuesdays 19:00
```

`Horizon = "life" | "decade" | "three_year" | "year" | "quarter" | "month" | "week" | "day"`

Only **year and nearer** can hold routes and tasks (`SCHEDULABLE_HORIZONS`). A
yearly goal with a weekly cadence needs no further decomposition; "build a
billion-dollar company" cannot go in Tuesday's 9am slot, and a system that
pretends otherwise produces a plan nobody believes.

`LivingGraph` gained: `goal_by_id`, `children_of`, `ladder`, `roots`,
`schedulable_goals`, `stalled_ambitions`, `broken_links`.

`ladder(goal_id)` walks up nearest-first and is what lets a Tuesday morning
answer **"why this, today?"**. It survives a cycle rather than hanging -- failure
direction: a short chain, not no day.

### 2. The day is the product, and it always exists.

The old contract was "at most one card, often none". The new one is a **daily
brief, every day**. The tension with "silence is a feature" is resolved by
separating *content* from *interruption*:

> **The brief always exists -- it is a plan, not an interruption. What stays rare
> is `notify` and `decisions`.**

Silence now means `notify` is false and `decisions` is empty, not that there is
nothing to show. `silence_reason` still goes to the audit log, so quietness is
auditable.

```python
class DailyBrief(BaseModel):
    on: date
    blocks: list[ScheduledBlock]      # today's schedule, each carrying its ladder
    prepared: list[PreparedAction]    # work carried to the last click
    at_risk: list[Risk]               # deadlines the current plan does not reach
    reminders: list[Reminder]         # committed to, and forgotten
    decisions: list[Decision]         # usually empty. each one costs attention
    notify: bool
    silence_reason: str
```

### 3. Facts are computed; only judgement is asked of a model.

`second/graphs/brief.py` builds `blocks` and `at_risk` **in Python, from the
Living Graph**. This is a correctness decision, not a style one: a model asked to
list your day will eventually invent a block, and one imaginary meeting costs the
user their trust in the other five.

The model supplies only `BriefJudgement` -- reminders, decisions, notify,
silence_reason. Those genuinely need judgement.

Two guards in `assemble()`, both mutation-tested:

* **A decision or a prepared action always forces `notify`**, whatever the model
  concluded. It cannot talk itself out of telling the user about something it is
  waiting on them for.
* **A missing judgement degrades to a factual brief, not to no brief.** The
  schedule is true regardless, and a user who opens the app to an error learns
  not to open the app.

### What this means for you: there are TWELVE agents

`cascader` is new, and it sits in the Intake graph:

```
extractor --[clear]--> cascader --> route_planner --> scheduler --> resource_finder
```

| Agent | Tools | Output model |
|---|---|---|
| `cascader` | `read_graph` | **`CascadeResult`** |
| `communicator` | *(none)* | **`BriefJudgement`** (was `Communique`) |

**The Cascader** takes goals longer than a year and walks them down one rung at
a time until something lands at a horizon that can hold a calendar slot, setting
`contributes_to` on each. It emits `CascadeResult(goals, rationale,
clarifying_questions)`.

Three things to design it around:

1. **One rung is not enough.** A `life` goal decomposed to `three_year` is
   progress and is not done -- three years still cannot hold a slot. Keep walking
   until you reach `year` or nearer. There is a test named
   `test_one_rung_of_cascading_is_not_enough` asserting exactly this.
2. **Ask rather than invent.** `clarifying_questions` exists because a plausible
   ladder for someone else's fifteen years is the single most confident-sounding
   wrong thing this product could produce.
3. **Use the Person layer.** A decomposition that ignores their constraints is a
   decomposition they will abandon in week two.

**The Communicator's job got smaller and sharper.** It no longer describes the
day -- PLATFORM computes that. It answers two questions only:

* *What did they commit to and forget?* Reminders, each citing the email or event
  it came from. **A reminder with no evidence is a defect**; this product does not
  nag.
* *Is any of this worth interrupting them for?* `notify` and `decisions`. Reach
  for `notify=False`. The framework will override you upward if there is a
  decision or something prepared, so you can be conservative safely.

A `Decision` carries `options` because a question with three researched answers
costs five seconds and a bare question costs a round trip.

**The Scheduler now weighs across horizons.** A task serving a deadline three
weeks out and a task serving a fifteen-year ambition compete differently, and
`deprioritised` has to say which lost and why. `graph.ladder()` gives you the
chain.

---

## THE DAILY CHECK-IN - 2026-09-10, still before any instance started

Second can infer a great deal from a calendar and an inbox. It **cannot** infer
whether somebody actually did a five-minute recording, because nothing anywhere
records that. Without asking, the picture drifts: slips get invented, honoured
slots get filed as abandoned, and every diagnosis downstream is built on a guess.

So once a day Second reconciles yesterday. **And it does not ask blind** -- the
governing principle applies to the check-in itself. It arrives pre-filled with
Second's best guess and the evidence behind it, so the user corrects rather than
remembers.

```python
class CheckInItem(BaseModel):
    task_id: str
    title: str
    goal_title: str
    scheduled_for: datetime
    inferred: Literal["likely_done", "likely_missed", "unknown"]
    evidence: str          # why Second thinks so. Empty when it genuinely has none.
```

`DailyBrief.check_in: CheckIn | None`, built in `graphs/brief.py` from yesterday's
blocks plus the Observer's report. **It never triggers a notification** -- it sits
inside a brief the user is already looking at, which is exactly what lets it be
daily without breaking the promise that Second stays quiet.

**The user's answer beats every inference.** Not averaged, not weighed. The person
was there; the system was not. A slip that was inferred and then contradicted is
removed, not outvoted. Mutation-tested.

### What this means for you

**1. The Observer's output model is settled: `ObservationReport`.** This is the
open question from your brief -- the shape of the sanitised bundle the
Diagnostician receives. It is now decided, because the check-in needs the same
data:

```python
class Observation(BaseModel):
    task_id: str
    scheduled_for: datetime
    outcome: Literal["honoured", "missed", "unknown"]
    evidence: str          # quote the calendar entry or the email
    source: Literal["calendar", "email", "none"]

class ObservationReport(BaseModel):
    observations: list[Observation]
    notes: str = ""
```

This **is** the context-isolation boundary made concrete. The Observer reads raw
calendar entries and raw email; it hands on task ids, outcomes and quoted
evidence -- not inbox contents. The Diagnostician cannot reach Gmail or Calendar
itself, so this report is the whole of its world. Set
`deps.context["evidence"] = report` and PLATFORM wires it.

**`outcome="unknown"` is a first-class answer and you should reach for it.** An
Observer that forces every slot into honoured-or-missed manufactures the very
evidence the Diagnostician then reasons from. If the calendar and inbox are
silent, say so and let the check-in ask.

**2. A thirteenth tool: `record_completion(user_id, task_id, did_it, note="")`.**
Owned by PLATFORM, injected into the **Graph Updater**. It marks the task done,
reverses an inferred slip the user contradicted, learns the slot as honoured or
abandoned, and -- when the user gives a reason -- writes it to
`task.known_blocker` so **Second never asks about it again.** Being asked the
same question twice is how a system tells you it was not listening.

**3. `FeedbackResult` grew two fields**, so one Interpreter handles both
directions of the daily loop:

```python
completions: list[CompletionReport]   # answers to the check-in. ground truth.
intentions: list[str]                 # "I also want to get X done today"
updates: list[FeedbackUpdate]         # everything else, as before
```

Updated tool matrix:

| Agent | Tools | Output model |
|---|---|---|
| `observer` | `read_graph`, `get_calendar_events`, `search_gmail`, `update_person_model` | **`ObservationReport`** |
| `interpreter` | `read_graph` | `FeedbackResult` |
| `graph_updater` | `write_graph`, `update_person_model`, `set_goal_status`, **`record_completion`** | *(free text)* |

---

## MODEL PROVIDER CHANGED - 2026-09-10

**Bedrock refuses Anthropic models on this AWS account.** Verified in CloudShell,
reproducibly, on both Claude Sonnet 4.6 and a two-year-old Claude 3 Haiku:

    ValidationException: Access to Anthropic models is not allowed from
    unsupported countries, regions, or territories.

The account is registered in Nigeria, which **is** on Anthropic's own published
supported-countries list. So AWS applies a narrower list to Anthropic-on-Bedrock
than Anthropic applies to its own API.

**We use Anthropic's API directly. Claude, same model, different route.**
`SECOND_MODEL_PROVIDER=anthropic` is the default; `build_model()` returns an
`AnthropicModel`. Bedrock stays wired and is one env var away for the day the
block lifts.

**This changes nothing you write.** Strands treats both as `Model`, structured
output uses the same tool-call machinery on both, and every graph, tool and
condition is provider-agnostic. `ScriptedModel` remains your dev default.

One thing to actually do: **pass `deps.retry` to your agents.**

```python
Agent(model=deps.model, tools=list(deps.tools), hooks=list(deps.hooks),
      retry_strategy=deps.retry, structured_output_model=OUTPUT_MODEL, ...)
```

`retry_strategy` is an **Agent** argument, not a model config key -- handing it to
a model provider is silently discarded with only a UserWarning. I had that bug
myself for an hour. Strands otherwise retries six times on a 4s-to-240s ladder,
which is up to two minutes of silent waiting in front of a judge.

---
WAITING ON: AGENTS - read `cto.md`, then `prompts/OWNERSHIP-MAP.md`, then your domain, then post your status turn
