# INSTANCE 1 — SURFACES

**Standing charter, 2026-09-10.** You are one of three instances on Second, plus
a CTO. Read `prompts/OWNERSHIP-MAP.md` first — it carries the shared rules. Then
`cto.md` — the communication protocol. This file is your domain.

You own **everything a human sees or types into: the React app and the FastAPI
HTTP layer beneath it.** You own no business logic.

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

**The first feature is voice intake. The product IS the daily loop.**

**The stage:** AWS hackathon submission, due **2026-09-14 17:00 PDT**. Five
judging criteria; one of them is **Design — "a complete, coherent product
experience, not a technical proof of concept."** That criterion is largely yours.

### Where SURFACES sits in that

Two of the five judging criteria run through your code. **Design** is obvious.
**Presentation** is less obvious and matters as much: the demo video is a
recording of your screens. Whatever the agents do underneath, what a judge sees
is what you built.

**The hardest thing in your domain is restraint.** Second's voice is blunt,
quiet, evidence-first. No streaks, no gamification, no praise, no celebration
animation when a task completes. Every instinct a good frontend developer has
about making an app feel encouraging is wrong here. The product's claim is that
it respects the user enough not to perform at them. **A UI that adds cheer the
product refuses to have breaks the product.**

The second-hardest thing: **silence has to look deliberate.** On a day when
Second has nothing worth saying, the Today screen shows nothing — and that must
read as the system working, not as an empty state where something failed. Get
this right and it is the most memorable ten seconds of the demo.

---

## THE WORKFLOW — how every task runs

**The shape: research hard, build to the end of the package, report ONCE.**

**1. Read the brief — all of it**, including DECISIONS and DEFAULTS below.

**2. RESEARCH HARD.**

- **The problem:** read `src/second/core/models.py`. Those types are exactly what
  your screens render. **Verify every claim in this brief against the actual
  code. Briefs are regularly wrong.**
- **⭐ THE VERSION:** pinned versions below were checked **2026-09-10**. Note
  TypeScript's `latest` tag is now **7.0.2** and this project pins **5.9.3**
  deliberately — see DECISIONS. Follow the pin.
- **The approach:** confirm the pattern is current. React 19 and Vite 8 have both
  moved; do not carry a React 17 habit into them.
- **The whole package** before building any of it.
- **The options** for any choice you face — before you would ask about them.

**3. BUILD EVERYTHING YOU CAN.** If the backend is not ready, **build against the
fixture and finish anyway.** See DEFAULTS.

Prove every guard by watching a test fail before it passes. Fix the sibling call
site.

**3b. Stop mid-package for exactly two reasons:** you need something you do not
own, or the choice is irreversible and this brief did not decide it. Everything
else: take the default, note it, keep building.

**⭐ NEVER ASK AN ABSTRACT QUESTION.** Every question must carry: the options you
considered and how you checked them · the constraint that decides between them ·
**your recommendation** · and **what you will do if nobody answers**.

**4. Commit to branch `surfaces`. Never push.** `git add` explicit paths only.

**5. Report through the protocol** — append your turn, end with `WAITING ON: CTO`,
give the user ONE fenced relay line.

**6. Only the CTO merges and pushes.**

⚠️ Work in your worktree: **`C:\Users\jivwe\second-surfaces`**. Run `uv sync`
once there, and `npm install` in `web/`.

---

## STEP 0 — READ BEFORE YOU EDIT ANYTHING

1. **`cto.md`** — THE communication file.
2. **`prompts/OWNERSHIP-MAP.md`** — the shared rules, including the product voice.
3. **`src/second/core/models.py`** (~300 lines) — **read every line.** This is
   your render contract: `LivingGraph`, `Goal`, `Route`, `Task`, `PersonModel`,
   `Link`, `TodayCard`, `PreparedAction`, `AuditEntry`.

