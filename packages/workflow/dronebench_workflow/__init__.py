"""Revision store, transactions, and the job queue (Team B, architecture sections 4, 5, 7)."""

from .db import SCHEMA_VERSION, connect, migrate, transaction
from .repository import Repository
from .revisions import DesignState, RevisionBuilder, RevisionService
from .store import ArtifactStore, ImmutabilityError
from .transactions import TransactionService

__all__ = [
    "SCHEMA_VERSION", "connect", "migrate", "transaction",
    "Repository",
    "ArtifactStore", "ImmutabilityError",
    "DesignState", "RevisionBuilder", "RevisionService",
    "TransactionService",
]
