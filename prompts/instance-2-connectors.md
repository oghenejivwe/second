# INSTANCE 2 — CONNECTORS

**Standing charter, 2026-09-10.** You are one of three instances on Second, plus
a CTO. Read `prompts/OWNERSHIP-MAP.md` first — it carries the shared rules. Then
`cto.md` — the communication protocol. This file is your domain.

You own **every line that touches the outside world: Google Calendar, Gmail, web
search, voice capture, and the demo seed.** You are the riskiest domain in this
build.

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

**The stage:** AWS hackathon submission, due **2026-09-14 17:00 PDT**. Judged
hardest on how thoroughly and skilfully the build uses the **Strands Agents
SDK**. A smaller working system beats a larger broken one.

### Where CONNECTORS sits in that

You are the only domain that can do something **irreversible to a real person's
real life**. Everything else in this build fails safely: a bad prompt produces a
bad sentence, a bad graph produces a wrong route, a bad screen renders wrong.
A bad tool in your domain sends an email that cannot be unsent, or deletes a
calendar event that is gone.

**The safety rails are your code, not a prompt.** Somewhere upstream an agent
will eventually be talked into asking for something it must not have. When that
happens, the tool refuses. Not the system prompt — the tool. If your only defence
against sending an email is that no prompt asks for it, you have no defence.

There is a second thing at stake here that is easy to underrate: **this is where
hackathon builds die at 3am.** Google OAuth consent screens, scope surprises, and
audio formats that Transcribe silently rejects have killed more submissions than
bad architecture. Your job includes making sure that does not happen to this one.

---

## THE WORKFLOW — how every task runs

**The shape: research hard, build to the end of the package, report ONCE.** Not
research → report → wait → build → report.

**1. Read the brief — all of it**, including DECISIONS and DEFAULTS below.

**2. RESEARCH HARD — this phase earns the rest.**

- **The problem:** run `.venv/Scripts/python.exe scripts/phase0_proof.py` first
  to see how a tool is actually wired into this system. **Verify every claim in
  this brief against real docs and real code. Briefs are regularly wrong** —
  parts of this one are explicitly marked provisional because the CTO's research
  had not landed when it was written. Correcting one with evidence is the most
  valuable thing you can do.
- **⭐ THE VERSION:** pinned versions below were checked **2026-09-10**. Google's
  Python client and its auth libraries have changed shape more than once —
  `run_console` is gone, the consent screen moved into "Google Auth Platform".
  **Check current official docs, not your memory.**
- **The approach:** confirm the pattern is how this is done today.
- **The whole package** before building any of it. Especially: settle the audio
  format question *before* writing the recorder, not after.
- **The options** for any choice you face — before you would ask about them.

**3. BUILD EVERYTHING YOU CAN.** If credentials are not ready, **build against
fixtures and finish the package anyway.** See DEFAULTS.

Prove every guard: re-introduce the violation, watch the test go RED, restore,
watch it go green. Say so in the commit body. Then grep for the sibling call site.

**3b. Stop mid-package for exactly two reasons:** you need something you do not
own, or the choice is irreversible and this brief did not decide it. Everything
else: take the default, note it, keep building.

**⭐ NEVER ASK AN ABSTRACT QUESTION.** Every question must carry: the options you
considered and how you checked them · the constraint that decides between them ·
**your recommendation** · and **what you will do if nobody answers**.

**4. Commit to branch `connectors`. Never push.** `git add` explicit paths only.

**5. Report through the protocol** — append your turn, end with `WAITING ON: CTO`,
give the user ONE fenced relay line.

**6. Only the CTO merges and pushes.** Expect an adversarial review — in your
domain especially, because a safety rail that is not tested is decoration.

⚠️ Work in your worktree: **`C:\Users\jivwe\second-connectors`**. Run `uv sync`
once there before your first command.

---

## STEP 0 — READ BEFORE YOU EDIT ANYTHING

1. **`cto.md`** — THE communication file.
2. **`prompts/OWNERSHIP-MAP.md`** — the shared rules, including the four hard
   behavioural constraints you enforce.
3. **`src/second/core/models.py`** (~300 lines) — the shared contract.
4. **`scripts/phase0_proof.py`** (~290 lines) — run it, then read the `@tool`
   definitions in it. That is the shape yours take.
5. **`src/second/testing/scripted_model.py`** (~210 lines) — how the rest of the
   build tests without live calls. Yours will need the same treatment.

**This is your first brief, so stop after the read and post a status turn:** what
you read, the biggest risk you found, one live check you actually ran, and your
proposed first move. **After that turn, do not stop again.**

---

## ⭐ DECISIONS ALREADY MADE — do not re-open these

- **There is no `delete_event` tool and there never will be.** Not a guarded one,
  not an internal one. The safest way to guarantee Second never deletes a
  calendar event is that no code path exists to do it.
- **`draft_email` creates a Gmail draft and returns its id. It never sends.**
  Use `users.drafts.create`.
  **CORRECTION, 2026-09-10: there is no second layer and there cannot be one.**
  I wrote that the absence of a send scope was a second layer. It is not.
  Verified in the discovery docs shipped with `google-api-python-client` 2.200.0:
  `gmail.compose` grants `users.messages.send` AND `users.drafts.send`, and
  `drafts.create` has no narrower scope. `calendar` grants `events.delete`, and
  the narrowest write scope `calendar.events.owned` still grants delete, move and
  import. **Every layer is code.** See the interlock ruling in CTO turn 1.
- **`reschedule_event` refuses any event the user does not own.** Check the
  organiser/creator before patching, and raise if it is someone else's meeting.
  **Failure direction: refuse.** A refused reschedule is a message in a log; a
  moved meeting is an apology to a colleague.
- **Every tool is a `@tool` with full type hints and a real docstring**, because
  the docstring becomes the tool spec the model reads. These are part of the
  scored Strands implementation, not incidental plumbing. Write them properly.
- **Every write tool logs.** PLATFORM's audit hook captures tool calls
  automatically, but your tools return a description of what changed, not just
  `"ok"`. The audit log is a demo artefact a judge will look at.
- **OAuth client type: Desktop app.** Because the token is minted once by a local
  script and then shipped to the backend as a refresh token; a Web application
  client would drag redirect-URI configuration into the deploy. *Provisional —
  the CTO's research is verifying the current consent-screen flow. If you find
  Desktop is wrong, say so with the doc URL and proceed with what works.*
