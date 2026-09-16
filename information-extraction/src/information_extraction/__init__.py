"""Offline extraction with opt-in configured profiles and legacy G0 compatibility."""

from .contracts import (
    Action, Attempt, Block, Blocked, Candidate, Chunk, Claim, Conflict, Evidence,
    ExecutionError, FailureCode, IntegrityError, InvalidInput, Metric, Model, ModelFailure,
    ModelRequest, ModelResponse, NotFound, Plan, Record, ReviewStatus, SCHEMA_VERSION,
    Snapshot, StaleRevision, Status, Store, TokenUsage, ValidationFailure,
    ConfiguredCandidate, ConfiguredPlan, DialogueBlock, ExtractionProfile, FieldEvidence,
    FieldSpec, FieldType, FieldValue, FlatRecord, RecordSchema,
)
from .execution import Execution
from .sqlite_store import SQLiteStore
from .schema import load_profile

__all__ = [
    "Action", "Attempt", "Block", "Blocked", "Candidate", "Chunk", "Claim", "Conflict",
    "Evidence", "Execution", "ExecutionError", "FailureCode", "IntegrityError",
    "InvalidInput", "Metric", "Model", "ModelFailure", "ModelRequest", "ModelResponse", "NotFound",
    "Plan", "Record", "ReviewStatus", "SCHEMA_VERSION", "SQLiteStore", "Snapshot",
    "StaleRevision", "Status", "Store", "TokenUsage", "ValidationFailure",
    "ConfiguredCandidate", "ConfiguredPlan", "DialogueBlock", "ExtractionProfile", "FieldEvidence",
    "FieldSpec", "FieldType", "FieldValue", "FlatRecord", "RecordSchema", "load_profile",
]
