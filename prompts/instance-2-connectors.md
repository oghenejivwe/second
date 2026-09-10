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
  Use `users.drafts.create`. Do not request a send scope. The absence of the
  scope is the second layer; the tool's behaviour is the first.
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
| `tavily-python` | 0.8.1 | web search; swap if the owner's key is for another provider |
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
WAITING ON: CONNECTORS — read `cto.md`, then `prompts/OWNERSHIP-MAP.md`, then your domain, then post your status turn