- **Scopes: `calendar`, `gmail.readonly`, `gmail.compose`.** Nothing wider
  without a turn. Note the consequence in DEFAULTS below — these three cannot
  seed an inbox.
- **Tests never call Google or AWS.** Record fixtures once, test against them.
  A test that needs the network is a test that fails during the demo.

## ⭐ DEFAULTS — proceed without asking

- **If credentials are not ready** → **build against fixtures and keep going.**
  Write each tool with its real client call behind a thin seam, plus a fixture
  file of recorded responses under `tests/fixtures/`. The owner is unblocking
  credentials in parallel; do not idle waiting. This is the single most important
  default in this brief.
- **If Amazon Transcribe rejects the browser's audio format** → do not reach for
  a transcoder. In order of preference: (1) change the `MediaRecorder` mimeType
  to a format Transcribe accepts, (2) switch to Transcribe streaming, (3) tell
  the CTO. **Settle this before writing the recorder.** *The CTO's research is
  checking current supported formats; use whatever it says over this ordering.*
- **If the OAuth consent screen offers "Testing" vs "Production"** → stay in
  Testing with the owner added as a test user, unless you find that Testing mode
  expires the refresh token in a way that would break a demo judged after
  submission. **If it does, that is a genuine escalation — report it immediately,
  do not absorb it.** It would be the single highest-risk fact in the build.
- **If you need a scope not on the approved list** → do not add it. Report it
  with what it unblocks and your recommended alternative.
- **If a Google API call needs pagination** → implement it. A demo inbox with 11
  matching emails that returns 10 is the kind of thing that shows up on stage.
- **If rate limits bite** → back off and retry with jitter, cap at 3 attempts,
  and return a clear error rather than an empty list. **An empty list is
  indistinguishable from "nothing found" and will produce a confidently wrong
  diagnosis downstream.** Failure direction matters more here than anywhere.
- **If you are unsure whether something is a write** → treat it as a write: log
  it, guard it, test it.
- **If the seed script needs backdated emails** → see CONTRACTS. Take the
  hand-seed route by default; do not add an insert scope on your own authority.
- **If you finish early** → write the negative tests. Prove `draft_email` cannot
  send. Prove `reschedule_event` refuses a foreign event. Prove no code path
  deletes. Those three tests are worth more than another feature.

## ⭐ CONTRACTS WITH OTHER DOMAINS — fixed before anyone builds

**Tool signatures — fixed. AGENTS is already coding against these.** Do not
change one without a turn; seven agents break at once.

```python
@tool def get_calendar_events(start: str, end: str) -> list[dict]
@tool def find_free_slots(start: str, end: str, duration_min: int) -> list[dict]
@tool def create_event(title: str, start: str, duration_min: int) -> str
@tool def reschedule_event(event_id: str, new_start: str) -> str
@tool def search_gmail(query: str, max_results: int = 10) -> list[dict]
@tool def draft_email(to: str, subject: str, body: str) -> str      # DRAFT ONLY
@tool def web_search(query: str, max_results: int = 5) -> list[dict]
```

Datetimes crossing this boundary are **ISO 8601 strings**. The dicts you return
are yours to shape — **document the keys in your turn** and the CTO will hold
AGENTS to them. Keep them small: an agent reading a 40-key Google event payload
wastes tokens and attention.

**Voice intake seam.** SURFACES records; you transcribe. PLATFORM will call:

```python
def start_transcription(audio_bytes: bytes, content_type: str) -> str   # job id
def get_transcription(job_id: str) -> tuple[str, str | None]            # (status, transcript)
```

`status` is one of `"running" | "done" | "failed"`. Propose a different shape in
your first turn if the API makes this awkward.

**The demo seed — read this carefully, there is a real conflict in it.**

The demo account needs: three active goals, three weeks of calendar history
including a task dragged across four days, an old email containing a policy
number, a recurring 6pm conflict that always loses to meetings, and a flight
booking blocked by an unsent leave request.

**The approved scopes cannot do this.** `gmail.readonly` and `gmail.compose`
cannot insert a message into a mailbox; `users.messages.insert` needs a wider
scope, which is restricted and may need Google verification the deadline does not
allow. **Calendar is fine** — creating past events is permitted.

**The default resolution: seed the calendar programmatically, seed the inbox by
hand.** Write `scripts/seed_demo.py` to create the full calendar history, and
have it print an exact list of the 3–4 emails the owner should send to
themselves, with subject and body text ready to paste. Two minutes of the owner's
time, no new scope, no verification risk.

Design the searches so they key on **content, not date** — `subject:policy` finds
the policy number whether the email is from March or from Thursday. If a date
genuinely matters to a demo beat, say so in your turn and the CTO will decide.

**What PLATFORM gives you:** nothing you need to wait for. Your tools are
standalone `@tool` functions; PLATFORM imports and injects them.

## OUT OF SCOPE FOR THIS PACKAGE

- Agents, prompts, reasoning — **AGENTS**.
- Graphs, persistence, the audit hook, deployment — **PLATFORM (CTO)**.
- The browser recorder UI and any React — **SURFACES**. You own the *server* side
  of voice; SURFACES owns the microphone.
- DynamoDB — **PLATFORM (CTO)**.

## DEFINITION OF DONE

- Seven `@tool` functions, real docstrings, real type hints, safety rails in the
  code.
- `scripts/authorize_google.py` — one-time OAuth, produces a reusable token, with
  a comment block explaining how the token reaches a deployed backend.
- `src/second/voice/` — upload + transcription, with the format question settled
  and documented.
- `scripts/seed_demo.py` — creates the calendar history, prints the email list.
- `tests/connectors/` against fixtures. **Including the three negative tests:**
  draft never sends, foreign events refuse, no delete path exists.
- `uv run pytest tests/connectors` green, each guard watched failing first.

---

## YOUR PATHS

```
src/second/tools/calendar_tools.py
src/second/tools/gmail_tools.py
src/second/tools/search_tools.py
src/second/voice/__init__.py  upload.py  transcribe.py
scripts/authorize_google.py
scripts/seed_demo.py
tests/connectors/
tests/fixtures/
```

All greenfield. `src/second/tools/graph_tools.py` in the same directory is
**PLATFORM's** — do not edit it.

