# SECOND — THE INSTANCES

**2026-09-10.** This file is the map every instance shares. Each instance also
has its own brief; where they disagree, **this file wins**.

---

## THE PRODUCT — read this even though it is not your code

**You are a specialist in your part. You are not ignorant of the whole.**

Second is a personal execution agent for people running several long-term goals
at once. The user speaks their goals aloud. Second works out concrete routes to
achieve them, fits them into the user's real calendar, runs daily in the
background, adapts when reality intervenes, learns the person over time, and asks
for feedback that changes the plan.

**The governing principle, from which everything follows:** Second does
everything it can do without you, then hands you the smallest possible piece. Not
"write your leave email" but a drafted leave email awaiting one click. Not "book
flights" but three options priced and compared. The user's job shrinks to a
decision.

**The first feature is voice intake. The product IS the daily loop** — observe,
diagnose, adapt, prepare, and stay quiet. Build for the destination. A beautiful
intake flow attached to a system that cannot notice a slipped task is the wrong
product.

**The constraint that outranks everything — enforced in code, never by prompt:**

- **Never send an email.** Drafts only.
- **Never delete a calendar event.**
- **Never move an event the user does not own.**
- **Reasoning about the user is structural, never psychological.** No agent may
  infer motivation, laziness, discipline or mood. Only observable evidence from
  the graph, the calendar and the inbox. This is a product promise, and a
  violation of it is a defect at any severity you find it.

**Voice:** blunt, quiet, evidence-first. No streaks, no gamification, no praise.
Every message cites its evidence. **If there is nothing worth saying, say
nothing** — the silence path is a feature and it must be demonstrable.

**The honest stage and stakes.** This is a hackathon submission for the AWS
"Agents for Humans" track, **due 2026-09-14 17:00 PDT**. One solo owner, three
instances, a CTO. Judged on five criteria: Technological Implementation (how
thoroughly and skilfully it uses the **Strands Agents SDK** — a live demo and a
Bedrock AgentCore deployment strengthen this), Design (a complete product, not a
technical proof of concept), Potential Impact, Creativity & Originality,
Presentation.

**A smaller working system beats a larger broken one.** Do not add features
beyond your brief. When in doubt, finish what you have.

**Strands is the spine, not a wrapper around an LLM call.** Every agent, every
piece of memory, every state transition, every tool call and every routing
decision runs through Strands primitives. If something can be done with a Strands
primitive, do it that way — the SDK's own session management, Graph
orchestration, structured output, tools and hooks are what is being scored.
Nothing important lives outside the framework.

**Each instance is a specialist in its own paths and literate in the whole.** Own
your domain deeply; understand the product entirely; hand off rather than reach
across.

---

## THE INSTANCES

There are three instances plus the CTO. **The CTO owns PLATFORM** — the Strands
spine and the shared contract — rather than only reviewing. That is a deliberate
change from the usual four-instance shape, for two reasons: PLATFORM stewards the
files every other domain imports and the CTO is the only one who merges, so
putting them together removes the highest-collision file set; and the CTO already
built and proved that spine in Phase 0.

| # | Instance | Owns | Risk |
|---|---|---|---|
| — | **PLATFORM** (CTO) | Strands graphs, shared contract, persistence, audit, deploy | contract breakage reaches all three |
| 1 | **SURFACES** | React app + the FastAPI HTTP layer | none — no business logic here |
| 2 | **CONNECTORS** | Google Calendar, Gmail, web search, voice intake, demo seed | **highest** — real writes to a real account |
| 3 | **AGENTS** | all ten agents, their prompts, the Scheduler | the product's actual intelligence |

CONNECTORS is the riskiest domain because it is the only one that can do
something irreversible to a real person's calendar and inbox. AGENTS is the
largest by importance because the spec says to converge effort there.

### PLATFORM (CTO) — no brief file; the CTO works from `cto.md`

