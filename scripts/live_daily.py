"""The whole Daily graph against a live model. Run: uv run python scripts/live_daily.py

Real model, real graph, real tools, real DynamoDB semantics. AWS is the only thing
substituted -- moto runs the actual service in-process -- because no credentials
exist yet and the store is not what this is testing.

Everything else is the production path: five agents, the conditional edge, the
audit hook, the runaway guard, and the seeded demo world.

What to watch, in order of importance:

  1. Does the Diagnostician cite real evidence, or invent it?
  2. Does it reach for UNKNOWN when the evidence is thin?
  3. Does the branch route where the diagnosis says it should?
  4. Does the Preparer stop at the last click?
"""

from __future__ import annotations

import asyncio
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
warnings.filterwarnings("ignore")

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

from second.core.clock import Clock  # noqa: E402
from second.core.models import BriefJudgement, Diagnosis, ObservationReport  # noqa: E402
from second.graphs import service  # noqa: E402
from second.graphs.composition import ToolRegistry, build_model  # noqa: E402
from second.graphs.conditions import typed_result  # noqa: E402
from second.graphs.daily import build_daily_graph  # noqa: E402
from second.persistence.store import LivingGraphStore  # noqa: E402
from second.testing import demo_scenario  # noqa: E402
from second.testing.fake_connectors import ALL_FAKE_CONNECTORS  # noqa: E402
from second.tools.graph_tools import ALL_GRAPH_TOOLS  # noqa: E402

USER = demo_scenario.USER_ID


def seeded_store():
    boto3.client("dynamodb", region_name="us-west-2").create_table(
        TableName="second_graph",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table = boto3.resource("dynamodb", region_name="us-west-2").Table("second_graph")
    store = LivingGraphStore(table=table)
    store.save(demo_scenario.living_graph())
    return store


async def main() -> int:
    with mock_aws():
        store = seeded_store()
        service.set_store(store)
        clock = Clock.fixed(demo_scenario.TODAY, zone_name="Europe/London")

        # Deliberately NOT passing a model: each node picks its own, which is the
        # only way the free tier's per-model daily quota adds up to a whole run.
        from second.settings import GEMINI_NODE_MODELS

        print("models  : one per node --")
        for node in ("observer", "diagnostician", "adapter", "preparer", "communicator"):
            print(f"            {node:15s} {GEMINI_NODE_MODELS.get(node)}")
        print(f"date    : {clock.today}  ({clock.name})")
        print("-" * 66)

        before = {
            task.id: (list(task.scheduled_slots), task.slip_count, len(task.slips), task.title)
            for goal in store.load(USER).goals
            for route in goal.routes
            for task in route.tasks
        }

        composed = build_daily_graph(
            store=store,
            user_id=USER,
            clock=clock,
            registry=ToolRegistry([*ALL_GRAPH_TOOLS, *ALL_FAKE_CONNECTORS]),
        )

        try:
            result = await composed.run("Yesterday's plan against what actually happened.")
        except Exception as error:  # noqa: BLE001 - the point is to see what breaks
            print(f"\nGRAPH FAILED: {type(error).__name__}\n  {str(error)[:400]}")
            return 1

        path = [node.node_id for node in result.execution_order]
        print(f"\npath    : {' -> '.join(path)}")

        observed = typed_result(result, "observer", ObservationReport)
        if observed:
            print(f"\nOBSERVER  {len(observed.observations)} observation(s)")
            for item in observed.observations[:6]:
                print(f"  [{item.outcome:9s}] {item.task_id:14s} {item.evidence[:70]}")

        diagnosis = typed_result(result, "diagnostician", Diagnosis)
        if diagnosis:
            print(f"\nDIAGNOSIS {diagnosis.blocker_type}  confidence={diagnosis.confidence}")
            print(f"  task     : {diagnosis.task_id}")
            print(f"  evidence : {diagnosis.evidence or '(null -- nothing supported a cause)'}")
            print(f"  action   : {diagnosis.proposed_action[:90]}")
            print(f"  asks user: {diagnosis.requires_user_decision}")

        judgement = typed_result(result, "communicator", BriefJudgement)
        if judgement:
            print(f"\nCOMMUNICATOR notify={judgement.notify}")
            for reminder in judgement.reminders:
                print(f"  reminder : {reminder.what[:70]}")
                print(f"             cites: {reminder.evidence[:60]}")
            for decision in judgement.decisions:
                print(f"  decision : {decision.question[:70]}")
            if judgement.silence_reason:
                print(f"  silence  : {judgement.silence_reason[:80]}")

        writes = composed.audit.writes()
        print(f"\nAUDIT   {len(composed.audit.entries)} entries, {len(writes)} writes")
        for entry in writes:
            print(f"  {'FAILED ' if entry.failed else 'ok     '}{entry.actor:14s} {entry.action}")
            if entry.failed:
                print(f"           why: {entry.payload.get('error', '(not recorded)')[:110]}")

        # The claim adapt_task exists to make: a plan can change without the
        # record of why it had to change being touched. Read back from the
        # store, because what matters is what landed, not what the tool said.
        print()
        print("GRAPH AFTER")
        lost = False
        for goal in store.load(USER).goals:
            for route in goal.routes:
                for task in route.tasks:
                    was_slots, was_count, was_slips, was_title = before[task.id]
                    now_slots = list(task.scheduled_slots)
                    if (now_slots, task.title) == (was_slots, was_title):
                        continue
                    past = [slot for slot in was_slots if slot.date() < clock.today]
                    survived = len(set(past) & set(now_slots))
                    print(f"  {task.id}: {was_title!r}")
                    if task.title != was_title:
                        print(f"    retitled  -> {task.title!r}")
                    print(f"    slots     {len(was_slots)} -> {len(now_slots)}")
                    print(f"    past kept {survived}/{len(past)}")
                    print(f"    slips     {was_slips} -> {len(task.slips)}, count {was_count} -> {task.slip_count}")
                    if len(task.slips) < was_slips or task.slip_count < was_count:
                        print("    *** SLIP HISTORY LOST -- the one thing it must not do ***")
                        lost = True
                    if survived < len(past):
                        print("    *** A PAST SLOT WAS REWRITTEN ***")
                        lost = True

        print("\n" + "=" * 66)
        print("This is the first time any of it has thought for itself.")
        return 1 if lost else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
