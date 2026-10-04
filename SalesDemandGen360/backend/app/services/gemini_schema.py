"""Turning a Pydantic contract into a schema Gemini will accept.

This module exists because the two schema dialects disagree in ways that fail
*silently in the worst direction*: Gemini rejects what it does not understand
with a 400 naming a field, and accepts a schema it has quietly reinterpreted.

Three differences do the damage:

* **`$ref` / `$defs`.** Pydantic hoists every nested model into `$defs` and
  references it. Gemini's `responseSchema` has no `$ref` at all, so a nested
  contract — `DraftSet` holding `TouchDraft`, `StrategyProposal` holding
  `ProposedThread` — arrives as an empty object. Every one of our contracts is
  nested, so this is not an edge case; it is the normal case.
* **Unknown keywords.** `additionalProperties`, `$schema`, `title`, `default`,
  `exclusiveMinimum` and Pydantic's `anyOf`-for-optional are variously rejected
  or ignored.
* **Property order.** JSON Schema has no ordering; Gemini generates fields in
  the order given and takes `propertyOrdering` as the instruction. Without it
  the model's output order drifts between calls, which is harmless for parsing
  and costly for prompt caching.

A fourth difference has no workaround at all: Gemini cannot describe a
**free-form map**. `EvaluationResult.scores` is `dict[str, float]` — arbitrary
criterion names — and there is no `additionalProperties` to lean on. An
optional one is dropped from the schema and its name recorded in
`dropped_fields`, so the capability gap is reported rather than discovered; a
required one raises, because a contract whose mandatory field cannot be asked
for is not runnable on this provider.

The translation is deliberately **lossy and conservative**: anything that
cannot be expressed is dropped from the schema rather than approximated, and
the resulting object is validated against the original Pydantic model
afterwards. That ordering matters — the schema steers the model, the Pydantic
model is what actually enforces the contract. Guarantees this module cannot
carry (exactly six dimensions, a dated touch citing its signal) are still
enforced, just one step later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

#: Keywords Gemini's subset of OpenAPI 3.0 understands. Everything else is
#: dropped — an unknown keyword is either a 400 or, worse, silently ignored.
_KEPT = {
    "type",
    "format",
    "description",
    "enum",
    "items",
    "properties",
    "required",
    "nullable",
    "minItems",
    "maxItems",
    # Not `minLength`/`maxLength`. They look like the obvious way to stop a
    # derailed call writing until the output budget runs out, and Gemini
    # answers **HTTP 400** to a schema carrying either — tried, measured,
    # reverted. The bounds stay on the Pydantic model, where they reject an
    # over-long answer after the fact rather than preventing it.
}

#: `format` values Gemini accepts. Pydantic emits several it does not, and an
#: unrecognised format is rejected rather than ignored.
_FORMATS = {
    "integer": {"int32", "int64"},
    "number": {"float", "double"},
    "string": {"date-time", "enum"},
}


class SchemaTooComplexError(ValueError):
    """A contract that cannot be expressed in Gemini's schema subset.

    Raised rather than degraded. A silently simplified schema produces output
    that parses and means something slightly different, which is the failure
    mode that survives review and shows up as bad copy weeks later.
    """


@dataclass
class Translation:
    """The schema, and what could not survive the trip."""

    schema: dict[str, Any]
    #: Optional fields Gemini cannot describe, by dotted path. Reported so a
    #: capability gap between providers is visible rather than inferred later
    #: from output that is quietly missing something.
    dropped_fields: list[str] = field(default_factory=list)


def to_gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Just the schema, for callers that do not care what was lost."""
    return translate(model).schema


def translate(model: type[BaseModel]) -> Translation:
    """Translate a Pydantic model into `responseSchema` shape."""
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    dropped: list[str] = []
    schema = _convert(raw, defs, depth=0, path="", dropped=dropped)
    return Translation(schema=schema, dropped_fields=dropped)


