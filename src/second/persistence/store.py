"""The Living Graph, persisted.

One DynamoDB table, ``second_graph``, holding two kinds of row:

    pk=USER#<id>  sk=GRAPH                    the whole Living Graph, one item
    pk=USER#<id>  sk=AUDIT#<iso>#<seq>        one row per thing the system did

**Why the whole graph is one item.** A spec-shaped three-goal graph measures
well under a tenth of DynamoDB's 400 KB item cap, and every read in this system
is a whole-graph read -- no agent wants one route without its tasks. Per-entity
rows would buy query flexibility nothing here uses, at the cost of a
multi-item transaction on every write.

**Why writes are read-modify-write with an optimistic lock**, rather than nested
``UpdateExpression`` paths: several nodes write during a single Daily run, and
the failure that matters is the Adapter silently clobbering the Observer's
person-layer update. A conditional write on ``version`` turns that into a retry
instead of a lost write. It also sidesteps the trap where
``SET person.preferences.x`` raises ``ValidationException`` if ``preferences``
does not already exist -- there are no partial paths to keep alive.

The cost is that two writers in the same run serialise. At this volume that is
milliseconds, and correctness is worth more than the milliseconds.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from second.core.models import AuditEntry, LivingGraph
from second.persistence.serde import decimals_to_native, from_item, to_item
from second.settings import AWS_REGION, TABLE_NAME

logger = logging.getLogger(__name__)

GRAPH_SK = "GRAPH"
BRIEF_PREFIX = "BRIEF#"
AUDIT_PREFIX = "AUDIT#"


class VersionConflict(RuntimeError):
    """Another writer changed the graph between our read and our write."""


def _pk(user_id: str) -> str:
    return f"USER#{user_id}"


class LivingGraphStore:
    """Reads and writes the Living Graph.

    Args:
        table: An existing boto3 DynamoDB Table resource. Injected so tests can
            hand in a fake or a moto-backed table without touching AWS.
        table_name: Used only when ``table`` is not supplied.
        region: Used only when ``table`` is not supplied.
    """

    def __init__(
        self,
        table: Any = None,
        *,
        table_name: str = TABLE_NAME,
        region: str = AWS_REGION,
    ) -> None:
        self._table = table
        self._table_name = table_name
        self._region = region

    @property
    def table(self) -> Any:
        """The DynamoDB table, created lazily so importing this module needs no credentials."""
        if self._table is None:
            self._table = boto3.resource("dynamodb", region_name=self._region).Table(self._table_name)
        return self._table

    # -- schema ---------------------------------------------------------

    def ensure_table(self) -> None:
        """Create the table if it does not exist. Safe to call repeatedly."""
        client = boto3.client("dynamodb", region_name=self._region)
        try:
            client.describe_table(TableName=self._table_name)
            logger.info("table %s already exists", self._table_name)
            return
        except client.exceptions.ResourceNotFoundException:
            pass

        client.create_table(
            TableName=self._table_name,
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
        client.get_waiter("table_exists").wait(TableName=self._table_name)
        logger.info("created table %s", self._table_name)

    # -- the graph ------------------------------------------------------

    def load(self, user_id: str) -> LivingGraph:
        """Read the whole Living Graph.

        Uses a strongly consistent read. Several nodes write during one run, and
        an eventually-consistent read would hand a downstream node the pre-write
        graph -- whose ``version`` is then already stale, so the optimistic lock
        fails on a conflict that never really happened.

        Returns an empty graph for an unknown user rather than raising, because
        a first-run intake is a normal state, not an error.
        """
        response = self.table.get_item(
            Key={"pk": _pk(user_id), "sk": GRAPH_SK},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return LivingGraph(user_id=user_id)
        return from_item(LivingGraph, item["graph"])

    def save(self, graph: LivingGraph) -> LivingGraph:
        """Write the graph, but only if nobody else changed it first.

        Args:
            graph: The graph to persist. Its ``version`` must match what is
                currently stored.

        Returns:
            The graph as written, with ``version`` incremented and
            ``updated_at`` stamped.

        Raises:
            VersionConflict: The stored version moved. Re-read and re-apply --
                or use :meth:`mutate`, which does that for you.
        """
        expected = graph.version
        written = graph.model_copy(
            update={"version": expected + 1, "updated_at": datetime.now(timezone.utc)}
        )

        item = {
            "pk": _pk(graph.user_id),
            "sk": GRAPH_SK,
            "version": written.version,
            "graph": to_item(written),
        }

        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk) OR #v = :expected",
                ExpressionAttributeNames={"#v": "version"},
                ExpressionAttributeValues={":expected": expected},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            raise VersionConflict(
                f"graph for {graph.user_id} moved underneath us: expected version {expected}"
            ) from error

        return written

    def mutate(
        self,
        user_id: str,
        change: Callable[[LivingGraph], LivingGraph | None],
        *,
        attempts: int = 5,
    ) -> LivingGraph:
        """Apply a change to the graph, retrying if another writer wins the race.

        Args:
            user_id: Whose graph to change.
            change: Receives the current graph and mutates it in place, or
                returns a replacement. Must be safe to run more than once --
                it will be, on a conflict.
            attempts: How many times to re-read and re-apply before giving up.

        Returns:
            The graph as written.

        Raises:
            VersionConflict: Still losing the race after ``attempts`` tries.
                Failure direction: raise rather than write. A lost person-layer
                update is invisible; a raised error is not.
        """
        for attempt in range(1, attempts + 1):
            current = self.load(user_id)
            updated = change(current) or current
            try:
                return self.save(updated)
            except VersionConflict:
                if attempt == attempts:
                    raise
                logger.warning("version conflict on %s, retry %d/%d", user_id, attempt, attempts)
        raise AssertionError("unreachable")

    # -- the day ---------------------------------------------------------

    def save_brief(self, user_id: str, brief: Any) -> None:
        """Keep a computed brief so reading the day does not re-run the graph.

        SURFACES found that ``GET /api/today`` ran the entire Daily graph -- tens
        of seconds and real tokens, on a route anything might poll. The store held
        the graph but had nowhere to put a day.
        """
        try:
            self.table.put_item(
                Item={
                    "pk": _pk(user_id),
                    "sk": f"{BRIEF_PREFIX}{brief.on.isoformat()}",
                    "brief": to_item(brief),
                }
            )
        except ClientError:
            logger.exception("could not cache the brief for %s; the run still stands", user_id)

    def load_brief(self, user_id: str, on: Any) -> dict | None:
        """The most recently computed brief for a day, or None."""
        try:
            response = self.table.get_item(
                Key={"pk": _pk(user_id), "sk": f"{BRIEF_PREFIX}{on.isoformat()}"},
                ConsistentRead=True,
            )
        except ClientError:
            logger.exception("could not read the cached brief for %s", user_id)
            return None
        item = response.get("Item")
        return item["brief"] if item else None

    # -- the audit log --------------------------------------------------

    def append_audit(self, user_id: str, entries: list[AuditEntry]) -> None:
        """Append audit rows. Never fails a run.

        The audit log is evidence, not control flow. If DynamoDB is unavailable
        the run should still complete -- so this logs and swallows.
        **Failure direction: lose the record, keep the run.**
        """
        if not entries:
            return
        try:
            with self.table.batch_writer() as batch:
                for seq, entry in enumerate(entries):
                    batch.put_item(
                        Item={
                            "pk": _pk(user_id),
                            "sk": f"{AUDIT_PREFIX}{entry.at.isoformat()}#{seq:04d}",
                            **to_item(entry),
                        }
                    )
        except ClientError:
            logger.exception("audit append failed for %s; run continues", user_id)

    def read_audit(self, user_id: str, limit: int = 50) -> list[AuditEntry]:
        """Read the most recent audit rows, newest first."""
        response = self.table.query(
            KeyConditionExpression=(
                Key("pk").eq(_pk(user_id)) & Key("sk").begins_with(AUDIT_PREFIX)
            ),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [
            from_item(AuditEntry, decimals_to_native(item))
            for item in response.get("Items", [])
        ]