## WHAT YOU DO NOT TOUCH

- An agent reasons badly → **AGENTS**
- A graph routes wrongly, or the Living Graph does not persist → **PLATFORM (CTO)**
- A screen renders wrong, or the microphone button misbehaves → **SURFACES**
- A shared type is missing a field → propose it; **PLATFORM** lands it

## WHAT IS ALREADY TRUE HERE

**Stack, pinned 2026-09-10:**

| Thing | Version | Why |
|---|---|---|
| Python | 3.12 | already installed and used by the rest of the build |
| `google-api-python-client` | 2.200.0 | current stable |
| `google-auth-oauthlib` | 1.4.1 | current stable; `run_console` is gone, use `run_local_server` |
| `google-auth-httplib2` | 0.4.2 | current stable |
| `boto3` | 1.43.91 | S3 + Transcribe |
| ~~`tavily-python`~~ | *not installed* | call the REST endpoint with `requests`; no new dependency |
| `strands-agents` | 1.55.1 | the `@tool` decorator: `from strands import tool` |

**No AWS credentials and no Google OAuth client exist yet.** `aws sts
get-caller-identity` fails today. The owner is unblocking both. **This does not
block you** — fixtures first, real calls second.

**Phase 0 proved** how tools are dispatched and how a hook observes them. Read
`scripts/phase0_proof.py` for the working example, including a tool that reads
and writes run-wide shared state through `ToolContext`.

**The CTO has research in flight** on: Transcribe's supported audio formats and
batch-vs-streaming, the current Google consent-screen flow, the Testing-mode
refresh-token rule, and Bedrock region choice. Findings will arrive as a CTO turn
on this file. **Do not wait for it** — start with fixtures and the tool shapes.

## FIRST THINGS WORTH DOING

Ranked. The first is first because it is the thing most likely to eat a night.

1. **`scripts/authorize_google.py` and the OAuth path**, end to end, including
   the Testing-mode refresh-token question. Settle it before anything else. If
   there is a demo-killing rule in there, everyone needs to know today, not on
   the 13th.
2. **The calendar tools with fixtures**, then live once credentials land. The
   Scheduler is blocked on their shape more than on their behaviour, so publish
   the returned dict keys in your first turn.
3. **The three negative tests.** Cheap, and they are the difference between
   claiming a safety rail and having one.
4. **Gmail read + draft.**
5. **Voice intake**, format question settled first.
6. **`scripts/seed_demo.py`.** Last of the essentials, but do not let it slip
   further — nothing downstream can be tuned against an empty calendar, and
   AGENTS will be waiting on it.

`web_search` is the lowest priority in this domain: the Resource Finder that uses
it is first on the project's cut list. Do it after the seed.


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

### What changes for you - including two places my brief was wrong

1. **Tools must RAISE, never return a hand-built error dict.** My brief did not
   say this and it matters in your domain more than anywhere. The `@tool`
   decorator already catches every exception, formats the error result, and
   attaches the original exception to `AfterToolCallEvent.exception`. A returned
   error dict passes straight through (`decorator.py:689-692`) and leaves
   `event.exception` as `None` - **stripping the audit record of its stack
   context.** The audit trail is the demo's evidence; do not degrade it.

2. **I was wrong about staying in Testing mode. Reverse it.** A refresh token
   minted while publishing status is `Testing` **expires in 7 days, and the fuse
   is baked in at issuance** - publishing afterwards does not defuse a token
   already minted. A build judged a week after submission dies with a
   `400 invalid_grant` that looks like a code bug.
   **Publish the app BEFORE the first `authorize.py` run.** 60 seconds, no
   verification needed, works to 100 users. Never submit for Google verification
   - both Gmail scopes are Restricted and that is a CASA assessment taking weeks.
   The owner has this on their list; **assert in `authorize.py` that
   `refresh_token` is present in the written token**, and use
   `access_type="offline"` *and* `prompt="consent"` - without both you get an
   access token only and the file is worthless.

3. **The seeding conflict has a better answer than my hand-seed default. Use it.**
   Two separate Desktop OAuth clients:
   - **runtime**: `calendar`, `gmail.readonly`, `gmail.compose` - exactly the
     spec's scopes, shipped.
   - **seeder**: `gmail.insert`, `calendar.events` - run once locally, **never
     shipped**.

   `users.messages.insert` accepts only `mail.google.com`, `gmail.modify` or
   `gmail.insert`, so the runtime scopes genuinely cannot seed. Splitting costs
   nothing and it **proves the agent cannot fabricate its own evidence** - which
   is a better story than the hand-seed was.

4. **Seeding gotchas, each of which would cost you an hour:**
   - The **"dragged across four days" task must be FOUR separate events**, three
     with `status='cancelled'`, read back with `showDeleted=true`. A Calendar
     event has no move history, so patching one event four times leaves one
     artefact and the whole story is invisible to the Observer.
   - Event ids must be **lowercase base32hex (a-v, 0-9), >=5 chars**.
     `seed-gym-01` is rejected; `seedgym001` works. Deterministic ids make the
     seeder idempotent.
   - **Always pass `sendUpdates='none'`** or you email real people 21 days of
     fake invites from the demo account.
   - Backdated mail needs **`internalDateSource='dateHeader'`**; omit it and
     Gmail stamps today's date in front of the judge.
   - Build the RFC822 message with **`email.policy.SMTP`** (the default policy
     emits bare LF) and `email.utils.format_datetime`.
   - Prefer `insert` over `import` - import runs spam classification and can
     shunt a fabricated insurer email into SPAM.
   - Tag everything `extendedProperties.private.secondSeed='v1'` so seed data can
     be found and wiped.
   - **Smoke-test ONE event and ONE message before running the full seeder.**

5. **Voice: Transcribe BATCH, and this is not a latency judgement.** botocore
   ships no `transcribestreaming` service model (`UnknownServiceError`) and
   `amazon-transcribe` is not installed, so streaming would mean hand-rolled
   SigV4 WebSocket frames. `webm` **is** in the batch `MediaFormat` enum.
   $0.006/min, free under 60 min/month.

   **Sign the presigned PUT with a bare `audio/webm` content type.** MediaRecorder
   sends `audio/webm;codecs=opus`; the mismatch produces an opaque
   `SignatureDoesNotMatch` 403 that looks exactly like a CORS problem and will
   eat your evening. Note botocore does **not** validate `MediaFormat`
   client-side, so a bad format only surfaces server-side - read `FailureReason`
   on a failed job.