```
src/second/core/          models.py — THE SHARED CONTRACT
src/second/persistence/   DynamoDB, the Living Graph repository, Strands sessions
src/second/graphs/        intake.py daily.py feedback.py conditions.py service.py
src/second/hooks/         audit.py
src/second/tools/graph_tools.py
src/second/testing/       scripted_model.py — the offline model provider
src/second/settings.py
scripts/phase0_proof.py
deploy/                   AgentCore, EventBridge, IAM
```

### 1 — SURFACES (`prompts/instance-1-surfaces.md`)

```
web/                      the React app: Record, Living Graph, Today, Goals
src/second/api/           FastAPI app and routes
```

Everything a person sees or types into. **UI and HTTP shape only** — this
instance does not change agent behaviour, scheduling logic or persistence. When a
screen needs data the backend does not return, that is a **handoff to PLATFORM**,
not a fix.

### 2 — CONNECTORS (`prompts/instance-2-connectors.md`)

```
src/second/tools/calendar_tools.py
src/second/tools/gmail_tools.py
src/second/tools/search_tools.py
src/second/voice/                    S3 upload + Amazon Transcribe
scripts/authorize_google.py
scripts/seed_demo.py
```

Every line that touches the outside world. The safety rails live **in this code**,
not in a prompt — an agent that asks to send an email must be refused by the
tool, not talked out of it.

### 3 — AGENTS (`prompts/instance-3-agents.md`)

```
src/second/agents/        ten agent factories + their prompts
```

The Extractor, Route Planner, Scheduler, Resource Finder, Observer,
Diagnostician, Adapter, Preparer, Communicator and Interpreter. **You build
agents; PLATFORM composes them into graphs.** You never construct a `Graph`.

---

## THE DEPLOY CHAIN

```
your branch  ──►  staging  ──►  main   ( = LIVE )
  you commit      CTO merges     CTO merges + pushes + deploys to AgentCore
  never push      + pushes
```

`main` is what deploys, so **main is live**. Nothing reaches it except through
the CTO, and nothing reaches the CTO except through your log.

**Committed does not mean deployed.** AgentCore deployment is a manual step the
CTO runs. Do not assume your merged code is running anywhere.

**There is no git remote yet.** The public repository is a submission
requirement and the CTO will create it. Until then `staging` and `main` are local
branches and "push" is a no-op the CTO owns.

---

## BOUNDARY RULES

1. **`src/second/core/models.py` is stewarded by PLATFORM.** Every domain imports
   it, so a change reaches all four at once. Any instance may **propose** a change
   in its log turn; the CTO lands it and announces it. **Never widen a shared type
   to make one domain's problem go away.**
2. **The composition root is PLATFORM's.** `src/second/graphs/` wires agents into
   graphs and injects their tools. If your work needs wiring, say so in your
   handback — do not wire it yourself.
3. **Tool injection is how least privilege is enforced.** PLATFORM decides which
   tools each agent receives. An agent does not import a connector directly. This
   is a scored security property of the architecture, not a style preference.
4. **Cross-domain work is a HANDOFF, not a reach-across.** Found a real defect
   outside your paths? Write it up in your turn and hand it over. Do not fix it.
5. **Tests live with the code they test**, under `tests/<domain>/`. You own yours.

---

## THE WORKING TREE

Each instance works in **its own git worktree** so three sessions cannot collide
on one directory. The CTO creates them; you will be told your path.

```
C:\Users\jivwe\MySecond              main + staging   (CTO)
C:\Users\jivwe\second-surfaces       branch: surfaces
C:\Users\jivwe\second-connectors     branch: connectors
C:\Users\jivwe\second-agents         branch: agents
```

Run `uv sync` once in your worktree before your first command. Your worktree has
its own `.venv`; the project root's is not shared.

- **`git add` explicit paths. NEVER `git add -A` or `git add .`.**
- **`git status --porcelain` before every commit** — confirm every staged path is
  one you actually edited, and paste it into your turn.
