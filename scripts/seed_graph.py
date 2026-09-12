"""Put the demo world into the real DynamoDB table. Dry by default.

    uv run python scripts/seed_graph.py                  # show what would be written
    uv run python scripts/seed_graph.py --apply          # write it
    uv run python scripts/seed_graph.py --apply --replace  # overwrite an existing graph

**Why this exists.** ``demo_scenario.living_graph()`` had exactly three callers:
the test suite, ``live_daily.py`` (which runs against ``moto``, in process), and
nothing else. ``bootstrap_aws.py`` creates the table and leaves it empty, and
``LivingGraphStore.load`` returns an empty graph for an unknown user rather than
raising -- so a real deployment came up clean, answered ``GET /api/today`` with a
day containing nothing, and never said why. Every live run so far has been
against an in-memory table. This is the missing half.

``seed_demo.py`` is the other half and they are not interchangeable: that one
writes Google Calendar and Gmail, this one writes the Living Graph. The two must
agree, because the Observer compares the plan in this table against the events in
that calendar. Both derive from ``demo_scenario``, and both read the same
``SECOND_DEMO_TODAY``, which is the only thing keeping them aligned.

**Set SECOND_DEMO_TODAY in the shell before running either.** ``demo_scenario``
reads it at *import* time and every date in the world is relative to it. Exporting
it afterwards moves nothing, and a graph anchored to one day against a calendar
anchored to another produces an Observer that reports everything as missed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from second.persistence.store import LivingGraphStore, VersionConflict  # noqa: E402
from second.settings import AWS_REGION, DEMO_TODAY_ENV, TABLE_NAME  # noqa: E402
from second.testing import demo_scenario  # noqa: E402


def describe(graph) -> list[str]:
    """A short census of a graph, so what is about to be written is legible."""
    routes = [route for goal in graph.goals for route in goal.routes]
    tasks = [task for route in routes for task in route.tasks]
    slips = sum(len(task.slips) for task in tasks)
    scheduled = sum(len(task.scheduled_slots) for task in tasks)
    return [
        f"goals            {len(graph.goals)}  ({sum(1 for g in graph.goals if g.status == 'active')} active)",
        f"routes           {len(routes)}",
        f"tasks            {len(tasks)}",
        f"scheduled slots  {scheduled}",
        f"slip records     {slips}",
        f"links            {len(graph.links)}",
        f"abandoned slots  {graph.person.abandoned_slots}",
        f"honoured slots   {graph.person.honoured_slots}",
        f"constraints      {graph.person.constraints}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply", action="store_true", help="actually write; without it this only reports"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="overwrite a graph that is already there (required if one exists)",
    )
    parser.add_argument("--user", default=demo_scenario.USER_ID, help="user id to write under")
    args = parser.parse_args(argv)

    pinned = os.environ.get(DEMO_TODAY_ENV)
    print(f"table   : {TABLE_NAME} in {AWS_REGION}")
    print(f"user    : {args.user}")
    print(f"anchored: {demo_scenario.TODAY}  ({DEMO_TODAY_ENV}={pinned or 'unset, using the default'})")
    if not pinned:
        print()
        print(f"  NOTE: {DEMO_TODAY_ENV} is not set, so the world is anchored to the built-in")
        print(f"  default. seed_demo.py will anchor the calendar to the same default only if")
        print(f"  it is run the same way. Set it in the shell before BOTH, not in .env --")
        print(f"  demo_scenario reads it at import and nothing here loads .env early enough")
        print(f"  to help.")
    print()

    graph = demo_scenario.living_graph()
    print("about to write:")
    for line in describe(graph):
        print(f"  {line}")
    print()

    store = LivingGraphStore(table_name=TABLE_NAME, region=AWS_REGION)

    try:
        existing = store.load(args.user)
    except Exception as error:  # noqa: BLE001 - a missing table is a normal first run
        print(f"could not read the table: {type(error).__name__}: {error}")
        print(f"if it does not exist yet: uv run python scripts/bootstrap_aws.py")
        return 1

    occupied = bool(existing.goals or existing.links)
    if occupied:
        print(f"ALREADY THERE: version {existing.version}, {len(existing.goals)} goal(s):")
        for goal in existing.goals:
            print(f"  {goal.id:12s} {goal.title[:52]}")
        if not args.replace:
            print()
            print("Refusing to overwrite. This graph holds slip history and person-layer")
            print("facts that nothing can reconstruct -- replacing it silently would destroy")
            print("the evidence every later diagnosis is built on. Pass --replace if that is")
            print("genuinely what you want.")
            return 1
        print("  --replace given; it will be overwritten.")
        print()

    if not args.apply:
        print("DRY RUN. Nothing written. Add --apply.")
        return 0

    # save() holds an optimistic lock on version. A fresh graph is version 0, which
    # only matches when nothing is stored; to deliberately replace, adopt the stored
    # version so the condition passes. This is the one place overwriting is intended,
    # and it is gated behind --replace above.
    if occupied:
        graph = graph.model_copy(update={"version": existing.version})

    try:
        written = store.save(graph)
    except VersionConflict as error:
        print(f"VERSION CONFLICT: {error}")
        print("Something wrote to this graph between the read above and the write.")
        print("Re-run; nothing was changed.")
        return 1
    except Exception as error:  # noqa: BLE001 - the point is to report it
        print(f"WRITE FAILED: {type(error).__name__}: {error}")
        return 1

    # Read it back rather than trusting the write. The store round-trips through
    # DynamoDB's Decimal types, and a field that serialises but does not deserialise
    # would otherwise show up much later, inside an agent.
    back = store.load(args.user)
    print(f"written. version {written.version}")
    print()
    print("read back from the table:")
    for line in describe(back):
        print(f"  {line}")

    problems = []
    if len(back.goals) != len(graph.goals):
        problems.append(f"goal count changed: wrote {len(graph.goals)}, read {len(back.goals)}")
    wrote_tasks = {t.id for g in graph.goals for r in g.routes for t in r.tasks}
    read_tasks = {t.id for g in back.goals for r in g.routes for t in r.tasks}
    if wrote_tasks != read_tasks:
        problems.append(f"tasks differ: missing {sorted(wrote_tasks - read_tasks)}")
    wrote_slips = sum(len(t.slips) for g in graph.goals for r in g.routes for t in r.tasks)
    read_slips = sum(len(t.slips) for g in back.goals for r in g.routes for t in r.tasks)
    if wrote_slips != read_slips:
        problems.append(f"slip records differ: wrote {wrote_slips}, read {read_slips}")

    if problems:
        print()
        print("PROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print()
    print("The graph survived the round trip intact.")
    print(f"Next: uv run python scripts/seed_demo.py --zone <IANA> --smoke --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
