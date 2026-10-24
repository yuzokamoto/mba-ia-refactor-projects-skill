"""Relógio UTC que preserva o formato legado sem timezone."""
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)
