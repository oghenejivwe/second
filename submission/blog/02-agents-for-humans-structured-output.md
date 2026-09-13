# Agents for Humans: when Bedrock said no, and what free-tier models taught me about Strands structured output

I built Second for the Agents for Humans hackathon between 10 and 14 September 2026, working alone from Nigeria with Claude Code as my coding assistant. Second is a personal execution agent. You say your goals out loud, it breaks them into a ladder from lifetime down to this week, schedules the work into your calendar, and each morning checks what actually happened. It runs on three Strands `GraphBuilder` graphs, and the conditional edges in those graphs route on typed fields that come back as structured output.

## Bedrock said no

My plan was Claude on Amazon Bedrock. On 10 September I made a call from CloudShell and got this, on a current Claude model and on one two years old:

```
ValidationException: Access to Anthropic models is not allowed from
unsupported countries, regions, or territories.
```

My AWS account is registered in Nigeria, which is on Anthropic's own supported-countries list for its API. So AWS applies a narrower list to Anthropic models on Bedrock than Anthropic applies to itself. Every Bedrock quota I looked at read 0.0.

Second picks its provider from one environment variable, and the Bedrock route stays wired for the day the block lifts. I needed a model I could call for free.

## Why most cheap models were out

Strands produces structured output through a forced tool call. The agent gets a tool whose input schema is my Pydantic model, and the provider is told a tool call is mandatory. If the provider obeys, I get a typed `Diagnosis` back. If it doesn't, I get prose.

Second's Daily graph runs Observer, then Diagnostician, then branches: to the Adapter when the Diagnostician can act alone, to the Communicator when the decision belongs to the user. Those edges read a field on the Diagnostician's output. A model that answers in prose raises no error. The graph just routes on a field nothing filled in.

## Six providers that take the instruction and drop it

I searched the installed Strands SDK for how each model provider handles `tool_choice`. Six of them (`mistral`, `ollama`, `llamacpp`, `llamaapi`, `writer` and `sagemaker`) call `warn_on_tool_choice_not_supported` and then discard the tool choice. You get a Python warning and nothing else.

It looks like the obvious path: `strands-agents[mistral]` plus `MistralModel(...)` runs cleanly while every structured output silently stops being forced.

So Second refuses those six when the model is built: `build_model()` raises `ModelProviderNotConfigured` and says the provider discards forced tool choice. OpenAI-compatible services, Mistral's own API and Groq among them, go through Strands' `openai` provider instead, which honours it. One test asserts all six are refused. Another scans the installed SDK and fails if the set of discarding providers changes, so an upgrade that fixes one shows up in the test run.

## Probing a provider adversarially

The SDK passing the parameter along proves nothing about the service on the other end, which can accept `tool_choice="required"` and ignore it. So I wrote `scripts/probe_provider.py` to test any OpenAI-compatible endpoint.

After a plain call to check the key and region access, the second check is adversarial. It sends `tool_choice="required"`, the exact literal Strands sends, with a prompt telling the model to reply "hello" and not to call any tool under any circumstances. A provider that really forces the call returns one anyway; one that merely accepts the parameter returns prose. The third check sends one of Second's real nested schemas, built with Strands' own tool-spec converter, and checks that the arguments parse.

## Gemini's free tier, one model per node

Gemini is free without a card and available in Nigeria. Strands' Gemini provider maps a forced tool choice to function-calling mode `ANY`, and forced tool choice held up when I tested it live.

The catch is the quota, counted per model: the 429 names the model inside `quotaDimensions`. I learned that by running the Daily graph and watching it die at the Diagnostician. The free tier allows 5 requests a minute, and the same evening's errors showed a harder cap of 20 requests a day per model. Five nodes on one model share those requests, and the graph can't finish. So `GEMINI_NODE_MODELS` assigns every node a model, with the five Daily nodes on five different ones. It's slow. It finishes.

## Listening to the provider

Strands' default retry strategy retries `ModelThrottledException`, which Bedrock raises. Gemini raises `ClientError` for a 429 and `ServerError` for a 503, so a transient refusal killed the run. I wrote `ResilientRetry`, a subclass of Strands' `ModelRetryStrategy` that decides from status codes and message text instead of exception types.

The second live run still died. Gemini had said "Please retry in 40.513907697s". My fixed ladder retried after 2 seconds, then 4, then gave up 34 seconds before the window reopened. Now the provider's number wins:

```python
        stated = _stated_delay(self._last_exception)
        if stated is None:
            return super()._calculate_delay(attempt)

        honoured = min(math.ceil(stated) + 1, math.ceil(self._patience))
```

A per-minute window asks for about 40 seconds; an exhausted daily allowance asks for hours. Past 65 seconds the strategy stops waiting, because sleeping through a day is a hang. It moves to another model if one is left, and gives up if not.

The third run got past the quota and died on "This model is currently experiencing high demand." That sentence is about one model, and other models in the same map were idle. When a refusal names the model, `ResilientRetry` calls `update_config(model_id=...)` on the agent's model, moves to the next of up to three alternates, and retries after a second. A model that refused is not tried again.

I broke these guards on purpose and confirmed the tests meant to catch them failed. After the fixes, seven end-to-end Daily runs completed on Gemini, using fake calendar and inbox connectors and DynamoDB mocked in-process with moto. The Diagnostician quoted the evidence I had planted (a gym session declined on 4 of 5 weekdays against a 9-attendee "Eng sync" the user doesn't own) and returned UNKNOWN for the slip nothing explained.

## Where AWS still fits

The model moved off Bedrock. The rest of Second's AWS design stayed. The Living Graph is one DynamoDB item per user, and every write is conditional on a version number, so two nodes writing in the same run get a conflict instead of a silent overwrite. That is tested with moto. Voice goes to S3 through a presigned upload, and Amazon Transcribe produces the text Intake reads. A deployed run reads the Google refresh token from Secrets Manager. `app.py` is the Bedrock AgentCore runtime entrypoint, and it refuses any prompt that is not a string. For the morning run, EventBridge Scheduler triggers a Lambda shim. `scripts/bootstrap_aws.py` creates the table and bucket, and `deploy/iam-policy.json` holds the IAM policy.

None of it runs on AWS yet. The table and bucket have not been created and AgentCore is not deployed. The live runs above used moto in process.

## What isn't proven yet

Groq restricted my first account at signup, before any API call. A second account worked, but I haven't confirmed that Groq honours forced tool choice, so nothing depends on it yet.

Google's unpaid-tier terms allow human reviewers to read API input and output, so the free-tier runs used synthetic data. No real calendar or inbox has been read yet, and Second's AgentCore entrypoint exists in code but isn't deployed.

If your Strands graph routes on structured output, check that the provider class keeps the forced tool call, then that the service obeys it.

The code is at https://github.com/oghenejivwe/second.
