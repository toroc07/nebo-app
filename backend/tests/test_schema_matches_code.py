"""db/schema.sql restricts some text columns to lists of values. They must match what the code
writes, or every insert fails in PostgreSQL with a CheckViolation. The in-memory store used by
the other tests has no such checks, so this compares the lists directly, without a database."""

import re
from typing import get_args

from app import config, main, models

SCHEMA = (config.BACKEND_DIR / "db" / "schema.sql").read_text(encoding="utf-8")


def _checks(column: str) -> list[set[str]]:
    """Value lists of every `column IN (...)` check in the schema (table and migration)."""
    return [
        set(re.findall(r"'([A-Z_]+)'", body))
        for body in re.findall(rf"{column}\s+IN\s*\(([^)]*)\)", SCHEMA)
    ]


def test_model1_classes_match_the_schema():
    checks = _checks("predicted_class")
    assert any(c == set(models.MODEL1_CLASSES) for c in checks)


def test_model2_classes_match_the_schema():
    classes = {t["class_name"] for t in models.MODEL2_TEMPLATE_CATALOG}
    assert any(c == classes for c in _checks("predicted_class"))


def test_vote_values_match_the_schema():
    allowed = set(get_args(main.CitizenVoteRequest.model_fields["vote"].annotation))
    checks = _checks("vote")
    assert checks and all(c == allowed for c in checks)