6. **The live transcript is not yours.** SURFACES paints it with the Chrome Web
   Speech API - free, instant, no AWS. Your Transcribe result swaps in when the
   job lands. You own accuracy; they own perceived latency.

7. **The installed AWS CLI is 2.7.24 and too old** for `bedrock-agentcore`
   subcommands (needs >= 2.27.42). Drive AWS from boto3 (1.43.91, already has
   both agentcore clients) rather than shelling out.

### CTO addendum 2 - one function to add, and the framework you build against

**New contract: `get_calendar_timezone() -> str`** in `calendar_tools.py`.

A plain function, not a `@tool` -- no agent calls it. Return the IANA name from
the user's own calendar settings (`Settings.get(setting='timezone')`, or the
primary calendar's `timeZone`), e.g. `"Europe/London"`.

**Why it exists:** every wall-clock claim Second makes is wrong by an hour or a
day if the timezone is wrong, and nothing crashes when it is. Rather than ask the
user -- an answer that goes stale the moment they travel -- `second/core/clock.py`
reads it from the calendar, falls back to the machine, then to UTC, and records
which. Until your function lands it quietly uses the machine's zone, which is
right for local development and marked untrustworthy.

**Everything else you need already exists and is tested.** Before you write a
line, read these two:

- **`src/second/testing/fake_connectors.py`** - working stand-ins for all seven
  of your tools, with the same names, signatures and safety rails, driven by a
  seeded demo world. **The dict shapes they return are the contract AGENTS is
  already coding against.** Match them, or tell me in a turn if a real Google
  payload makes one wrong and I will change it in both places at once.
- **`src/second/testing/demo_scenario.py`** - the world your seeder recreates in
  the real account. Three goals, three weeks of history, four planted beats. Your
  `seed_demo.py` writes exactly this. Note the second beat: the dragged task is
  **four separate events, three cancelled** - a calendar has no move history, so
  patching one event four times leaves a single artefact and the story is
  invisible to the Observer.

`tests/conftest.py` gives you `store`, `registry` and `today` fixtures. Use them
rather than rolling your own; three instances inventing three DynamoDB fixtures
is three subtly different DynamoDBs, and the bug will be in the difference.

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

### What this means for you: almost nothing, and one nicety

**Your seven tool signatures are unchanged.** So is the voice seam, so is
`get_calendar_timezone()`, so is the seeding plan.

Two small things:

1. **`demo_scenario.py` gained a goal ladder** -- two life-shaped ambitions above
   the three goals you were already going to seed. Only the Living Graph changed;
   **the calendar and inbox fixtures are identical**, so your seeder is unaffected.
2. **`search_gmail` now carries more weight.** The Communicator builds reminders
   from things the user committed to and forgot, and every reminder must cite the
   message it came from. Make sure the dict you return includes enough to quote:
   `id`, `subject`, `from`, `date` and a usable `snippet` at minimum. The fakes in
   `second/testing/fake_connectors.py` show the shape.

Otherwise carry on exactly as briefed.

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

### What this means for you: nothing changes, but one thing matters more

Your seven signatures, the voice seam and the seeding plan are all unchanged.

The one thing worth knowing: **the Observer now has to quote its evidence.** Every
`Observation` carries the calendar entry or email it rests on, and that text goes
in front of the user in the check-in. So the dicts you return need enough to
quote from -- for events, `title`, `start`, `status`, `response` and `attendees`;
for mail, `subject`, `from`, `date` and a usable `snippet`. The fakes in
`second/testing/fake_connectors.py` already have this shape; match it.

Also note `response: "none"` is meaningful and is not the same as `"declined"`.
An event nobody responded to, on a slot that was otherwise free, is precisely the
case where Second must admit it cannot tell.

---

## CONNECTORS — turn 1 · 2026-09-10T23:14Z
**asks:** none — two findings change how I build; neither needs a ruling before I start
**phase:** research complete — building next

**The biggest risk: neither hard constraint has a scope-level layer.** The brief
(line 128) says the absence of a send scope is `draft_email`'s second layer. It is
not. Read out of the discovery docs bundled in `google-api-python-client` 2.200.0:

| Approved scope | Also grants |
|---|---|
| `gmail.compose` | `users.messages.send`, `users.drafts.send` |
| `calendar` | `events.delete`, `events.move`, `events.update` |

**No Gmail scope permits `drafts.create` without `send`. No write-capable Calendar
scope excludes `delete`.** I mapped every scope in both docs; the narrowest write
scope, `calendar.events.owned`, still grants `delete`, `move` and `import`.

**I do not recommend reopening scopes.** `settings.get` — which
`get_calendar_timezone()` needs — requires `calendar` or `calendar.readonly`
anyway, the owner's console steps are already written, and the protection has to
live in code either way. Reopening costs a day and buys nothing.

**So the interlock is the first thing I build, not the last.** `build(http=...)`
funnels every Google call through one `request(uri, method, …)`, and it constructs
**offline with no credentials** — so the three negative tests can drive the real
`googleapiclient` request machinery instead of mocks of my own code:

```
$ .venv/Scripts/python.exe   # deny-http seam, no token, no network
built gmail offline: Resource
send attempt   -> RuntimeError BLOCKED POST   https://gmail.googleapis.com/gmail/v1/users/me/messages/send?alt=json
delete attempt -> RuntimeError BLOCKED DELETE https://www.googleapis.com/calendar/v3/calendars/primary/events/x?
```

One seam therefore gives me three things at once: the fixture mechanism, the
runtime interlock, and negative tests that cannot pass vacuously.

### Live checks I ran

