"""
backend/services/forecast_edits.py
====================================
The AI Action Center's whitelisted transformation types (feature-update.md
Feature 2) and the pure functions that apply/replay them.

Safety: operations are parsed from LLM output as strict JSON matching one of
these Pydantic schemas — never executed as code. This intentionally avoids
the exec()-on-LLM-output pattern the old (already-deleted)
services/constraint_executor.py used, which was a documented RCE vector.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from pydantic import BaseModel, ValidationError, field_validator

# days_of_week uses pandas/Python's Monday=0 .. Sunday=6 convention —
# documented here and in the LLM system prompt so both stay in sync.
_MIN_DOW, _MAX_DOW = 0, 6


class _DateRangeFilter(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    days_of_week: Optional[List[int]] = None

    @field_validator("days_of_week")
    @classmethod
    def _valid_dow(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for d in v:
                if not (_MIN_DOW <= d <= _MAX_DOW):
                    raise ValueError(f"days_of_week values must be {_MIN_DOW}-{_MAX_DOW}")
        return v

    def matches(self, record_date: date) -> bool:
        if self.date_from is not None and record_date < self.date_from:
            return False
        if self.date_to is not None and record_date > self.date_to:
            return False
        if self.days_of_week is not None and record_date.weekday() not in self.days_of_week:
            return False
        return True


class SetValueRangeOp(_DateRangeFilter):
    operation_type: str = "set_value_range"
    value: float


class ScaleRangeOp(_DateRangeFilter):
    operation_type: str = "scale_range"
    scale_pct: float


class ClipBoundsOp(_DateRangeFilter):
    operation_type: str = "clip_bounds"
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    @field_validator("max_value")
    @classmethod
    def _bounds_sane(cls, v, info):
        min_value = info.data.get("min_value")
        if v is not None and min_value is not None and v < min_value:
            raise ValueError("max_value must be >= min_value")
        return v


# Whitelist — the only operation types the AI Action Center will ever apply.
_OPERATION_SCHEMAS: Dict[str, type[BaseModel]] = {
    "set_value_range": SetValueRangeOp,
    "scale_range": ScaleRangeOp,
    "clip_bounds": ClipBoundsOp,
}


class InvalidOperationError(Exception):
    """Raised when the LLM's output doesn't parse as JSON or doesn't match
    one of the whitelisted operation schemas. Callers should surface a clean
    "couldn't understand that instruction" error, not a 500."""


def _extract_json_object(text: str) -> dict:
    """LLMs sometimes wrap JSON in markdown fences or add stray prose
    despite instructions not to. Try a direct parse first, then fall back
    to extracting the first {...} block."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise InvalidOperationError(f"Model output is not valid JSON: {text[:200]!r}")


def parse_operation(raw_text: str) -> Tuple[str, dict]:
    """Parses and validates raw LLM output into (operation_type, params_dict).
    Raises InvalidOperationError on anything that isn't valid JSON, is the
    model's explicit "none" (instruction doesn't describe an edit — see the
    system prompt), or doesn't match a whitelisted operation schema — never
    executes the input."""
    obj = _extract_json_object(raw_text)

    op_type = obj.get("operation_type")
    if op_type == "none":
        raise InvalidOperationError(
            "The model determined this instruction doesn't describe a forecast edit"
        )

    schema = _OPERATION_SCHEMAS.get(op_type)
    if schema is None:
        raise InvalidOperationError(
            f"Unknown or missing operation_type: {op_type!r}. "
            f"Must be one of {list(_OPERATION_SCHEMAS)}"
        )

    try:
        validated = schema.model_validate(obj)
    except ValidationError as exc:
        raise InvalidOperationError(f"Invalid parameters for {op_type}: {exc}") from exc

    return op_type, validated.model_dump(mode="json", exclude={"operation_type"})


def _record_date(record: dict) -> date:
    """results.json's Date values may be pandas-Timestamp-via-str() (space
    separator) or ISO "T"-separated strings depending on the write path —
    pd.Timestamp's parser handles both plus everything else, so it's used
    here instead of datetime.fromisoformat, which chokes on the former."""
    return pd.Timestamp(record["Date"]).date()


def apply_operation(
    records: List[dict],
    operation_type: str,
    params: dict,
) -> List[dict]:
    """Applies one whitelisted operation to the `Forecast` field of matching
    records (rows with Forecast is None — historical/test rows — are never
    touched; only the future forecast is ever edited by the Action Center,
    matching the spec's "re-render the graph with updated forecast").
    Returns a new list — never mutates the input, so baseline stays pure."""
    schema = _OPERATION_SCHEMAS[operation_type]
    op = schema.model_validate({"operation_type": operation_type, **params})

    result = copy.deepcopy(records)
    for row in result:
        if row.get("Forecast") is None:
            continue
        if not op.matches(_record_date(row)):
            continue

        if isinstance(op, SetValueRangeOp):
            row["Forecast"] = op.value
        elif isinstance(op, ScaleRangeOp):
            row["Forecast"] = row["Forecast"] * (op.scale_pct / 100.0)
        elif isinstance(op, ClipBoundsOp):
            value = row["Forecast"]
            if op.min_value is not None:
                value = max(value, op.min_value)
            if op.max_value is not None:
                value = min(value, op.max_value)
            row["Forecast"] = value

    return result


def affected_points_before(
    records: List[dict],
    operation_type: str,
    params: dict,
) -> List[dict]:
    """Captures {Date, Forecast} for exactly the rows `apply_operation` would
    touch, from the CURRENT effective series (before this operation is
    applied) — this is what makes revert exact rather than a recomputation."""
    schema = _OPERATION_SCHEMAS[operation_type]
    op = schema.model_validate({"operation_type": operation_type, **params})

    return [
        {"Date": row["Date"], "Forecast": row["Forecast"]}
        for row in records
        if row.get("Forecast") is not None and op.matches(_record_date(row))
    ]


def replay_edits(baseline_records: List[dict], edits: List[Any]) -> List[dict]:
    """Re-applies a job's persisted edit stack (ordered by sequence_no) on
    top of the baseline to compute the current effective series."""
    records = copy.deepcopy(baseline_records)
    for edit in edits:
        records = apply_operation(records, edit.operation_type, edit.params)
    return records
