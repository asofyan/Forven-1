"""One-shot migration: move ~/.juddex -> ~/.forven on first Forven boot.

Idempotent: if ~/.forven already exists with content, skip. If ~/.juddex
does not exist, skip. Otherwise move the directory, rename juddex.duckdb
to forven.duckdb, rename .juddex_key to .forven_key, and drop a
LEGACY_MOVED_TO_FORVEN breadcrumb in the old location if it still exists.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

BREADCRUMB = "LEGACY_MOVED_TO_FORVEN"


def migrate_home_directory() -> bool:
    """Return True if a migration occurred, False if skipped."""
    home = Path.home()
    legacy = home / ".juddex"
    current = home / ".forven"

    if current.exists() and any(current.iterdir()):
        return False
    if not legacy.exists():
        return False

    log.warning("Forven: migrating %s -> %s (one-shot)", legacy, current)
    legacy.rename(current)

    for old_name, new_name in (
        ("juddex.duckdb", "forven.duckdb"),
        (".juddex_key", ".forven_key"),
    ):
        old_path = current / old_name
        new_path = current / new_name
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)

    try:
        (home / ".juddex").mkdir(exist_ok=True)
        (home / ".juddex" / BREADCRUMB).write_text(
            f"This directory's contents were moved to {current} during the "
            f"Juddex -> Forven rename. Safe to delete.\n"
        )
    except OSError:
        pass

    return True
