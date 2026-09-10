"""Moving Pydantic models in and out of DynamoDB.

Two lines that would otherwise be discovered at the first real write.

boto3's ``TypeSerializer`` rejects Python floats outright -- it will not guess a
precision for you -- and the shared contract has two float fields:
``Goal.extraction_confidence`` and ``Diagnosis.confidence``. So ``model_dump()``
raises, and a plain ``json.loads(model_dump_json())`` round trip raises too,
because it hands the floats straight back.

The fix is to route through JSON (which turns ``date`` and ``datetime`` into
strings for free) while intercepting the float parse:

    json.loads(model.model_dump_json(), parse_float=Decimal)

On the way back, Pydantic revalidates ``Decimal`` into a ``float`` field
cleanly, so nothing downstream has to know this happened.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def to_item(model: BaseModel) -> dict[str, Any]:
    """Convert a Pydantic model into something DynamoDB will accept.

    Args:
        model: Any model from ``second.core.models``.

    Returns:
        A plain dict whose floats are ``Decimal`` and whose dates are ISO
        strings, suitable for a resource-level ``put_item`` or as a nested Map.
    """
    return json.loads(model.model_dump_json(), parse_float=Decimal)


def from_item(model_type: type[T], item: dict[str, Any]) -> T:
    """Rebuild a Pydantic model from a DynamoDB item.

    Args:
        model_type: The model class to rebuild.
        item: The item as returned by boto3's resource interface.

    Returns:
        A validated model. ``Decimal`` values revalidate into ``float`` fields.
    """
    return model_type.model_validate(item)


def decimals_to_native(value: Any) -> Any:
    """Recursively replace ``Decimal`` with ``int`` or ``float``.

    Only needed on the way out to JSON responses -- ``json.dumps`` cannot
    serialise ``Decimal`` and the API layer hands these to FastAPI. Pydantic
    handles its own conversion, so this is for raw dicts read straight from
    DynamoDB, such as an audit row.
    """
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if value == as_int else float(value)
    if isinstance(value, list):
        return [decimals_to_native(item) for item in value]
    if isinstance(value, dict):
        return {key: decimals_to_native(item) for key, item in value.items()}
    return value