**This is your first brief, so stop after the read and post a status turn:** what
you read, the biggest risk you found, one thing you actually ran, and your
proposed screen order. **After that turn, do not stop again.**

---

## ⭐ DECISIONS ALREADY MADE — do not re-open these

- **Four screens. No more.** Record, Living Graph, Today, Goals. A fifth screen
  is scope the deadline cannot afford, and the judging criteria reward one
  coherent thing over five thin ones.
- **You own the FastAPI layer, but it contains no logic.** Every route is a thin
  call into PLATFORM's service functions (see CONTRACTS) plus serialisation.
  Because HTTP shape is a UI concern and agent orchestration is not, and the
  seam between them is where the two domains stop colliding.
- **TypeScript pinned to 5.9.3, not the 7.0.2 that `npm view` reports as
  `latest`.** TypeScript 7 is a native rewrite released weeks ago; on a four-day
  build the ecosystem lag around a brand-new major is a risk with no upside.
  "Latest" means current stable, not newest published.
- **`@xyflow/react` for the Living Graph.** It is the maintained successor to
  React Flow, it does dependency edges and custom nodes out of the box, and
  hand-rolling a DAG layout is a day you do not have.
- **Dark and restrained. No component library.** Plain CSS or CSS modules. A
  design system is a week of value in a four-day build, and the visual identity
  here is *quietness*, which no component library gives you for free.
- **No auth, no multi-user, no routing library needed beyond the four screens.**
  Single hardcoded demo user. This is a submission, not a product launch.
- **`TodayCard | null` is the contract, and `null` is a first-class render.**
  Not an error, not a spinner, not "nothing to show yet". Design that state
  deliberately.
- **The Living Graph screen is the centrepiece and it must visibly change after
  every run.** Slipped tasks red, the blocking edge highlighted, Person-layer
  facts visible at the edges. If a judge cannot see the graph change, the product
  did not demonstrate its main claim.

## ⭐ DEFAULTS — proceed without asking

- **If the backend is not ready** → **build against a fixture and keep going.**
  Check in `web/src/fixtures/living-graph.json`, a realistic `LivingGraph` shaped
  exactly like `models.py`, and develop every screen against it behind a flag.
  This is the most important default here: the backend will be the last thing
  finished, and you must not be idle until then.
- **If a screen needs data the API does not return** → **that is a handoff, not a
  fix.** Do not compute it in the client. Report it with the exact field you
  need and build the rest of the screen around a placeholder.
- **If you need state shared across screens** → `zustand`. If a single screen
  needs it, plain `useState`. Do not add react-query, Redux, or a router library
  for four screens.
- **If a design choice is between "informative" and "encouraging"** → informative.
  Every time. Cite the evidence, show the number, skip the adjective.
- **If an API call fails** → show what failed, in one plain line, with a retry.
  **No generic "Something went wrong."** The product's voice is evidence-first
  and that applies to errors.
- **If a long operation is running** (a graph run takes tens of seconds) → show
  the transcript and the work in progress, not a spinner. The spec is explicit:
  display the transcript on screen while the graph renders, so there is something
  to watch during processing.
- **If you are unsure how a `PersonModel` fact should look on screen** → put it
  at the edge of the graph as a small annotation, not in a panel. It is context,
  not content.
- **If you finish early** → polish the Today screen's silence state and the
  Living Graph's change animation. Those two carry the demo.

## ⭐ CONTRACTS WITH OTHER DOMAINS — fixed before anyone builds

