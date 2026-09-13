# Agents for Humans: the bugs only a live model found, and the guardrails they became

I built Second in five days for the Agents for Humans Hackathon. It is a personal execution agent. You say your goals out loud; it breaks them down to this week, puts the work in your calendar, checks each morning what actually happened, and prepares the next step up to the last click. It drafts email and never sends it.

For the first day and a half, every agent talked to a scripted model that does what the test says. A real model does whatever the schema, the tools and the token limit allow.

I wanted Amazon Bedrock, but Bedrock refused Anthropic models for my account's country, and every Bedrock quota I checked showed 0.0. So these live runs were on the Gemini free tier, with fake calendar and inbox connectors and DynamoDB in process under moto. The agents are Strands Agents SDK agents in three GraphBuilder graphs.

## No evidence, no diagnosis

When a task slips, the Diagnostician has to say why and quote the calendar entry or email that shows it. If nothing explains the slip, the honest answer is "I can't tell."

Strands produces structured output by forcing a tool call, so the model cannot decline to answer. My first instinct was a validator that rejects a Diagnosis with empty evidence. Then I looked at where a rejection goes. A validation error returns to the model as an error tool result, and nothing caps how many times that loop runs. The cheapest way out is to put something in the evidence field, and an invented quote validates.

So the validator downgrades instead of raising. From `src/second/core/models.py`:

```python
if not (self.evidence or "").strip():
    self.blocker_type = "UNKNOWN"
    self.confidence = min(self.confidence, 0.3)
    self.requires_user_decision = True
return self
```

An UNKNOWN diagnosis follows a conditional edge to the Communicator, which asks the user. The evidence field is nullable on purpose, to give the model somewhere honest to land.

On the first live run, given a task that slipped into empty slots with no conflict and no email, Gemini returned UNKNOWN, null evidence, confidence 0.0. Across the seven end-to-end Daily runs that followed, the Diagnostician cited the evidence I had planted (a gym session declined on 4 of 5 weekdays against a 9-attendee "Eng sync" the user does not own) and still said UNKNOWN for the slip nothing explained.

## The Adapter ran out of tokens

The first full live Daily run died at the Adapter with `MaxTokensReachedException`. Its prompt told it to read the whole goal and write the whole goal back, to change three fields. A goal with eight slots and four slip records did not fit in an 8192-token completion. It truncated mid-object twice before an attempt fit.

The crash was the lucky outcome. `write_graph` upserts by id, so a shorter object that still validates replaces the whole goal and erases the slip history the next diagnosis depends on. I had warned against that in the prompt, and a prompt is only a request.

The fix was a new tool, `adapt_task`, with parameters for the four things an adaptation may change: task title, upcoming slots, route cadence and route rationale. Slips, status, dependencies and deadline have no parameter, so the Adapter has no way to touch them. `future_slots` replaces only slots from today onwards, and a reason is required and recorded. The Adapter lost `write_graph`, and `assert_privileges` refuses to build a graph where an agent holds a tool outside its declared list.

## FAILED, with no reason

The run also logged three `write_graph` calls from the Adapter, two marked FAILED. I could not tell whether they were lost optimistic-lock races or patches the model built wrong, and those need opposite fixes.

The audit hook, one Strands hook provider registered on the graph and every agent, saw the exception and kept only the fact that there was one. Its test had a docstring saying the audit keeps the cause, and asserted only that `failed` was true. A failed row now carries the exception type and message.

## A check that could not fail

Before walking the Google setup, I had AI agents audit it. The worst finding: `authorize_google.py --role runtime --check` proved the token worked by asking for the calendar time zone. That function deliberately swallows every exception and returns None. The check printed "live call OK. Calendar timezone: None" and exited 0 on a dead token. It now makes calls that raise, against both Calendar and Gmail.

That path has still not been walked. The OAuth app is not published, no token exists, and Second has not read a real calendar or inbox.

## Breaking the guards on purpose

For each guard, I broke the code and watched a test go red. Disabling `_no_evidence_means_unknown` let a confident diagnosis with null evidence reach the Adapter. Letting the brief honour the Communicator's `notify` flag as given stopped a raised decision and a prepared draft from reaching the user. `adapt_task` got four mutations, including replacing all slots instead of upcoming ones and dropping the reason requirement.

The FAILED-row test is why I do this. It looked correct and checked nothing.

## Someone else's meeting

`reschedule_event` reads the event first and refuses if the user is not its organiser. A refused move is a line in a log. A moved meeting is an apology to eight colleagues.

The web app's audit panel shows the refusal. The demo data comes from running the real graphs and audit hook with a scripted model and fake connectors. The Adapter moves the gym session to 07:00, then tries to move the Eng sync. That row is marked failed, and its reason says the event belongs to someone else and will not be moved. No tool exists to send email or delete a calendar event.

## Where AWS fits

Several nodes write to the Living Graph in one Daily run, and it is a single DynamoDB item per user. Every write is conditional on a version number. If the Observer updates the person model while the Adapter is mid-change, the Adapter's write fails the condition, re-reads and re-applies, and the Observer's update survives. The retry is tested with moto against a second writer that wins the race.

Voice goes through an S3 presigned upload to Amazon Transcribe, and there is a Bedrock AgentCore entrypoint and an EventBridge Scheduler to Lambda trigger for the morning run. None of it is deployed yet: the table and bucket do not exist, AgentCore is not running, and everything above ran on my machine.

The code, tests and commit history are at https://github.com/oghenejivwe/second
