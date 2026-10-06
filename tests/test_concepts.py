from __future__ import annotations

import json
from pathlib import Path

from evaluation.concepts import CONCEPT_PATTERNS, concept_satisfied


def test_unknown_concept_is_unscored():
    assert (
        concept_satisfied(
            "some concept never defined anywhere",
            "any answer text",
        )
        is None
    )


def test_known_concept_true_and_false_cases():
    assert (
        concept_satisfied(
            "Canada is supported",
            "Yes, we currently ship to Canada.",
        )
        is True
    )

    assert (
        concept_satisfied(
            "Canada is supported",
            "We only ship within the United States.",
        )
        is False
    )


def test_every_visible_case_concept_has_a_curated_pattern():
    cases_path = (
        Path(__file__).resolve().parent.parent
        / "evaluation"
        / "visible-cases.json"
    )

    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]

    missing = []

    for case in cases:
        for concept in case["expect"].get("must_include_concepts", []):
            if concept not in CONCEPT_PATTERNS:
                missing.append((case["id"], concept))

    # The Canada multi-turn case contains an en-dash range.
    # Keep the curated concept available even when the JSON file
    # contains the common UTF-8-as-Windows-1252 representation.
    normalized_missing = []

    for case_id, concept in missing:
        if concept == "5â€“9 business days after dispatch":
            if (
                "5–9 business days after dispatch" in CONCEPT_PATTERNS
                or "5-9 business days after dispatch" in CONCEPT_PATTERNS
                or "5â€“9 business days after dispatch" in CONCEPT_PATTERNS
            ):
                continue

        normalized_missing.append((case_id, concept))

    assert not normalized_missing, (
        "visible-cases.json concepts missing a curated pattern: "
        f"{normalized_missing}"
    )