**HTTP routes — you implement these; the shapes are fixed.** PLATFORM provides
the service functions; you own the serialisation.

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/voice` | multipart audio | `{"job_id": str}` |
| `GET` | `/api/voice/{job_id}` | — | `{"status": "running\|done\|failed", "transcript": str \| null}` |
| `POST` | `/api/intake` | `{"transcript": str}` | `{"graph": LivingGraph, "questions": [str]}` |
| `GET` | `/api/graph` | — | `{"graph": LivingGraph}` |
| `POST` | `/api/daily/run` | — | `{"card": TodayCard \| null}` |
| `GET` | `/api/today` | — | `{"card": TodayCard \| null}` |
| `POST` | `/api/feedback` | `{"text": str}` | `FeedbackResult` |
| `POST` | `/api/goals/{goal_id}/status` | `{"status": "active\|paused\|retired"}` | `{"graph": LivingGraph}` |
| `GET` | `/api/audit?limit=50` | — | `{"entries": [AuditEntry]}` |

**Every payload is `Model.model_dump(mode="json")` from `core/models.py`.** No
bespoke response shapes. Generate the TypeScript types from those models rather
than hand-writing them if you can do it in under thirty minutes; hand-write them
otherwise.

**PLATFORM provides — do not implement these yourself:**

```python
# src/second/graphs/service.py   (PLATFORM owns)
async def run_intake(user_id: str, transcript: str) -> IntakeResult
async def run_daily(user_id: str, today: date) -> TodayCard | None
async def run_feedback(user_id: str, text: str) -> FeedbackResult
def load_living_graph(user_id: str) -> LivingGraph
def set_goal_status(user_id: str, goal_id: str, status: GoalStatus) -> LivingGraph
def read_audit(user_id: str, limit: int) -> list[AuditEntry]
```

**CONNECTORS provides** the voice seam PLATFORM wires into `/api/voice`. You send
the bytes; you do not talk to S3 or Transcribe.

**`/api/audit` exists for the demo.** A judge should be able to see every write
the system made. Give it a plain, readable screen or panel — it does not need to
be beautiful, it needs to be legible.

## OUT OF SCOPE FOR THIS PACKAGE

- Agents, prompts, reasoning — **AGENTS**
- Google/AWS calls, the microphone's server side — **CONNECTORS**
- Graphs, persistence, audit capture, deployment — **PLATFORM (CTO)**
- Auth, multi-user, mobile — **nobody. Not in this build.**

## DEFINITION OF DONE

- Four screens, working against the real API, dark and restrained.
- **Record:** one button, waveform, live transcript.
- **Living Graph:** goals → routes → tasks with dependency edges; slipped tasks
  red; the blocking edge highlighted; Person-layer facts at the edges; **it
  visibly changes after a run.**
- **Today:** at most one card — what was prepared, or the single decision needed
  — and a deliberate, designed empty state.
- **Goals:** list with pause and retire; **retiring visibly redistributes time.**
- FastAPI app serving all nine routes.
- `npm run build` clean; typecheck clean.

---

## YOUR PATHS

```
web/                       the whole React app
src/second/api/            FastAPI app, routes, serialisation
tests/api/
```

All greenfield. Nothing exists yet — you choose the `web/` internal structure.

## WHAT YOU DO NOT TOUCH

- An agent reasons badly, or a card says the wrong thing → **AGENTS**
- Calendar or Gmail returns wrong data → **CONNECTORS**
- A service function is missing or returns the wrong shape → **PLATFORM (CTO)**
- A shared type is missing a field → propose it; **PLATFORM** lands it

## WHAT IS ALREADY TRUE HERE

**Stack, pinned 2026-09-10:**

| Thing | Version | Why |
|---|---|---|
| `react` / `react-dom` | 19.3.0 | current stable |
| `vite` | 8.2.2 | current stable |
| `@vitejs/plugin-react` | 6.1.1 | matches Vite 8 |
| `typescript` | **5.9.3** | deliberate pin; `latest` is 7.0.2, see DECISIONS |
| `@xyflow/react` | 12.11.6 | the Living Graph |
| `zustand` | 5.0.15 | only if cross-screen state is genuinely needed |
| `fastapi` | 0.141.1 | current stable |
| `uvicorn` | 0.52.4 | current stable |
| Python | 3.12 | matches the rest of the build |

**Nothing of the backend exists yet** beyond the shared contract and the Phase 0
proof. The API will arrive underneath you. **Fixture first.**

**No AWS credentials are configured yet.** You never needed them.

## FIRST THINGS WORTH DOING

Ranked. The first is first because it unblocks you from everyone else.

1. **The fixture and the type layer.** A realistic `LivingGraph` JSON plus the
   TypeScript types generated or written from `models.py`. Everything else in
   your domain is downstream of it, and it costs you nothing to be wrong about
   the backend's readiness afterwards.
2. **The Living Graph screen.** It is the centrepiece, it is the hardest, and it
   is the one a judge remembers. Build it before the easy screens.
3. **Today, including the silence state.** Small, and it carries a scored
   product claim.
4. **The FastAPI layer**, once PLATFORM's service functions exist. Thin.
5. **Record.** Depends on CONNECTORS' voice seam; build the UI against a fake
   transcript first.
6. **Goals.** Simplest, and its "retiring redistributes time" behaviour depends
   on the Scheduler being finished, so it is naturally last.

**The project cut list, in order, if the schedule tightens:** hooks audit log,
Resource Finder, voice input, Living Graph visualisation. Note that the Living
Graph visualisation is on it — build it early and well so it never gets there.


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

1. **The Record screen gets a genuinely live transcript, for free.** Use the
   **Chrome Web Speech API** (`SpeechRecognition` / `webkitSpeechRecognition`,
   verified present in Chromium 152) to paint words as they are spoken - no
   polling, no AWS, no latency. Amazon Transcribe still runs in the background on
   the uploaded audio and its accurate result swaps in when the job lands.
   **The user perceives zero latency and the graph gets the accurate transcript.**
   This is a better Record screen than the brief described; build to it.

2. **Audio reaches S3 by presigned PUT from the browser.** CONNECTORS mints the
   URL. **Send `Content-Type: audio/webm` exactly** - bare, no `;codecs=opus`,
   even though that is what `MediaRecorder.mimeType` reports. The signature
   covers the content type, and a mismatch gives an opaque 403 that reads like a
   CORS failure. If you see a 403 on upload, check this before anything else.

3. **`fastapi` is not installed yet.** `uvicorn` 0.52.4 is present, FastAPI is
   not. I am adding `fastapi==0.141.1` to the project - run `uv sync` in your
   worktree once I have landed it.

4. **`/api/audit` matters more than the brief implied.** The audit trail is now
   the demo's primary evidence that the system is doing what it claims, and a
   judge will be pointed at it. Give it a real, legible screen or panel -
   chronological, showing node spans and tool writes, with failures marked. It
   does not need to be beautiful; it needs to be readable at a glance on a
   recording.

5. Region and model are pinned to `us-west-2` and
   `global.anthropic.claude-sonnet-4-6` if you surface either in config or a
   status line.

Nothing else in your brief changed. The nine routes, the four screens, the
`TodayCard | null` contract and the TypeScript 5.9.3 pin all stand.

### CTO note - the backend behind your routes now exists

`second/graphs/service.py` is landed with every function your brief promised:
`run_intake`, `run_daily`, `run_feedback`, `load_living_graph`,
`set_goal_status`, `read_audit`. 30 tests green. **Your nine routes and their
shapes are unchanged** - build against them.

Two things worth knowing:

- **`run_daily` returns `TodayCard | None`, and `None` is the common case.**
  Behind it, the Communicator now emits a typed `Communique` carrying
  `should_speak` and a `silence_reason` that goes to the audit log. Your contract
  does not change, but the silence state you are designing is a deliberate
  decision the system recorded, not an absence of data. If you want to show *why*
  it stayed quiet, the reason is in `/api/audit`.
- **`run_intake` returns `IntakeResult`** - `{graph, clarifying_questions,
  schedule}`. When `clarifying_questions` is non-empty, `schedule` is `None`:
  the graph deliberately stopped before planning because it was not clear enough
  what the user wanted. **That is a screen state worth designing** - Second
  asking one question back rather than showing a confident wrong plan.

`fastapi==0.141.1` is now installed. Run `uv sync` in your worktree.

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

### What this means for you: Today is a day view, and the graph is a tree

**Two of your four screens change shape. Neither gets harder; both get better.**

**`GET /api/today` and `POST /api/daily/run` now return `DailyBrief`, never
null.** The old `{"card": TodayCard | null}` is gone.

```json
{ "on": "2026-09-10",
  "blocks": [ { "title": "Record five minutes and listen back",
                "start": "2026-09-10T08:00:00+01:00", "duration_min": 60,
                "goal_title": "Get comfortable speaking to a room",
                "horizon": "year",
                "serves": ["Raise a Series A", "Build a company that outlives me"] } ],
  "prepared": [...], "at_risk": [...], "reminders": [...], "decisions": [],
  "notify": false, "silence_reason": "Nothing slipped, nothing needs deciding." }
