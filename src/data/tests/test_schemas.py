import json
import pathlib

import pytest
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAIRS = [("reading", "sample_reading"), ("proposal", "sample_proposal"), ("verdict", "sample_verdict"),
         ("record", "sample_record"), ("card", "sample_card"), ("review", "sample_review")]


@pytest.mark.parametrize("schema,fixture", PAIRS)
def test_fixture_matches_schema(schema, fixture):
    s = json.loads((ROOT / "schemas" / f"{schema}.schema.json").read_text())
    f = json.loads((ROOT / "fixtures" / f"{fixture}.json").read_text())
    Draft202012Validator.check_schema(s)
    Draft202012Validator(s).validate(f)
