"""Controller-local attribution for the private operator protocol."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorIdentity:
    subject: str
    source: str
    permissions: frozenset[str]

