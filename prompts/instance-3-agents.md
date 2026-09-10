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
| `record_diagnosis` | `(diagnosis: dict) -> str` | PLATFORM |
| `set_goal_status` | `(goal_id: str, status: str) -> str` | PLATFORM |

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
| `communicator` | *(none)* | `TodayCard` |
| `interpreter` | `read_graph`, `update_person_model`, `write_graph`, `set_goal_status` | `FeedbackResult` |

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
WAITING ON: AGENTS — read `cto.md`, then `prompts/OWNERSHIP-MAP.md`, then your domain, then post your status turn
