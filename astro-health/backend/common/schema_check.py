"""Validate any object against data/schemas/*.json (read-only dependency on the data folder).

Owner: person B
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema


def validate(instance: dict, schema_path: str) -> None:
    """Validate *instance* against the JSON Schema at *schema_path*.

    Parameters
    ----------
    instance:
        The dict to validate.
    schema_path:
        Absolute (or cwd-relative) path to the ``.json`` schema file.

    Raises
    ------
    ValueError
        If *instance* fails validation, with the ``jsonschema`` error message
        embedded so callers get a clear diagnostic.
    FileNotFoundError
        If *schema_path* does not exist.
    """
    path = Path(schema_path)
    with path.open() as f:
        schema = json.load(f)

    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"Schema validation failed against {path.name!r}: {exc.message}"
        ) from exc
