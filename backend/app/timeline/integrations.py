"""Interfaces for clinical modules that own source records.

Source modules register a verifier before writing an event. The timeline never
accepts event creation from a client and never treats a caller-supplied ID as
proof that a medical record exists.
"""
from collections.abc import Callable

from sqlalchemy.orm import Session

SOURCE_MODULES = frozenset({"consultation", "prescription", "medicine", "laboratory", "appointment"})
SourceVerifier = Callable[[Session, int, str], bool]

_source_verifiers: dict[str, SourceVerifier] = {}


def register_source_verifier(source_module: str, verifier: SourceVerifier) -> None:
    """Register the owning module's patient-scoped source-record lookup."""
    if source_module not in SOURCE_MODULES:
        raise ValueError(f"Unsupported timeline source module: {source_module}")
    _source_verifiers[source_module] = verifier


def get_source_verifier(source_module: str) -> SourceVerifier | None:
    return _source_verifiers.get(source_module)


def clear_source_verifiers() -> None:
    """Clear adapters, primarily for isolated test teardown."""
    _source_verifiers.clear()