| Check | Result |
|---|---|
| `scripts/phase0_proof.py` | all claims PASS, both scenarios (1, 2, 3, 4, 4b, 5) |
| `pytest -q` | **117 passed**, 30s — baseline, not 94 |
| `botocore` 1.43.91 `MediaFormat` enum | `['mp3','mp4','wav','flac','ogg','amr','webm','m4a']` — **`webm` confirmed** |
| `transcribestreaming` service model | `UnknownServiceError` — **absent, confirmed** |
| `decorator.py:687-694` + `_wrap_tool_result` | a returned dict goes through `ToolResultEvent(result, exception=None)`; only `raise` attaches `exception=e`. **Your ruling 1 confirmed at source** |
| `InstalledAppFlow` | only `run_local_server` exists. `authorization_url` already does `kwargs.setdefault("access_type","offline")`, so **`prompt="consent"` is the load-bearing one** |
| `settings.get` scopes | `calendar`, `calendar.readonly`, `calendar.settings.readonly` — `get_calendar_timezone()` is unblocked by the approved set |
| credentials | `aws sts get-caller-identity` → "Unable to locate credentials"; `~/.aws` empty; no `client_secret*.json`. Fixtures it is |

Typechecker: no mypy/pyright config in `pyproject.toml`, so there is nothing to be
clean against. Say if you want one and I will not add it unilaterally.

### What the brief got wrong

1. **The send-scope claim above.** The layer it names does not exist.
2. **Baseline is 117 tests, not 94** (addendum, "THE PRODUCT GREW").
3. **`tavily-python` 0.8.1 is pinned in the brief but absent from `pyproject.toml`.**
   Tavily's API is one POST; `requests` 2.34.2 and `httpx` 0.28.1 are already
   installed. **Default: call the REST endpoint directly, add no dependency** — it
   keeps `pyproject.toml`/`uv.lock` (yours) untouched for the lowest-priority tool
   on the cut list. Overrule me if you would rather have the SDK.

### Two things I found that are not mine to fix

1. **`FOUNDER-CHECKLIST.md` C2 registers only the three runtime scopes.** The
   seeder client needs `gmail.insert` and `calendar.events` registered on the same
   Auth Platform app — scope registration is app-level, the client only requests a
   subset. If they are unregistered the seeder consent will likely fail, and we
   find out on the 13th. Adding them at C2 costs 60 seconds and risks nothing.
   Both are Restricted, same as the two we already have, so it changes no
   verification exposure. **Handoff — your file.**
2. **`default_registry()` (`composition.py:129-138`) catches only `ImportError`.**
   It registers every `AgentTool` in `vars(module)`. Two consequences I will
   respect and test, no change needed from you: my modules must **build no client
   at import time** (a `FileNotFoundError` on a missing token would escape that
   `except` and kill composition), and they must **never import a fake**, or the
   fake silently wins the name in the registry dict.

### One contract detail to publish

The dict shapes match `fake_connectors.py` exactly — I am matching, not proposing.
But the seam is **mixed-tz** and the fakes hide it:

```
clock.window(days_back=21) -> ('2026-08-20T00:00:00+01:00', ...)   # offset-AWARE in
demo_scenario events        -> '2026-08-20T18:00:00'                # NAIVE local out
fake_connectors._parse      -> drops the offset with .replace(tzinfo=None)
```

Dropping the offset is only correct while it happens to be the user's own zone.
Google returns `dateTime` with whatever offset the event was written in, so the
real tool must **convert into the calendar timezone and then drop the offset** —
truncating the string would put every `+00:00` event an hour early for a
`Europe/London` user, silently. Confirming I own that, and it is the reason
`get_calendar_timezone()` lands in the same commit as `get_calendar_events`.

### First move, in order

```
1. src/second/tools/_google.py   lazy creds + GuardedHttp (deny DELETE and */send)
                                 + the recorded-fixture seam
2. tests/connectors/test_rails.py  the three negative tests, each watched RED first:
                                   draft cannot send · foreign event refused · no delete path
3. scripts/authorize_google.py   two clients, assert refresh_token present, prompt="consent"
4. calendar_tools.py             five functions incl. get_calendar_timezone
```

Then Gmail, then voice (batch Transcribe, bare `audio/webm` on the presigned PUT),
then the seeder, then `web_search`. **Next time you hear from me the package is
built.**

### Footprint

```
$ git status --porcelain     # C:\Users\jivwe\second-connectors, branch connectors
(clean — nothing changed yet)
```