def _convert(
    node: Any,
    defs: dict[str, Any],
    *,
    depth: int,
    path: str,
    dropped: list[str],
) -> dict[str, Any]:
    if depth > 12:
        # Deep recursion here means a self-referential model. Gemini cannot
        # express one, and the alternative to failing is an infinite expansion.
        raise SchemaTooComplexError(
            "schema nests deeper than 12 levels, or references itself"
        )
    if not isinstance(node, dict):
        raise SchemaTooComplexError(f"unexpected schema node: {node!r}")

    node = _resolve(node, defs)
    out: dict[str, Any] = {}

    for key, value in node.items():
        if key not in _KEPT:
            continue
        if key == "properties":
            required = set(node.get("required", []))
            properties: dict[str, Any] = {}
            for name, sub in value.items():
                child = f"{path}.{name}" if path else name
                try:
                    properties[name] = _convert(
                        sub, defs, depth=depth + 1, path=child, dropped=dropped
                    )
                except SchemaTooComplexError:
                    if name in required:
                        raise
                    # Optional and inexpressible. Dropped, and recorded — see
                    # the module docstring.
                    dropped.append(child)
            out["properties"] = properties
        elif key == "items":
            out["items"] = _convert(
                value, defs, depth=depth + 1, path=f"{path}[]", dropped=dropped
            )
        elif key == "format":
            out["format"] = value  # filtered below, once `type` is known
        else:
            out[key] = value

    _fix_format(out)

    if out.get("type") == "object":
        properties = out.get("properties") or {}
        if not properties:
            # Either a free-form map (`dict[str, float]`), which Gemini cannot
            # describe, or a `$ref` that was missed. Both return `{}` from
            # every call if let through.
            raise SchemaTooComplexError(
                f"the object at {path or '<root>'!r} has no properties — it is a "
                "free-form map, or a $ref was missed"
            )
        # Gemini generates fields in the order given. Fixing it keeps output
        # byte-stable between calls, which is what prompt caching keys on.
        out["propertyOrdering"] = list(properties)
        required = [r for r in out.get("required", []) if r in properties]
        if required:
            out["required"] = required
        else:
            out.pop("required", None)

    if "type" not in out:
        raise SchemaTooComplexError(f"could not determine a type for {node!r}")
    return out


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Inline a `$ref`, and flatten the `anyOf` Pydantic uses for optionals.

    `str | None` becomes `anyOf: [{type: string}, {type: null}]`. Gemini has no
    `anyOf`, but it does have `nullable` — so the two-branch optional, which is
    almost every optional field we have, translates exactly. A genuine union of
    two real types does not, and says so.
    """
    if "$ref" in node:
        target = _lookup(node["$ref"], defs)
        merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        return _resolve(merged, defs)

    for combinator in ("anyOf", "oneOf"):
        if combinator not in node:
            continue
        branches = [_resolve(b, defs) for b in node[combinator]]
        concrete = [b for b in branches if b.get("type") != "null"]
        nullable = len(concrete) != len(branches)
        if len(concrete) != 1:
            raise SchemaTooComplexError(
                f"{combinator} with {len(concrete)} non-null branches cannot be "
                "expressed in Gemini's schema subset"
            )
        rest = {k: v for k, v in node.items() if k != combinator}
        resolved = {**concrete[0], **rest}
        if nullable:
            resolved["nullable"] = True
        return resolved

    return node


def _lookup(ref: str, defs: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/$defs/"):
        raise SchemaTooComplexError(f"unsupported reference {ref!r}")
    name = ref.removeprefix("#/$defs/")
    if name not in defs:
        raise SchemaTooComplexError(f"reference {ref!r} has no definition")
    return defs[name]


#: What to tell the model in words when the schema cannot say it. Found the
#: hard way: dropping `format: uuid` silently produced `"signal-123"` for a
#: `list[uuid.UUID]` field, which is schema-valid and fails the contract.
_FORMAT_HINTS = {
    "uuid": "a UUID, exactly as given in the input; never invent one",
    "date": "a date as YYYY-MM-DD",
    "date-time": "an ISO 8601 timestamp",
    "email": "an email address",
    "uri": "an absolute URL",
}


def _fix_format(out: dict[str, Any]) -> None:
    """Drop a `format` this type does not accept, and say it in prose instead.

    Pydantic emits `format: uuid` and `format: date`; Gemini's string formats
    are `enum` and `date-time` only. Dropping the keyword leaves a plain
    string — and a plain string is what the model then invents. The constraint
    has to survive somewhere, so it moves into the description, which is the
    one channel both dialects share.
    """
    fmt = out.get("format")
    if fmt is None:
        return
    if fmt in _FORMATS.get(out.get("type", ""), set()):
        return

    out.pop("format")
    hint = _FORMAT_HINTS.get(fmt, f"formatted as {fmt}")
    existing = out.get("description")
    # Only the first character. `str.capitalize()` lowercases the rest, which
    # turns "a UUID" into "a uuid" — and the whole point of the hint is that
    # the model recognises the word.
    standalone = hint[0].upper() + hint[1:]
    out["description"] = f"{existing} ({hint})" if existing else standalone
