"""
GOV4 Governance Control Plane - SSOT v4.0.1
Optimized for immutable state transitions and high-throughput durability.
"""

from __future__ import annotations
import os
import json
import hmac
import hashlib
import logging
import math
import uuid
import copy
from dataclasses import dataclass, field
from enum import Enum, auto
from threading import Lock
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Tuple

# ============================================================
# LOGGING & CORE SYSTEM CONSTANTS
# ============================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("gov4.ssot")

# ============================================================
# UTILITIES & SERIALIZATION
# ============================================================
def canonical(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)

def normalize(obj: Any, precision: int = 10) -> Any:
    if isinstance(obj, float): return round(obj, precision)
    if isinstance(obj, dict): return {k: normalize(v, precision) for k, v in obj.items()}
    if isinstance(obj, list): return [normalize(v, precision) for v in obj]
    return obj

# ============================================================
# WRITE-AHEAD LOG (DURABILITY HARDENED)
# ============================================================
class WAL:
    def __init__(self, path: str):
        self.path = path
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        # Buffering=1 for line buffering; explicit flush called on critical writes
        self.f = open(path, "a+", encoding="utf-8", buffering=1)

    def append(self, record: Dict[str, Any]) -> None:
        self.f.write(canonical(record) + "\n")
        self.f.flush() # Ensure durability on every audit log

    def close(self) -> None:
        self.f.close()

# ============================================================
# STATE REDUCER (IMMUTABLE PATTERN)
# ============================================================
class GovernanceCoreReducer:
    """Uses dictionary merge pattern instead of deepcopy for performance."""
    def apply(self, context: Dict[str, Any], event: NormalizedEvent) -> Dict[str, Any]:
        # Shallow copy for the new state root
        next_state = {**context}
        delta = event.delta
        
        if event.event_type == "telemetry_update":
            next_state["metrics"] = delta
        elif event.event_type == "escalation":
            next_state["escalation_logged"] = True
        elif event.event_type == "status_change":
            next_state["system_status"] = delta.get("status")
        elif event.event_type == "hiring_decision":
            next_state["last_decision"] = delta
            if delta.get("verdict") == "ISOLATE":
                next_state["system_status"] = "CRITICAL"
        return next_state

# ============================================================
# EXECUTION RUNTIME
# ============================================================
class ExecutionRuntime:
    def __init__(self, store: EventStore, reducer: Reducer,
                 snapshot_policy: Optional[SnapshotPolicy] = None) -> None:
        self._store = store
        self._reducer = reducer
        self._snapshot_policy = snapshot_policy or EveryNEventsSnapshot(50)
        self._snapshots: Dict[str, StateSnapshot] = {}

    def materialize_state(self, entity_id: str) -> Mapping[str, Any]:
        snapshot = self._snapshots.get(
            entity_id, StateSnapshot(entity_id=entity_id, last_sequence_no=0, context={})
        )
        # Base state from snapshot
        context = snapshot.context
        events = self._store.events_since(entity_id, snapshot.last_sequence_no)

        # Apply events incrementally
        for event in events:
            context = self._reducer.apply(context, event)

        if events and self._snapshot_policy.should_snapshot(len(events)):
            self._snapshots[entity_id] = StateSnapshot(
                entity_id=entity_id,
                last_sequence_no=events[-1].sequence_no,
                context=context, # Context is already a fresh dict from reducer
            )
        return MappingProxyType(context)