```

**`serves` is the shot that sells the product.** A block reads:

> **08:00 · Record five minutes and listen back**
> *serving:* speak well → raise a Series A → build a company that outlives me

That is a to-do list answering "why this, today?" and it is the thing no calendar
app does. Design the block around it.

**The silence state moved, it did not disappear.** A quiet day still shows the
full schedule -- it just has no `decisions`, no push, and `notify: false`. What
you are designing is *"Second has nothing to ask you today"* sitting calmly above
a day that is fully planned. That is a better screen than an empty one, and a
better ten seconds of demo.

**The Living Graph screen now renders a tree.** Goals have `horizon` and
`contributes_to`. Root ambitions at the top, tasks at the leaves.
`@xyflow/react` does hierarchical layout, so this is mostly a layout choice, and
the depth is what makes the visualisation worth looking at. Slipped tasks still
red, blocking edges still highlighted, Person-layer facts still at the edges.

Nothing else changed. Your other seven routes, the four-screen limit, the
TypeScript 5.9.3 pin and the restraint all stand.

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

### What this means for you: one new element, and it is a good one

`DailyBrief.check_in` is `CheckIn | None`. When present it holds yesterday's
work, each item **already carrying Second's guess and the evidence for it**:

```json
{ "on": "2026-09-09",
  "items": [
    { "task_id": "t-gym", "title": "Gym session",
      "goal_title": "Train three times a week",
      "scheduled_for": "2026-09-09T18:00:00+01:00",
      "inferred": "likely_missed",
      "evidence": "18:00 invite declined; 'Eng sync' ran at the same time." },
    { "task_id": "t-recording", "title": "Record five minutes and listen back",
      "goal_title": "Get comfortable speaking to a room",
      "scheduled_for": "2026-09-09T08:00:00+01:00",
      "inferred": "unknown", "evidence": "" }
  ] }
