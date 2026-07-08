"""Oracle F2: casos TECH_ONLY / ECO_ONLY / FULL (CA-1.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.generation_mode_policy import (
    active_jobs_for_mode,
    skipped_jobs_for_mode,
    wipe_preserve_subdirs_for_mode,
)

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "generation_mode" / "oracle_cases.json"


@pytest.fixture(scope="module")
def oracle_cases():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", json.loads(_FIXTURE.read_text(encoding="utf-8")), ids=lambda c: c["case_id"])
def test_generation_mode_oracle(case):
    mode = case["generation_mode"]
    active = active_jobs_for_mode(mode)
    skipped = skipped_jobs_for_mode(mode)
    for job in case["expect_active_jobs"]:
        assert job in active, f"{case['case_id']}: {job} should be active"
    for job in case["expect_skipped_jobs"]:
        assert job in skipped, f"{case['case_id']}: {job} should be skipped"
    preserve = wipe_preserve_subdirs_for_mode(mode)
    for sub in case["expect_preserve_on_wipe"]:
        assert sub in preserve, f"{case['case_id']}: preserve {sub}"