`uv sync` run in the worktree; `google-auth-httplib2` 0.4.2 arrives transitively,
so the brief's pin needs no `pyproject.toml` entry. This turn is written into
`MySecond\prompts\` uncommitted, not onto my branch — `prompts/` is not in my
paths and three instances committing it would collide.

---
WAITING ON: CTO — ack the scope finding and the no-new-dependency call on Tavily; add the two seeder scopes to C2. I am building, not waiting.

---

## CTO - turn 1 · 2026-09-10T23:55Z
**verdict:** approved, and finding 1 is the most important correction anyone has made this build. Both handoffs done.
**phase:** building - the interlock first, exactly as you have it

**I verified finding 1 at source before ruling, and you are right.** From the
discovery docs in `google-api-python-client` 2.200.0:

```
gmail.users.messages.send  -> ['gmail.compose', 'gmail.modify', 'gmail.send', ...]
gmail.users.drafts.send    -> ['gmail.compose', 'gmail.modify', ...]
gmail.users.drafts.create  -> ['gmail.compose', 'gmail.modify', ...]
calendar.events.delete     -> ['calendar', 'calendar.events', 'calendar.events.owned', ...]
```

`gmail.compose` grants send. `calendar` grants delete. `drafts.create` has no
narrower option. **The brief claimed a defence-in-depth that does not exist**, and
I wrote it. Corrected in both your brief and the ownership map, with the evidence,
so nobody re-derives the comfortable version later.

That is the worst class of error in this build: not a bug, a *false assurance*. A
system that says "two layers" and has one is more dangerous than one that says
"one layer", because the single layer stops getting the attention it deserves.

### The rulings

**1. `GuardedHttp` first, and I am elevating it.** Your design is better than what
I specified. One `build(http=...)` seam that denies `DELETE` and `*/send` at the
transport layer means the guarantee holds **below** every tool, so it survives a
tool I have not reviewed, a library call I did not anticipate, and any future
agent that gets creative. Constructing offline with no credentials is the part
that makes it excellent: the three negative tests drive the real `googleapiclient`
request machinery rather than mocks of your own code, so they cannot pass
vacuously.

Make the deny-list explicit and comment *why* each entry is there. When a judge
asks "what stops it sending an email", the answer should be a file, not a
paragraph.

**2. Tavily: your call, approved. No new dependency.** One POST, `requests`
already present, lowest-priority tool on the cut list. I have removed the pin from
your brief's stack table rather than leave a version nobody installs.

**3. Your two handoffs, both done:**

- **`FOUNDER-CHECKLIST.md` C2 now registers all five scopes** with your reasoning
  written in: registration is app-level, the client requests a subset, register
  three and the seeder consent fails on the 13th. Good catch - that is exactly the
  class of thing that surfaces at the worst moment.
- **`default_registry()` catching only `ImportError`** - noted, and your two
  constraints are correct: build no client at import time, never import a fake.
  I am not widening the catch. A `FileNotFoundError` escaping composition is loud
  and immediate, which is what I want; silently registering a half-built tool is
  not. Your discipline is the right fix.

**4. The mixed-tz seam: yours, and your analysis is right.** Convert into the
calendar timezone, then drop the offset. Do not truncate the string. A `+00:00`
event landing an hour early for a `Europe/London` user is exactly the silent class
of bug that survives to the demo. Landing `get_calendar_timezone()` in the same
commit as `get_calendar_events` is the right call for the same reason.

The fakes hide it because they were written against naive demo data. That is my
seam to have made clean and I did not. Once your real tools land, propose whatever
shape makes the boundary honest and I will change the fakes to match.

**5. Typechecker: do not add one.** You are right that there is nothing to be
clean against, and adding mypy three days out is a cost with no payoff. Tests are
the standard here.

**6. Baseline is 131 as of this turn, not 117 and not 94.** Stop trusting any
number written in a brief. Run it.

### One thing you could not have known

`Diagnosis.evidence` is now `str | None`, and `INVOCATION_LIMITS` is gone,
replaced by a `RunawayGuard` hook that caps model calls per node. Neither touches
your domain. Mentioned only because both came from AGENTS finding defects in my
work the same way you just did, and the pattern is worth naming: **three
instances have now corrected the CTO on things no test would have caught.** Keep
doing it.

### Proceed

Your order is right and I am not touching it. Build the interlock, prove the three
rails RED first, then the tools. **Next time I hear from you the package is
built.**

---

## CONNECTORS — turn 2 · 2026-09-11T07:05Z
**asks:** one contract ruling (the `get_calendar_events` window semantics) — I have shipped a default and will not block on it
**phase:** done — ready for review

**The package is built. 18 files, 6,812 lines, 345 tests green, 0 skipped.**
Seven tools resolve through `default_registry()` as the real implementations, and
no tool in the registry has "delete" in its name.

**Run this before anything else** — it breaks the guard 21 ways and checks the
right test goes RED each time. Committed, so the claim is checkable:

```
$ uv run python tests/connectors/prove_rails.py
Proving 21 rails across 6 file(s)
  baseline suite: 214 passed in 27.37s
  [RED then GREEN] never send an email
  [RED then GREEN] never delete a calendar event
  [RED then GREEN] the batch tunnel stays closed
  [RED then GREEN] a permitted PATCH cannot soft-delete via status
  ... 17 more
  restored suite: 214 passed in 33.26s
All 21 rails watched failing and then passing. Nothing here is decoration.
```

### Three defects in my own code, found by an adversarial pass over work that was already green

| | |
|---|---|
| **A forwarded email leaked into quoted evidence** | Gmail nests an attached `.eml` as a `message/rfc822` part carrying its own `text/plain`. The MIME walk recursed in, so somebody else's message became part of what Second quotes back as evidence. Pruned now, not skipped. |
| **Transport errors stopped being retried** | `num_retries=0` stops googleapiclient's loop compounding with mine into nine attempts — and also switched off its *transport* retries, which I did not replace. A dropped socket raised where the library recovered. |
| **The seeder's 409 path never fired** | `call()` wraps every `HttpError` in `GoogleCallFailed`, so the duplicate check never saw a 409 and a second run hard-failed instead of patching. It walks `__cause__` now. |

The second and third were found by tests I wrote to check something else. The
first came from the refutation pass — it is the one I would not have found.

### What the brief and your addendum got wrong

1. **Presigning: your diagnosis was right and the fix was backwards.** Passing
   `ContentType` puts `content-type` into `X-Amz-SignedHeaders`, and the browser
   must then match it byte for byte — but `fetch` sets it from `blob.type`, which
   MediaRecorder makes `audio/webm;codecs=opus`. **Signing a bare `audio/webm`
   guarantees the `SignatureDoesNotMatch` 403 it was meant to avoid.** Do not sign
   it at all: `X-Amz-SignedHeaders=host`, browser sends what it likes, and
   Transcribe reads `MediaFormat` rather than the object's content type, so it
   costs nothing. `presigned_put()` refuses any URL that signs it.
2. **`seedgym001` is also an illegal event id.** base32hex is `a-v` and `0-9`;
   `y` is outside `a-v`. **Twenty of the thirty-two fixture ids are illegal** for
   the same reason (`engsync000`, `gym000`). Ids are derived by hashing the
   fixture id — hex is legal base32hex by construction and deterministic, which is
   what makes re-running safe.
3. **botocore defaults to `legacy` retries, not `standard`** — verified at
   runtime. Five attempts, uncapped backoff, up to most of a minute of silence mid
   demo. All four boto3 clients now pass `standard`/3.
4. **A second presigning trap neither of us had:** a presigned URL for a
   non-`us-east-1` bucket is signed for the region but addressed to the global
   host. `curl` follows the 307; a browser re-preflights and fails CORS, saying
   nothing about regions.

### The ruling I need, and what I shipped meanwhile

**`get_calendar_events` returns the overlap set; the fake returns the start set.**
`timeMin` bounds an event's *end* and `timeMax` its *start*, so an event that
began before the window and runs into it comes back. `fake_connectors` filters
`lower <= start < upper`.

Google cannot be asked for start-only filtering, and post-filtering would discard
exactly the events that block time inside the window — which is what the Scheduler
most needs. **So I kept the overlap.** Nothing in the demo straddles a boundary,
so this changes no behaviour today. **My recommendation: change the fake to match,
in both places, at your convenience.** If you would rather I post-filter, it is
three lines and I will do it — but I think the fake is the one that is wrong.

`find_free_slots` also differs: the fake is a hardcoded fixture (07:00 and 12:00
each weekday, ignoring events); mine computes real gaps. Same shape, so nothing
downstream changes.

### The seeder needed two routes the runtime must never have

`events.import`, because `Event.organizer` is *"read-only except when importing"*
and a written organiser is the only way to seed a meeting the demo account does
not own. Without it every seeded event is owned, `reschedule_event` never refuses,
and **the beat where Second declines to move a colleague's meeting has nothing
real behind it.** Import takes no `sendUpdates`, so unlike insert it cannot notify
anyone.

And a `PATCH` that may write `status`, because the dragged-task beat is three
cancelled events and whether `insert` accepts `status='cancelled'` is documented
nowhere I could verify.

So the seeder is wider in exactly three ways, and a test fails if a fourth
appears. **The runtime still cannot insert mail, import an event, or write
status** — that is the claim that the agent cannot fabricate its own evidence,
checked rather than asserted.

### Two things for the owner, both small

1. **`FOUNDER-CHECKLIST.md` C4 should say the OAuth app needs all five scopes
   registered** — you added that at C2, thank you. No further change needed; noting
   only that I verified `settings.get` needs `calendar`/`calendar.readonly`/
   `calendar.settings.readonly`, so the **seeder token genuinely cannot read the
   timezone.** `seed_demo.py` takes `--zone` rather than reading it; running it
   without one is a clean error rather than a 403 on the first insert.
2. **Publish the app before the first `authorize_google.py` run.** The script asks
   and refuses to proceed on "no", stamps the answer next to the token, and
   `--check` makes one live call and tells you to re-run rather than debug a code
   bug if it sees `invalid_grant`.

### Contract published, for AGENTS

Dict keys unchanged from `fake_connectors`. Three notes they may want:

| Tool | Note |
|---|---|
| `get_calendar_events` | `response: "none"` ≠ `"declined"`. `tentative` → `"accepted"` (a maybe is not a refusal). A >200-guest event reads `"none"` even if accepted — Google does not propagate RSVPs at that size; it is logged. |
| `search_gmail` | `date` comes from `internalDate`, not the `Date` header. `snippet` is derived from the body, not Gmail's own, so the fake and the real tool render the same thing. |
| `web_search` | `kind` is inferred from the hostname and defaults to `"article"`. There is no field for it. |

`get_calendar_timezone() -> str | None` — `None` is the normal fall-through, not an
error, and `core/clock.py` already treats it that way.

### Files and footprint

```
$ git status --porcelain     # C:\Users\jivwe\second-connectors, branch connectors
(clean)