```

**Design it as confirmation, not data entry.** Second has already done the work;
the user is correcting a pre-filled answer. A tick and a cross per row, with the
evidence readable underneath. `inferred: "unknown"` with an empty `evidence` is
Second saying plainly *"I could not tell"* -- that row should look different from
the ones it has a view on, and it is the honest one.

**It does not notify.** It rides inside the brief the user already opened.

Answers go back through `POST /api/feedback` -- **no new route**. Send what the
user said or tapped as text; the Interpreter turns it into typed completions.

`CheckIn` also exposes `uncertain` (the items Second could not work out), if you
want to lead with those.

---

## SURFACES — turn 1 · 2026-09-10T23:09Z
**asks:** one ruling — `set_goal_status(reschedule=...)` is unwired, so "retiring visibly redistributes time" has no data path through my route; I ship "visibly *frees*" unless you wire it.
**phase:** research — complete. Building next, no further stops.

**Read:** `cto.md`, `prompts/OWNERSHIP-MAP.md`, all **692 lines** of `core/models.py`, plus `graphs/service.py`, `graphs/brief.py:222-280`, `persistence/store.py`, `settings.py`, `app.py`, `pyproject.toml`, `uv.lock`.

**Ran:** `pytest -q` → **117 passed** (baseline; the brief says 94 in one place and 30 in another). `scripts/phase0_proof.py` → all claims proved. Then the run that changed my plan:

```
$ python -c "assemble(graph=demo_scenario.living_graph(), clock=Clock.fixed(today), judgement=None)"
goals 6  roots 3  routes 5  tasks 6  links 3   horizons: life three_year year month
slipped: t-recording(3) t-pitch(3) t-gym(4) t-flights(2)
depends: t-flights -> ['t-leave']          # t-leave: pending, zero scheduled_slots
blocks 1  at_risk 2  check_in True  is_quiet True
  2026-09-11T19:00+01:00  Attend speaking club
  serves: ['Raise a Series A', 'Build a company that outlives me']
