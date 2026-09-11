"""First contact with a real model. Run: uv run python scripts/live_check.py

Everything in this build has been proved against a scripted model, which was the
right way to build it and proves nothing about whether a real model can do the
job. This is the smallest script that answers the one question the architecture
rests on: **can the provider be forced into our typed output, with our schemas.**

Strands produces structured output as a *forced* tool call. If a provider cannot
be made to call a named tool, or rejects our schema when forced, every routing
decision in the Daily graph breaks. Google's own docs warn that forced mode may
reject deeply nested schemas, and ``ExtractionResult`` nests three levels.

So: the flat model first, then the deep one. If the deep one fails, the fix is in
our model definitions, not the provider.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
warnings.filterwarnings("ignore")

from strands import Agent  # noqa: E402
from strands.tools.structured_output.structured_output_utils import (  # noqa: E402
    convert_pydantic_to_tool_spec,
)

from second.core.models import Diagnosis, ExtractionResult  # noqa: E402
from second.graphs.composition import build_model  # noqa: E402


def probe(label: str, model_cls, prompt: str, system: str) -> bool:
    """Force one typed output out of a live model and report honestly."""
    spec = convert_pydantic_to_tool_spec(model_cls)
    print(f"\n=== {label} === schema {len(json.dumps(spec))}B")
    try:
        agent = Agent(
            model=build_model(),
            structured_output_model=model_cls,
            callback_handler=None,
            system_prompt=system,
        )
        result = agent(prompt)
    except Exception as error:  # noqa: BLE001 - this script exists to report failures
        print(f"  RAISED {type(error).__name__}: {str(error)[:220]}")
        return False

    typed = result.structured_output
    if typed is None:
        print(f"  NO TYPED OUTPUT. stop_reason={result.stop_reason}")
        return False

    print(f"  OK  stop_reason={result.stop_reason}")
    for field, value in typed.model_dump().items():
        rendered = str(value)
        print(f"    {field:24s} {rendered[:88]}")
    return True


def main() -> int:
    model = build_model()
    print(f"provider: {type(model).__name__} | {model.get_config().get('model_id')}")

    flat = probe(
        "Diagnosis -- flat, and it carries the routing decision",
        Diagnosis,
        "Task t-gym. The 18:00 gym slot was declined on 4 of 5 weekdays. Each of "
        "those days had 'Eng sync' at 18:00, 9 attendees, organised by someone else.",
        "You classify why a task slipped, structurally. Never guess at motivation. "
        "Quote the evidence, or leave evidence null if nothing supports a cause.",
    )

    deep = probe(
        "ExtractionResult -- nested three levels",
        ExtractionResult,
        "I want to get comfortable speaking to a room this year. And longer term, "
        "I want to build a company that outlives me.",
        "Extract distinct goals from speech. Emit shallow goals with no routes. "
        "Set horizon honestly: 'year' for this year, 'life' for a lifetime ambition.",
    )

    honest = probe(
        "Diagnosis -- nothing to cite. THE test.",
        Diagnosis,
        "Task t-recording. The 08:00 slot was free and uncontested on all three "
        "days it was missed. No conflicting event. No dependency. No email about it.",
        "You classify why a task slipped, structurally. If nothing in the evidence "
        "supports a cause, set blocker_type UNKNOWN, leave evidence null, and say so. "
        "Never invent a quote.",
    )

    print("\n" + "=" * 60)
    print(f"flat schema forced      : {'PASS' if flat else 'FAIL'}")
    print(f"deep schema forced      : {'PASS' if deep else 'FAIL'}")
    print(f"admits it cannot tell   : {'PASS' if honest else 'FAIL'}")
    return 0 if (flat and deep and honest) else 1


if __name__ == "__main__":
    raise SystemExit(main())