- **Check your branch before you commit.**
- **Never `git checkout --` on an uncommitted tree.**
- When the CTO announces a contract change, `git rebase staging` before
  continuing. Do not merge `staging` into your branch yourself.

---

## STANDING RULES — every instance, every task

1. **Research the approach, not just the problem.** Confirm the tool or pattern is
   the current well-supported one. Training data is stale by construction. The
   pinned versions in your brief were checked on **2026-09-10** — use them.
2. **Mutation-test every guard.** Watch it fail before you believe it. The safety
   rails especially: re-introduce the violation, watch the test go RED, restore.
3. **A green suite is not evidence.** Tests pass while proving nothing when they
   mock the failing primitive, hand-build an object the framework never
   constructs, or assert at a line the input cannot reach.
4. **A fixed threshold is not a control.** If your guard contains a constant, ask
   what it costs to step over it.
5. **Fix the sibling.** After fixing a call site, grep for its twin before you
   commit. This is the single most common repeat defect.
6. **Verify, never infer.** Comments describe intent the code may not implement.
   Grep for the route, not just the symbol.
7. **State the failure direction** on any new branch or network hop in a critical
   path: which way does it fail, and why is that the safe way?
8. **Never write a psychological inference about the user**, in code, in a prompt,
   or in a comment. If you find one, it is a defect — report it even if it is not
   in your domain.
9. **Commit to your branch; never push, never deploy.**
10. **Cost discipline.** Every Bedrock call costs real money against a $50 credit.
    Use `ScriptedModel` for tests. Never put a live model call in a unit test.

---

## HOW TO HAND BACK

Append ONE turn to your own brief file, then stop. Format in `cto.md`. End with
the one-line `WAITING ON:` ball-tracker, then give the user ONE fenced relay
line. **The log file is the message; chat is only the relay.**

---

## CURRENT STATE — 2026-09-10

**Phase 0 is complete and proved.** `scripts/phase0_proof.py` runs the real
Strands `Graph` against a scripted model with no AWS credentials, and proves five
things the build stands on. Run it before you do anything else — it is the
fastest way to understand how this system is put together.

Two spec assumptions were **wrong** and are corrected in code:

- **sdk-python issue #1118 does not apply to strands-agents 1.55.1.**
  `AgentResult.__str__` returns `structured_output.model_dump_json()`
  (`agent_result.py:73-78`) and `Graph._build_node_input` stringifies each
  dependency into the next node's prompt (`graph.py:1236-1242`). Typed results
  propagate between nodes. The spec's "write to shared state and read it back"
  workaround is **not required**. Shared state is still used, for persistence.
- **`GraphBuilder.set_hook_providers` alone logs nothing.** `Graph.hooks` is a
  separate registry (`graph.py:553`) firing only multi-agent events; tool events
  fire on each agent's own registry. The audit log is **one instance registered
  in both places**.

A third finding shapes every agent: **structured output is implemented as a
tool.** The event loop registers the output model's schema alongside the agent's
own tools (`event_loop.py:574-575`) and forces it only if the model tries to end
its turn without emitting one (`event_loop.py:369-377`). So **an agent can call
its tools and return a typed model in a single invocation.**

**What exists:** `src/second/core/models.py` (the contract, complete),
`src/second/testing/scripted_model.py`, `scripts/phase0_proof.py`, `LICENSE`,
`README.md`.

**What does not exist:** everything else.

**Credentials are the critical path and the owner is unblocking them.** No AWS
credentials are configured yet (`aws sts get-caller-identity` fails) and no
Google OAuth client exists. **Every instance must be able to make progress
without them** — that is why `ScriptedModel` exists and why CONNECTORS builds
against recorded fixtures first.

| Who | Ball |
|---|---|
| SURFACES | brief issued — not yet started |
| CONNECTORS | brief issued — not yet started |
| AGENTS | brief issued — not yet started |
| CTO | PLATFORM: persistence, graphs, audit, deploy |
| Owner | AWS + Google credentials |