```

**`demo_scenario.living_graph()` (`src/second/testing/demo_scenario.py:75`) is my fixture — I do not hand-write one.** I generate `web/src/fixtures/*.json` from it, so it is shape-exact by construction and cannot drift from `models.py`. `brief.assemble(judgement=None)` gives me a real `DailyBrief` with **no model call and no AWS credentials** (`brief.py:244-253`), which means every screen develops against true data today. Types via `model_json_schema()` → `json-schema-to-typescript`; generator lives in `web/scripts/`, inside my own path.

The demo graph also already contains every visual state the Living Graph screen has to prove: **three roots at two different horizons** (`life`, `life`, `month` — a root is not always at the top rung), four slipped tasks, one dependency edge whose upstream task is unscheduled, and three person-layer links.

### The biggest risk, and it is not in the frontend

| | |
|---|---|
| **What** | `set_goal_status(user_id, goal_id, status, *, reschedule=False)` — `service.py:90-119`. The docstring at `:103-105` says *"Reserved for re-running the Scheduler over the freed time. **Not yet wired** — the Goals screen currently shows the freed slots and the next Daily run reallocates them."* And `POST /api/goals/{id}/status` returns `{graph}` only — no `ScheduleDecision`. |
| **So** | The Definition of Done line **"retiring visibly redistributes time"** cannot be satisfied by any amount of UI work. No route returns the redistribution. |
| **Options** | (a) recompute the reallocation in the client — my brief forbids it, and it would be Second showing a plan it did not make; (b) chain `POST /api/daily/run` after a retire, so the schedule genuinely moves — real, but it costs a live model run of tens of seconds mid-demo and the beat depends on AGENTS' Scheduler; (c) render the **freed** slots: the retired goal's tasks struck through with their `scheduled_slots` shown, and one line naming what the next daily run will reallocate. |
| **Recommendation** | **(c)**, and it is honest rather than a downgrade — Second says what it has actually done. Take (b) only if you want the beat badly enough to spend a live run on it, in which case say so and I will put it behind one button. |
| **If nobody answers** | I build (c) and move on. |

### Three smaller findings, each yours not mine

| # | Finding | Ask |
|---|---|---|
| 1 | **Only one block lands today** from the demo scenario (run above). Today is a *day view* now; on the recording it will be one row. `demo_scenario.py` is PLATFORM's. | Consider two or three slots on the demo day. |
| 2 | **`Task.scheduled_slots` are naive datetimes** (`2026-09-11T19:00:00`, no offset) while `ScheduledBlock.start` is tz-aware (`+01:00`) — both in the run above. Two of my screens render times from differently-shaped datetimes. | I treat naive slots as local and never compare across the two. Normalise at the contract if you would rather. |
| 3 | **`uvicorn` 0.52.4 is present only transitively** — `uv.lock:226` via `bedrock-agentcore`, `uv.lock:1087` via `mcp`. It is not in `pyproject.toml` dependencies. Drop `bedrock-agentcore` and my dev server vanishes. | Pin `uvicorn==0.52.4` directly. Cheap. |

### WHAT THE BRIEF GOT WRONG

| Brief says | Actually |
|---|---|
| `/api/today` and `/api/daily/run` return `{"card": TodayCard \| null}` | `DailyBrief`, **never null** (`service.py:153-189`). Your later addendum corrected this; the route table at the top of the brief still carries the dead shape. |
| `TodayCard \| null` is the contract and `null` is a first-class render | **`TodayCard` does not exist.** `grep -rn TodayCard src/ tests/` returns nothing. The silence state is `DailyBrief.is_quiet` (`models.py:481`). |
| `/api/intake` returns `{"graph", "questions"}` | `IntakeResult` is `{graph, clarifying_questions, schedule}` (`models.py:532`). Per *"no bespoke response shapes"* I return the model verbatim and drop `questions`. Flag it if you wanted the shorter key. |
| "If you want to show *why* it stayed quiet, the reason is in `/api/audit`" | `models.py:521` and `:657` both say `silence_reason` is **"never shown to the user"**. The contract wins: it appears in the audit panel only, never on Today. |
| `/api/audit` should show **node spans** | `AuditEntry` (`models.py:682-692`) has no duration field: `at, run_id, kind, actor, action, payload, is_write, failed`. There are no spans to render. I give chronology grouped by `run_id`, with `is_write` and `failed` marked. Newest first (`service.py:85`). |
| Surface `us-west-2` / `global.anthropic.claude-sonnet-4-6` | `MODEL_PROVIDER` defaults to `"anthropic"` and `ANTHROPIC_MODEL_ID = "claude-sonnet-5"` (`settings.py:15,39`). If a status line names a model it says **Sonnet 5, direct API**. |
| "94 tests are green" / "30 tests green" | **117.** |

One thing the brief got right that I want on the record: `LivingGraphStore.table` is lazy (`store.py:77-84`), so **every one of my nine routes imports and starts without AWS credentials** and only fails when actually called. Fixture-first is not a workaround here, it is the only way the app runs today.

### Proposed screen order

1. **Fixture + type layer** — generated from `demo_scenario` and `model_json_schema()`. Everything is downstream of it.
2. **Living Graph.** Centrepiece, hardest, and the fixture already proves the tree: roots at mixed horizons, slipped red, the `t-leave → t-flights` edge highlighted, person facts at the edges.
3. **Today** — the day view, `serves` on every block, the check-in as pre-filled confirmation, and the quiet state.
4. **Audit** — a **panel on Today, not a fifth screen.** Four screens stands.
5. **FastAPI**, nine routes, thin over `service.py`. Unblocked — `service.py` exists.
6. **Record** — Web Speech API live, Transcribe swapping in. Needs CONNECTORS' presigned PUT.
7. **Goals** — last, for the reason above.

### Footprint

```
$ git status --porcelain
 M prompts/instance-1-surfaces.md
```

No code written yet, so **no guards added and no mutation to report** — this is the read turn the brief asked for. Tests **117 passed**, unchanged from baseline. No typechecker yet: `web/` does not exist.

---
WAITING ON: CTO - rule on the retire beat (freed vs. redistributed); the three smaller items need no answer to unblock me

---

## CTO - turn 1 · 2026-09-10T23:24Z
**verdict:** approved. Option (c), and I have removed the reason it was a compromise.
**phase:** building - screens 1 and 2, no further stops

**I verified all four of your findings myself before ruling. All four confirmed.**
`uvicorn` was only transitive. `Task.scheduled_slots[0].tzinfo` is `None` while
`ScheduledBlock.start.tzinfo` is `Europe/London`. Exactly one block landed on the
demo day. `TodayCard` returns nothing from `grep -rn`. You were right on every
count, and the brief was wrong on every count.

### 1. The retire beat - (c), and it is no longer a downgrade

You were right that no amount of UI work fixes it, and right to refuse (a). A
schedule Second did not make is a schedule Second cannot stand behind.

So I gave you the data instead of the problem:

```python
class GoalStatusChange(BaseModel):
    graph: LivingGraph
    freed: list[ScheduledBlock]   # upcoming slots the goal was holding
    freed_minutes: int
    note: str                     # what happens to them, in plain words
```

`POST /api/goals/{goal_id}/status` returns that, not `{graph}`. On the seeded
demo, retiring `g-speaking` gives you **3 slots, 180 minutes**, each a full
`ScheduledBlock` with its `serves` chain intact - so you can strike them through
and show what they were feeding.

**It says freed, not redistributed, and that is the ruling.** The Scheduler has
not run at that moment. `note` carries when it will: *"The next daily run
reallocates them to the goals still active."* Your instinct was right - this is
honest rather than a downgrade, and I would rather ship the true sentence than
the impressive one. Not (b): a live model run mid-demo, dependent on AGENTS'
Scheduler, is a great deal of risk for one beat.

The Definition-of-Done line now reads *"retiring visibly frees time, and says when
it gets reallocated."* I changed the standard rather than asking you to meet an
impossible one.

### 2. Your three smaller items

| # | Ruling |
|---|---|
| 1 | **Fixed.** The demo day now has **three** blocks - 08:00 recording, 17:00 pitch, 18:00 gym - across **two different ambitions**, so `serves` visibly differs down the column. Better than three rows of the same chain. |
| 2 | **Your handling is correct; I have made it explicit rather than lucky.** The asymmetry is deliberate: the Living Graph stores wall-clock because a plan is what the person reads off their own calendar, and storing UTC would move the plan when they travel. Anything crossing the API boundary is made aware by `Clock.local()` so a browser cannot guess. Now stated on `ScheduledBlock.start` itself, with the warning never to compare a raw slot against one without passing it through the clock. |
| 3 | **Pinned.** `uvicorn==0.52.4` is a direct dependency now. Good catch - that was a dev server one `uv remove` away from vanishing. |

### 3. Where you corrected me, on the record

- **`questions` vs `clarifying_questions`** - return `IntakeResult` verbatim. You
  applied my own rule correctly and the brief contradicted itself.
- **`silence_reason`** - you are right and my addendum was wrong. The contract
  says never shown to the user. Audit panel only.
- **Audit spans** - correct, `AuditEntry` has no duration. I wrote "node spans"
  loosely. Chronology grouped by `run_id` with `is_write` and `failed` marked is
  exactly right.
- **Test count** - 126 as of this turn, and it keeps moving. Stop trusting any
  number in the brief; run it.

**Audit as a panel on Today rather than a fifth screen: approved, and the better
call.** Four screens holds.

### 4. Two things you do not know yet

- **The model provider changed.** You caught the Sonnet 5 pin; here is why.
  Bedrock refuses Anthropic models to this AWS account on country grounds,
  reproducibly, on both a current and a two-year-old model. We use Anthropic's
  API directly. Nothing in your domain changes - I mention it because a status
  line naming the model should say **Sonnet 5, direct API**, and because it is
  why `BEDROCK_MODEL_ID` still exists in settings and is not what runs.
- **`Diagnosis.evidence` is now nullable.** Forced tool choice means a model
  cannot decline, so a required evidence field compelled it to invent a quote
  when it had none. Now nullable, and an evidenceless diagnosis is coerced to
  `UNKNOWN` with confidence capped at 0.3. **For you:** a `Decision` may cite
  thin evidence, and honest uncertainty is a real render case, not an edge case.

### 5. Proceed

Your screen order is right and I am not changing it. One push: **spend your best
hour on the quiet state and the check-in**, not on the graph's prettiness. The
graph proves the system thought; the quiet day and the pre-filled check-in prove
it has judgement. That is the part nobody else will have built.

Build screens 1-4. Do not stop again until the package is done.

---
WAITING ON: SURFACES - build the fixture, type layer, Living Graph, Today and the audit panel; report once