$ git log --oneline -3
572ae8d Voice, search, OAuth and the seeder: the package, and three defects in my own code
bcb3896 Calendar and Gmail: six tools, and the hour-eating bug they exist to avoid
952fe1a The single layer, and an allowlist because a denylist cannot be complete

 scripts/authorize_google.py        | 300 +   src/second/voice/__init__.py    |  46 +
 scripts/seed_demo.py               | 550 +   src/second/voice/transcribe.py  | 292 +
 src/second/tools/_google.py        | 853 +   src/second/voice/upload.py      | 229 +
 src/second/tools/calendar_tools.py | 637 +   tests/connectors/prove_rails.py | 393 +
 src/second/tools/gmail_tools.py    | 327 +   tests/connectors/test_*.py      |2950 +
 src/second/tools/search_tools.py   | 236 +
 18 files changed, 6812 insertions(+)
```

**Suite: 345 passed, 0 skipped** (131 platform, 214 connectors). No typechecker,
by your ruling. Nothing outside my paths was touched; `pyproject.toml` and
`uv.lock` are untouched, which is why `web_search` calls the REST API directly.

### What I did not build

Nothing from the brief. Credentials still do not exist — `aws sts
get-caller-identity` fails and there is no `client_secret*.json` — so **every line
of this is tested against fixtures and `moto`, and none of it has made a live
call.** The first real run is the risk I cannot retire from here. `--smoke` on the
seeder and `--check` on the OAuth script exist so that first run is one event, one
message, and one read rather than sixty writes.

---

## CTO - turn 2 · 2026-09-11T09:30Z
**verdict:** approved and merged. I ran `prove_rails.py` myself - 21 rails, each RED then GREEN. Your window ruling is right and I changed the fake.
**phase:** done - standing by for credentials

**486 green on my machine**, and I ran your rails proof rather than taking it on
trust:

```
$ uv run python tests/connectors/prove_rails.py
  baseline suite: 214 passed
  ... 21 rails, each watched failing and then passing
  restored suite: 214 passed
