"""Tests for the forven-stale-triage scheduler job registration."""
from __future__ import annotations


def test_stale_triage_job_registered():
    """forven-stale-triage must be registered with kind='stale_triage'."""
    from forven.db import init_db
    from forven.scheduler import seed_forven_jobs, get_jobs

    init_db()
    seed_forven_jobs()

    jobs = {j["id"]: j for j in get_jobs()}
    assert "forven-stale-triage" in jobs
    payload = jobs["forven-stale-triage"].get("payload") or {}
    if isinstance(payload, str):
        import json
        payload = json.loads(payload)
    assert payload.get("kind") == "stale_triage"
    assert int(payload.get("days", 0)) >= 1
