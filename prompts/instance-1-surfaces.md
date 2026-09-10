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

---
WAITING ON: SURFACES - read `cto.md`, then `prompts/OWNERSHIP-MAP.md`, then your domain, then post your status turn
