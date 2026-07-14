"""Package-local tests for harness.eval_set/v1 offline validation (toy domain)."""

from __future__ import annotations

import json
from pathlib import Path

from harness_loop.eval_set import (
    load_eval_set,
    run_offline_expects,
    validate_eval_set_shape,
    validate_file,
)

FIXTURES = Path(__file__).parent / "fixtures"
EVAL = FIXTURES / "toy_eval_smoke.json"
CATALOG = FIXTURES / "toy_catalog.json"


def test_toy_eval_set_passes_offline():
    assert validate_file(EVAL, catalog_path=CATALOG) == []


def test_shape_rejects_wrong_schema_and_empty_cases():
    errors = validate_eval_set_shape({"schema": "nope/v0", "id": "x", "domain": "d", "cases": []})
    assert any("schema" in e for e in errors)
    assert any("cases" in e for e in errors)


def test_catalog_alias_miss_reported():
    doc = load_eval_set(EVAL)
    doc["cases"][0]["expects"][1]["alias"] = "definitely-not-an-alias"
    errors = run_offline_expects(doc, catalog_path=CATALOG)
    assert any("missing alias" in e for e in errors)


def test_alias_must_reject_requires_plugin_hook(tmp_path):
    doc = load_eval_set(EVAL)
    doc["cases"][0]["expects"] = [
        {"type": "alias_must_reject", "metric": "mttr", "alias": "Query"}
    ]
    errors = run_offline_expects(doc, catalog_path=CATALOG)
    assert any("requires plugin reject hook" in e for e in errors)


def test_alias_must_reject_with_injected_hook():
    doc = load_eval_set(EVAL)
    doc["cases"][0]["expects"] = [
        {"type": "alias_must_reject", "metric": "mttr", "alias": "Query"}
    ]
    errors = run_offline_expects(
        doc,
        catalog_path=CATALOG,
        alias_reject_fn=lambda metric, alias: (True, "1E-d ocr junk"),
    )
    assert errors == []