```

**That file is the single most valuable artefact in this repository.** Not because
of the rails - because of the reasons attached to each. *"an inclusion list
instead of an exclusion list books the user over their own flight, because
fromGmail events are the bookings Google creates from confirmation emails"* is the
kind of thing that is invisible until it happens to somebody. Point a judge at it.

### The ruling you asked for: overlap, and the fake was wrong

**Confirmed and changed.** `timeMin` bounds an event's end and `timeMax` its start,
so an event running into the window comes back - and those are exactly the events
that block time inside it, which is what the Scheduler most needs. Post-filtering
would discard precisely the contention it exists to detect.

`fake_connectors.get_calendar_events` now filters on overlap. **Your tool was
right and my fake was wrong**, which is the correct direction for that
disagreement to resolve.

`find_free_slots` differing is fine: same shape, and a fixture that ignores events
is honest about being a fixture.

### The three defects you found in your own code

The forwarded-`.eml` leak is the one I want on the record. **Somebody else's email
becoming part of what Second quotes back as evidence** is a privacy failure
wearing the costume of a MIME-parsing bug, and you found it in an adversarial pass
over code that was already green. That is the standard.

That the other two surfaced from tests written to check something else is worth
naming too. It is the argument for writing the test you think is unnecessary.

### Your four corrections, all taken

1. **Presigning: my fix was backwards and would have caused the failure it was
   meant to prevent.** Signing a bare `audio/webm` guarantees the
   `SignatureDoesNotMatch` 403, because `fetch` sends `blob.type` which
   MediaRecorder makes `audio/webm;codecs=opus`. Not signing it at all is correct,
   and `presigned_put()` refusing any URL that signs it is better than a comment.
2. **`seedgym001` is illegal base32hex** - `y` is outside `a-v`. My example was
   wrong in the same breath as explaining the rule, and twenty of thirty-two
   fixture ids shared the fault. Hashing is the right fix.
3. **botocore defaults to `legacy` retries, not `standard`.** Verified at runtime
   by you; I asserted otherwise from memory.
4. **The cross-region presigned-URL trap** neither of us had. Noted.

### The seeder's three extra routes: approved, and the reasoning is right

`events.import` is the only way to write `Event.organizer`, and without a genuinely
foreign event **the beat where Second declines to move a colleague's meeting has
nothing real behind it** - it would be a refusal with no subject. A test failing
if a fourth route appears is what makes "the runtime cannot fabricate its own
evidence" a checked claim rather than a slogan.

The `--zone` flag instead of reading the timezone with a token that provably
cannot read it is exactly the right shape.

### Six defects in PLATFORM this round, and where they came from

For the record, because the pattern matters: **every one of the six defects I
fixed this round was found by an instance, not by me and not by a test.** The
evidence rule enforced in one place of four, a docstring claiming isolation the
wiring did not deliver, a reason discarded on the happy path, a check-in that
could never appear, a silence state that was unreachable, and a fake whose window
disagreed with the thing it stood in for.

Three of those were claims in my files that were stronger than the truth. That is
the failure mode to keep hunting.

### What remains, and none of it is yours

No credentials exist, so not one line of your 6,812 has made a live call. Your
`--smoke` and `--check` flags are the right answer to that and I am glad they are
there. When the owner finishes the Google console work, the order is: `--check`,
then `--smoke`, then the full seed, and I will run them with you rather than at
you.

---

## CONNECTORS — turn 3 · 2026-09-11T11:20Z
**asks:** one fixture fix that is yours, one line. Nothing blocks on it.
**phase:** done — one handoff, and a process slip of mine to report

You said nothing was needed from me. I verified the merge anyway, because my
package landed alongside two other branches plus your own fixes and "the rails
held on my branch" is not the same claim as "the rails hold on main". **They hold:
509 green, 21 rails RED-then-GREEN on merged main.** The fake's window now matches
the real tool exactly.

Then the verification found something.

### The seeded calendar is empty on the demo day

The check-in fix added yesterday slots to `living_graph()`. `calendar_events()`
did not gain matching entries, and the Eng sync series still stops the day before
`TODAY`:

```
GRAPH  2026-09-09 08:00  t-recording        CAL  2026-09-09 18:00  Eng sync
GRAPH  2026-09-09 18:00  t-gym              CAL  (nothing at all on 2026-09-10)
GRAPH  2026-09-10 08:00  t-recording
GRAPH  2026-09-10 17:00  t-pitch
GRAPH  2026-09-10 18:00  t-gym
```

**The graph plans three blocks on the demo day and the seeded calendar has no
events that day.** So `get_calendar_events` returns `[]`, `find_free_slots`
reports the whole working window free, and **18:00 on the day being shown is
genuinely empty** — which makes "6pm always loses to meetings" true of the history
and false of the day on stage. If a judge asks what is blocking 6pm today, the
honest answer is nothing.

**The fixture contradicts itself in writing.** The seeded inbox carries:

> *"the engineering sync moves to 18:00 daily so we overlap with the US team. It is
> a standing invite, no need to reply."*

Dated 2026-08-18, and the calendar stops providing it on 09-09.

**Fix: extend the Eng sync series through `TODAY`.** `demo_scenario.py` is yours,
so I have not touched it. `_weekdays_in_history()` returns offsets 0–20 and `TODAY`
is offset 21.

**Why this is worth a line of your time rather than a shrug:** yesterday's 18:00
Eng sync is what lets the Observer cite real evidence for the gym slip in the
check-in. Today has no equivalent, so the Adapter's move-to-07:00 is justified by
history alone on the one day anybody is watching.

### What I did about it in my own file

`seed_demo.py --verify` now refuses to call a seed verified when a day the graph
plans work on has **no** seeded events at all. That is the last place this could
have been caught before a judge caught it, and it is mine.

**Deliberately not a per-slot check.** A scheduled slot with no event on it is the
fourth beat — the honest unknown, where Second must admit it cannot tell. That is
wanted. A whole empty day is different: there is no evidence of any kind to reason
from. Bounded to the two days actually *observed*, yesterday and today; my first
version flagged future days too and fired on every correct fixture until I
narrowed it.

`test_the_current_fixture_leaves_the_demo_day_empty` pins the gap so it is a
visible failure rather than a surprise. **It is written to fail the moment you
extend the series, and its docstring says to delete it then.** A test that outlives
the thing it pins is a future false alarm.

### A process slip, mine

I found this while verifying in `MySecond` and **edited `scripts/seed_demo.py` and
`tests/connectors/test_seed.py` in your working tree** before thinking about which
tree I was in. Your uncommitted work on `models.py`, `graphs/service.py` and
`persistence/serde.py` was sitting there at the time.

I restored only my two paths — `git restore --source=HEAD -- <those two>` — moved
them to my worktree, and checked `git status` before and after. **Your three files
were not touched**, and the only thing in your tree from me now is this turn.

Reporting it rather than quietly tidying it, because "I was careful about it" is
not a control and you should know the tree was shared.

### Footprint

```
$ git log --oneline -2        # branch connectors, rebased onto main
d153811 Teach --verify to catch a day the graph plans and the calendar does not cover
dcd4881 Merge SURFACES: four screens, the audit panel, the type layer, nine routes

$ git status --porcelain
(clean)
```

Rebased onto main across six commits, then **re-verified rather than assumed**:
509 passed (133 platform, 216 connectors, 139 agents, 21 api), 21 rails
RED-then-GREEN, `uv sync` re-run after SURFACES' dependency changes.

### Still the only risk in my domain

No credentials, so none of this has made a live call. Order when the Google
console work lands, and I will be here for it:

```
1. authorize_google.py --role runtime --check      one read, proves the token
2. authorize_google.py --role seeder  --check      one read, proves the split
3. seed_demo.py --zone <IANA> --smoke --apply      one import, one cancel, one message
4. seed_demo.py --zone <IANA> --apply              the full 32 + 5, then --verify
```

Step 3 before step 4 is the whole point: a bad id, a bad body or a missing scope
fails identically on the first write and on the thirty-second.

---
WAITING ON: CTO — extend the Eng sync series through TODAY in demo_scenario (one line, yours), then merge d153811. Nothing else from me until credentials exist.
