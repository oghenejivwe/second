# Second: Devpost submission

## Project name

Second

## Tagline

Say your goals out loud. Second plans them into your calendar, checks each morning what really happened, fixes what it can and hands you the smallest piece.

## Track

Everyday Agents

## The problem

You can plan a good week on Sunday and lose it by Wednesday. A recurring meeting lands on the gym slot, an errand eats the study hour, and nothing says why. Calendars store events and to-do apps store tasks. Neither compares the plan with what happened, or tells a session lost to someone else's meeting from one you skipped. So people diagnose it alone, decide they lack discipline, and the plan dies quietly.

## Who it's for

People running several long-term goals at once (a side business, a certification, a race, a move abroad) who keep losing the week to meetings, errands and drift. They already live in a calendar and an inbox, so Second reads those and nobody has to log progress.

## What it does

You say your goals out loud. Second builds a ladder of goals from lifetime down to this week, plans a route for each, and schedules the work into your calendar. If it is too vague to plan on, it asks.

Each morning it checks what actually happened. It explains each slip with quoted evidence, or says it cannot tell and asks you. When it can fix the problem alone, it adapts the plan and prepares the next step up to the last click: it drafts the email and never sends it. Most mornings nothing needs you, and it stays quiet. The founder's rule: "Second does everything it can do without you, then hands you the smallest possible piece."

The web app has six screens: Record, Living Graph, Today, Schedule, Memory and Goals. Schedule shows seven days of placed blocks and proposals labelled as not in your calendar, and refuses slots you keep abandoning. Memory quotes evidence from your calendar, email and plan, and says whether each source could be read. Every two days Second asks what you want done this week, and every three days what you want this month, each with "by when?"; the answer is planned like anything else you say.

## How it works

Three Strands graphs share one DynamoDB store, the Living Graph, holding goals, routes, tasks and slip history.

- Intake: Extractor → Cascader → Route Planner → Scheduler → Resource Finder. Its first edge fires only when the goals are clear.
- Daily: Observer → Diagnostician. If Second can act alone: Adapter → Preparer → Communicator. If the decision is yours: straight to the Communicator.
- Feedback: Interpreter → Graph Updater.

Interrupting you is the most expensive call Second makes, so it is a typed field. The Diagnostician returns a Pydantic `Diagnosis`, and the conditional edge reads `requires_user_decision`, `confidence` and `blocker_type`. Second asks when the model says to, when confidence is below a floor, when the blocker is `UNKNOWN`, or when no typed result exists. No natural language is parsed to decide. The act-alone edge is the exact negation, because sibling edges in a Strands graph are independent and could otherwise both fire. A diagnosis with no evidence is coerced to `UNKNOWN` by the data model.

## How it uses Strands Agents

- Three `GraphBuilder` graphs with conditional edges on typed structured-output fields (`src/second/graphs/`).
- Structured output on every node. Strands forces a tool call for it, so providers that silently discard a forced tool choice (mistral, ollama, llamacpp, llamaapi, writer, sagemaker) are refused when the model is built.
- One audit hook on the graph and every agent, recording node spans and tool calls, refused calls included.
- `RunawayGuard` caps model calls per node.
- `ResilientRetry` honours a provider's stated delay, gives up when the wait means a daily allowance is gone, and switches model when a refusal names the model.
- Run-wide state under one namespace in `invocation_state`.

## Least privilege

Every agent declares its tools, and `assert_privileges` enforces it when a graph is built. The Diagnostician never reads raw calendar or email. The Communicator has no tools. The Adapter cannot rewrite a whole goal, so it cannot erase slip history. No tool can send email or delete a calendar event, and `reschedule_event` refuses events the user does not own. The README has the full per-agent table.

## AWS

Implemented in code: a DynamoDB single-table store with optimistic locking (tested with moto), voice through S3 presigned upload and Amazon Transcribe, Secrets Manager for the Google refresh token, a Bedrock AgentCore entrypoint that refuses non-string prompts, an EventBridge Scheduler to Lambda morning trigger, an IAM policy, and a script that creates the table and bucket.

