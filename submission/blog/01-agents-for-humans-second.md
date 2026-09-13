# Agents for Humans: building Second, an agent that stays quiet until it has evidence

Saying a goal out loud is easy. The hard part is the Tuesday when the gym session loses to a meeting and nobody notices.

I built Second for the Agents for Humans hackathon to work on that gap. You say your goals out loud. Second builds a ladder of goals from lifetime down to this week, plans a route for each and schedules the work into your calendar. Each morning it checks what actually happened. When something slipped, it explains why with a quoted calendar entry or email, or says it cannot tell. Then it adapts the plan and prepares the next step up to the last click. It will draft the email. It will not send it.

I built it alone between 10 and 14 September 2026 on the Strands Agents SDK, with Claude Code as my coding assistant.

## The rule everything follows

One sentence settles most design questions in the codebase: "Second does everything it can do without you, then hands you the smallest possible piece."

If Second can fix a slip on its own, it does. If the decision is yours, or it cannot work out what went wrong, it asks one question. When nothing needs your attention, the day still shows its plan, but nothing is sent to you. An agent that always has an explanation for a missed task is inventing some of them, so "I can't tell" has to be a valid answer.

## Three Strands graphs

Second is three `GraphBuilder` graphs.

**Intake** turns speech into a plan: Extractor, Cascader, Route Planner, Scheduler, Resource Finder. The edge out of the Extractor only fires when the goals are clear.

**Daily** is the product. The Observer reads the calendar and inbox, the Diagnostician decides why a task slipped, and the run then either acts or asks.

**Feedback** takes what you say back and the Interpreter hands typed updates to the Graph Updater.

All three share one audit hook on the graph and every agent, a `RunawayGuard` that caps model calls per node, and run-wide state under one namespace in `invocation_state`.

## Interrupting you is a typed field

The Diagnostician returns a Pydantic `Diagnosis`. Strands produces structured output by forcing a tool call, so the result is a typed object and the graph routes on its fields. From `src/second/graphs/daily.py`:

```python
    builder.add_edge("observer", "diagnostician")

    # The branch. Strict complements of one predicate, because sibling edges are
    # independent OR-gates -- if both were true, both nodes would run.
    builder.add_edge("diagnostician", "adapter", condition=can_act_alone)
    builder.add_edge("diagnostician", "communicator", condition=needs_user_decision)

    builder.add_edge("adapter", "preparer")
    builder.add_edge("preparer", "communicator")
```

`needs_user_decision` is true when the Diagnostician says the decision is yours, when its confidence is below a floor, when the blocker is `UNKNOWN`, or when there is no typed result at all. `can_act_alone` is literally `not needs_user_decision(state)`. Sibling edges are evaluated independently, so two hand-written conditions that drifted apart could run both nodes at once.

Evidence is enforced in the type too. In `src/second/core/models.py`, a `Diagnosis` with empty evidence has its blocker set to `UNKNOWN`, confidence capped at 0.3 and `requires_user_decision` set to true. I coerce it on purpose instead of raising a validation error: a rejected structured output goes back to the model to retry, and the cheapest way out of that loop is to make up a quote.

Second also refuses Strands providers that accept a forced tool choice and silently drop it: mistral, ollama, llamacpp, llamaapi, writer and sagemaker.

## Each agent gets only the tools its job needs

Every agent module declares `REQUIRED_TOOLS`, and `assert_privileges` checks the list when a graph is built. The Observer reads raw calendar and email. The Diagnostician has `read_graph` and `record_diagnosis` and never sees the inbox. The Adapter can reschedule an event and adapt a single task, but has no tool that rewrites a whole goal, so it cannot erase the history of what slipped. The Communicator, which writes the words you read, has no tools.

Below the agents: no tool in Second can send email, none can delete a calendar event, and `reschedule_event` refuses events you do not own.

## What live runs taught me

I planned to run on Amazon Bedrock. On 10 September, in CloudShell, Bedrock refused Anthropic models for my account's country (Nigeria): "Access to Anthropic models is not allowed from unsupported countries, regions, or territories." The Bedrock quotas also showed 0.0.

I moved to the Gemini free tier and confirmed forced tool choice works there. Its per-model limits, 5 requests a minute and 20 a day, meant one model per node. Seven end-to-end Daily runs completed on Gemini, against fake calendar and inbox connectors and an in-process DynamoDB from moto. The Diagnostician cited the evidence I had planted, a gym session declined on 4 of 5 weekdays against a 9-attendee "Eng sync" the user does not own, and returned `UNKNOWN` for the slip nothing explained.

Those runs found real bugs. The retry ladder ignored the delay Gemini asked for; `ResilientRetry` now honours it, gives up when the wait means the daily allowance is gone, and switches model when a refusal names the model. The Adapter ran out of output tokens retyping a whole goal to move one task, which is why `adapt_task` exists. Audit rows said FAILED without a reason; that is fixed.

The offline suite has more than 700 tests, and I broke each safety guard on purpose to confirm a test fails.

## The AWS side

Implemented in code:

- The Living Graph is a DynamoDB single table. Each write is conditional on a version number, so a concurrent run gets a `VersionConflict` instead of overwriting. Tested with moto.
- Voice goes to S3 through a presigned upload, and Amazon Transcribe produces the transcript Intake reads.
- The deployed Google refresh token is read from Secrets Manager.
- EventBridge Scheduler triggers a Lambda shim that starts runs. `deploy/iam-policy.json` holds the IAM policy and `scripts/bootstrap_aws.py` creates the table and bucket.

`app.py` is the Bedrock AgentCore runtime entrypoint, running the same service layer as the local app. Its payload guard refuses any prompt that is not a string. The runtime hands over the request body as parsed JSON of any type, and a structured content block naming a tool, passed through in place of a prompt, could run as a tool call before the model reasons about it. For an agent that drafts mail and moves calendar entries, that is an authorization hole.

Where this stands: AgentCore is not deployed yet, and the DynamoDB table and S3 bucket are not created. The Google OAuth app is not published, so Second has not read a real calendar or inbox; the live runs used fake connectors.

The code is MIT licensed at https://github.com/oghenejivwe/second.
