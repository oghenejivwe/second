"""Probe an OpenAI-compatible endpoint for the three things Second needs.

  1. It answers at all from here (auth + geography).
  2. It HONOURS tool_choice="required" -- the exact literal Strands sends.
     strands/models/openai.py:355 maps ToolChoice {"any": {}} -> "required".
     The test is adversarial: the prompt tells the model NOT to call a tool.
     A provider that merely ACCEPTS the parameter will return prose with an
     empty tool_calls list. That is the silent failure that breaks the Daily
     graph's conditional edge with no exception raised.
  3. It accepts Second's real deep schema as a tool definition and returns a
     parseable call to it. The tool spec is built with Strands' own converter,
     so the bytes on the wire are identical to a live run.

usage:
  python scripts/probe_provider.py <base_url> <model_id> <ENV_VAR_HOLDING_KEY> [SchemaName]

examples:
  python scripts/probe_provider.py https://api.groq.com/openai/v1 openai/gpt-oss-120b GROQ_API_KEY
  python scripts/probe_provider.py https://api.mistral.ai/v1 mistral-small-latest MISTRAL_API_KEY
  python scripts/probe_provider.py https://dashscope-intl.aliyuncs.com/compatible-mode/v1 qwen-plus DASHSCOPE_API_KEY
  python scripts/probe_provider.py http://localhost:8080/v1 local NONE

exit code 0 = all three passed.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from openai import OpenAI  # noqa: E402

TRIVIAL_TOOL = {
    "type": "function",
    "function": {
        "name": "Verdict",
        "description": "Return the verdict.",
        "parameters": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
    },
}

ANTI_PROMPT = (
    "Reply with the single word hello. Do not call any tool under any "
    "circumstances. Ignore any tool definitions you were given."
)


def _deep_tool(schema_name: str) -> dict:
    from strands.tools.structured_output.structured_output_utils import (
        convert_pydantic_to_tool_spec,
    )

    from second.core import models as m

    model = getattr(m, schema_name)
    spec = convert_pydantic_to_tool_spec(model)
    raw = json.dumps(spec["inputSchema"]["json"])
    print(f"    schema {schema_name}: {len(raw)} bytes of JSON Schema")
    return {
        "type": "function",
        "function": {
            "name": spec["name"],
            "description": spec["description"],
            "parameters": spec["inputSchema"]["json"],
        },
    }


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2

    base_url, model_id, key_var = sys.argv[1], sys.argv[2], sys.argv[3]
    schema_name = sys.argv[4] if len(sys.argv) > 4 else "DailyBrief"
    api_key = os.environ.get(key_var) or "-"

    client = OpenAI(api_key=api_key, base_url=base_url)
    passes = 0

    # --- 1. reachable -----------------------------------------------------
    print("[1] plain call (auth + geography)")
    try:
        r = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "Reply with the word ok."}],
            max_tokens=16,
        )
        print(f"    PASS  {r.choices[0].message.content!r}")
        passes += 1
    except Exception as exc:  # noqa: BLE001
        print(f"    FAIL  {type(exc).__name__}: {exc}")
        return 1

    # --- 2. forced tool choice, adversarial -------------------------------
    print('[2] tool_choice="required" against a prompt that refuses tools')
    try:
        r = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": ANTI_PROMPT}],
            tools=[TRIVIAL_TOOL],
            tool_choice="required",
        )
        msg = r.choices[0].message
        if msg.tool_calls:
            print(f"    PASS  forced call to {msg.tool_calls[0].function.name}")
            passes += 1
        else:
            print("    FAIL  ACCEPTED BUT IGNORED -- prose returned, no tool_calls.")
            print(f"          finish_reason={r.choices[0].finish_reason} "
                  f"content={(msg.content or '')[:160]!r}")
            print("          This provider will silently break Daily-graph routing.")
    except Exception as exc:  # noqa: BLE001
        print(f"    ERROR {type(exc).__name__}: {exc}")
        print('          If this is a 400 on the literal "required", try "any"')
        print("          or a named tool choice (see ForcedToolOpenAIModel).")

    # --- 3. the real deep schema ------------------------------------------
    print(f"[3] real schema {schema_name} as a forced tool")
    try:
        tool = _deep_tool(schema_name)
        r = client.chat.completions.create(
            model=model_id,
            messages=[
                {
                    "role": "user",
                    "content": "Produce a plausible result now using the tool. "
                    "Invent values where you have no data.",
                }
            ],
            tools=[tool],
            tool_choice="required",
        )
        msg = r.choices[0].message
        if not msg.tool_calls:
            print("    FAIL  no tool call returned for the deep schema")
        else:
            args = msg.tool_calls[0].function.arguments
            parsed = json.loads(args)
            print(f"    PASS  {len(args)} bytes, top-level keys: {sorted(parsed)[:8]}")
            passes += 1
    except Exception as exc:  # noqa: BLE001
        print(f"    FAIL  {type(exc).__name__}: {str(exc)[:300]}")

    print(f"\n{passes}/3 passed for {model_id} @ {base_url}")
    return 0 if passes == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