Not done as of 13 September 2026: AgentCore is not deployed and the table and bucket do not exist yet. The Google OAuth app is unpublished, so Second has not read a real calendar or inbox.

## Challenges we ran into

Bedrock refused Anthropic models for this account's country ("Access to Anthropic models is not allowed from unsupported countries, regions, or territories") and every quota read 0.0. We moved to the Gemini free tier.

That tier allows 5 requests per minute and 20 per day, each counted per model. Five Daily nodes on one model died at the Diagnostician, so each node got its own model. Gemini then said to retry in 40 seconds, and our retry ladder tried after 2 and 4 and gave up. It now waits the stated delay. A refusal saying the model is "experiencing high demand" now switches model.

Some Strands providers accept a forced tool choice and drop it with only a warning. The Daily graph would then route on a field the model never had to fill, with no error. We refuse those providers.

The Adapter hit `MaxTokensReachedException` retyping a whole goal to change three fields. A shorter partial goal that validated would have erased slip history. Its `write_graph` became `adapt_task`, which only accepts what an adaptation may change.

Some checks could not fail. One test claimed the audit kept a failure's cause but only asserted the failure, and live rows said FAILED with no reason. The live script printed "ok" whenever `adapt_task` returned; it now reads the store back. Safety guards are now broken on purpose to confirm a test goes red.

## Accomplishments that we're proud of

Seven end-to-end Daily runs completed on Gemini, with fake calendar and inbox connectors and an in-process DynamoDB. The planted gym session was declined on 4 of 5 weekdays against a nine-attendee "Eng sync" the user does not own, and the Diagnostician quoted that evidence. For the slip nothing explained, it returned `UNKNOWN` and asked. One founder built it in five days, with more than 700 offline tests.

## What we learned

Forced tool choice changes what a required field means. While `evidence` was required, a model with nothing to cite still had to write something, and the easy thing to write is a real quote attached to the wrong conclusion. Making it nullable and coercing to `UNKNOWN` fixed that.

Prompts and OAuth scopes make weak rails (`gmail.compose` also grants send). The limits have to live in the tools.

## What's next

Publish the OAuth app and run on a real calendar. Create the AWS resources, deploy to AgentCore and start the morning schedule. Verify forced tool choice on Groq.

## Built with

Python, Strands Agents SDK, Amazon Bedrock AgentCore, Amazon DynamoDB, Amazon S3, Amazon Transcribe, AWS Secrets Manager, Amazon EventBridge Scheduler, AWS Lambda, Google Gemini API, Google Calendar API, Gmail API, Tavily Search API, FastAPI, Pydantic, pytest, moto, TypeScript, React, React Flow, Zustand, Vite, Vercel

## Try it

Repository: https://github.com/oghenejivwe/second (MIT licence)

Architecture diagram: `docs/architecture.svg` in the repository. Dashed boxes are built but not deployed or connected yet.

With Node 24, from the repository root:

```
cd web
npm ci
npm run dev
```

Open http://localhost:5173. The screens run on example data generated by the real graphs with a scripted model, labelled "fixtures" on screen. For the offline tests, with uv and Python 3.12: `uv sync`, then `uv run pytest -q`.

Hosted demo, no install or login: https://second-blush-ten.vercel.app. It runs the same example data, labelled "fixtures" on screen.

## Disclosure

Built during the submission period, 10 to 14 September 2026, by Patrick Oghenejivwe with an AI coding assistant, Claude Code. Commits carry "Co-Authored-By: Claude" lines; the first is dated 10 September 2026. There is no pre-existing project code, only open-source libraries.

Third-party APIs: Google Gemini (free tier), Google Calendar and Gmail (OAuth, not yet authorised on a real account), Tavily Search, and the AWS services above. Google's terms for the free Gemini tier allow human review of API input and output. The live calls so far sent only synthetic data: the fake demo world and hand-written test prompts.
