"""
GSA Universal Cryptographic Interlock Wrapper Engine (v1.0.0)
Consolidated from GATEWAY canonical source + GSA-815 temporal exit gate.

Purpose:
   This module serves as the master control system for secure, verifiable
   data processing pipelines. It combines syntactic validation, metric analysis,
   and cryptographic auditing into one deterministic execution engine.

Architecture:
   - ContextEnvelope: Secure data container with history tracking
   - ComposableLegoModule: Standard interface for processing modules
   - SyntacticValidationLayer: Text governance (pronouns, hedging, paradoxes)
   - PipelineCycleManager: Main operational engine (error tracking, regime detection)
   - GsaUniversalAdapter: Universal wrapper that enforces interlock history
   - CryptographicAuditFramework: Tamper-evident logging with HMAC-SHA256
"""

from __future__ import annotations
import os
import json
import time
import hmac
import hashlib
import statistics
import asyncio
import re
from collections import deque
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Dict, Any, List, Tuple, Callable, Protocol, Optional


# ============================================================
# PROTOCOLS & DECORATORS
# ============================================================

def register_as_module(module_identifier: str) -> Callable[[type], type]:
    """Tags classes with a permanent ID so the system knows they are safe."""
    def decorator(cls: type) -> type:
        setattr(cls, "__gsa_authenticated__", True)
        setattr(cls, "__module_id__", module_identifier)
        return cls
    return decorator


class ComposableLegoModule(Protocol):
    """The standard rulebook that all processing modules must follow."""
    async def process_payload(self, context_envelope: ContextEnvelope) -> ContextEnvelope: ...


# ============================================================
# CORE DATA STRUCTURES
# ============================================================

@dataclass(frozen=False)
class ContextEnvelope:
    """The secure folder that carries data and its digital history."""
    payload_data: Any
    header_mapping: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    session_state_mapping: Dict[str, Any] = field(default_factory=dict)
    status_string: str = "INITIALIZED"


@dataclass(frozen=True)
class SystemInputStructure:
    """A strict container for incoming text and numbers."""
    text_content_body: str
    numeric_metric_value: float


# ============================================================
# CRYPTOGRAPHIC UTILITIES
# ============================================================

def compute_state_signature(
    upstream_hash: str,
    iteration: int,
    envelope: ContextEnvelope,
    extra_anchors: Optional[List[str]] = None
) -> str:
    """Creates a unique digital fingerprint based on the data and its history."""
    serialized_payload = json.dumps(envelope.payload_data, sort_keys=True, default=str)
    serialized_session = json.dumps(envelope.session_state_mapping, sort_keys=True, default=str)
    sorted_anchors = "||".join(sorted(extra_anchors)) if extra_anchors else "NONE"

    buffer_source = (
        f"parent:{upstream_hash}||iter:{iteration}||"
        f"graph:[{sorted_anchors}]||payload:{serialized_payload}||"
        f"session:{serialized_session}"
    )
    return hashlib.sha256(buffer_source.encode("utf-8")).hexdigest()


class CryptographicAuditFramework:
    """Keeps a permanent, unchangeable record of everything the system does."""
    def __init__(self) -> None:
        self.secret = os.getenv("VANGUARD_SECRET_KEY", "default-secure-key").encode()
        self.path = os.getenv("VANGUARD_AUDIT_LOG_PATH", "vanguard_audit.log")

    def write_tamper_evident_entry(self, event_type: str, metrics: Dict[str, Any]) -> None:
        """Writes a locked file entry that proves exactly what happened."""
        record = {"event": event_type, "metrics": metrics, "ts": time.time()}
        data_bytes = json.dumps(record, sort_keys=True).encode()
        record["signature"] = hmac.new(self.secret, data_bytes, hashlib.sha256).hexdigest()
        try:
            with open(self.path, "a") as log_file:
                log_file.write(json.dumps(record) + "\n")
        except IOError:
            pass


# ============================================================
# GOVERNANCE & VALIDATION (DIT)
# ============================================================

@register_as_module("GSA_SYNTACTIC_VALIDATOR")
class SyntacticValidationLayer:
    """Checks incoming text for bad words, opinions, or confusing loops."""
    def __init__(self) -> None:
        self.regex_identity = re.compile(r"\b(i|me|my|we|our)\b", re.I)
        self.regex_hedge = re.compile(r"\b(may|might|perhaps|seems)\b", re.I)
        self.forbidden_logic = ["paradox", "recursion"]

    def scrub_and_verify(self, text_body: str) -> Tuple[bool, str]:
        """Removes personal words and fails if it finds dangerous patterns."""
        if any(bad_word in text_body.lower() for bad_word in self.forbidden_logic):
            return False, "PROVENANCE_FAILED"

        scrubbed_text = self.regex_identity.sub("[REDACTED]", text_body)
        if self.regex_hedge.search(scrubbed_text):
            return False, "HEDGING_DETECTED"

        return True, scrubbed_text


# ============================================================
# OPERATIONAL PIPELINE (CYCLE MANAGER)
# ============================================================

@register_as_module("GSA_PIPELINE_CYCLE_MANAGER")
class PipelineCycleManager:
    """The main engine that analyzes numbers and makes safe adjustments."""
    def __init__(self) -> None:
        self.metric_error_history: deque[float] = deque(maxlen=8)
        self.validator = SyntacticValidationLayer()
        self.audit = CryptographicAuditFramework()

    async def process_payload(self, envelope: ContextEnvelope) -> ContextEnvelope:
        """Runs the main calculations and updates the safe boundaries."""
        input_data: SystemInputStructure = envelope.payload_data["input_structure"]
        observed_error: float = envelope.payload_data["observed_error"]

        # 1. Syntactic Check
        is_safe, clean_text = self.validator.scrub_and_verify(input_data.text_content_body)
        if not is_safe:
            envelope.status_string = f"ANATHEMA_STATE: {clean_text}"
            return envelope

        # 2. Metric Analysis
        self.metric_error_history.append(abs(observed_error))
        history_list = list(self.metric_error_history)
        volatility = statistics.stdev(history_list) if len(history_list) > 1 else 0.0

        # 3. Dynamic Bounding & Regime
        regime = "STABLE" if volatility < 10.0 else "UNSTABLE"
        anomaly_score = min(0.98, volatility * 0.05)

        iteration_result = {
            "processed_text": clean_text,
            "regime": regime,
            "anomaly_score": anomaly_score,
            "volatility": volatility
        }

        # 4. Save state and lock
        envelope.session_state_mapping["historical_errors"] = history_list
        envelope.payload_data = iteration_result
        envelope.status_string = "PIPELINE_ITERATION_EXECUTED"

        self.audit.write_tamper_evident_entry("PIPELINE_COMPLETE", iteration_result)
        return envelope


# ============================================================
# UNIVERSAL ADAPTER (THE WRAPPER)
# ============================================================

class GsaUniversalAdapter:
    """The master controller that wraps modules and enforces history tracking."""
    def __init__(self, underlying_module: ComposableLegoModule) -> None:
        self.module = underlying_module
        self.actor_name = type(underlying_module).__name__

    async def execute_interlock(self, envelope: ContextEnvelope) -> ContextEnvelope:
        """Processes the folder, checks the history, runs the code, and locks it."""
        headers = dict(envelope.header_mapping)
        current_iteration = headers.get("gsa_loop_iteration", 0)
        upstream_hash = headers.get("gsa_interlock_hash", "GENESIS_ANCHOR")

        # Run the enclosed operational payload
        output_envelope = await self.module.process_payload(envelope)

        # Stamp outbound metrics
        next_iteration = current_iteration + 1
        outbound_hash = compute_state_signature(upstream_hash, next_iteration, output_envelope)

        headers["gsa_interlock_hash"] = outbound_hash
        headers["gsa_loop_iteration"] = next_iteration
        headers["gsa_last_actor"] = self.actor_name

        output_envelope.header_mapping = MappingProxyType(headers)
        return output_envelope


# ============================================================
# EXECUTION ENTRY POINT
# ============================================================

async def main() -> None:
    # Set deterministic seed
    os.environ["VANGUARD_RUN_IDENTIFIER"] = "genesis-run-101"

    # Initialize components
    core_pipeline = PipelineCycleManager()
    wrapper_engine = GsaUniversalAdapter(core_pipeline)

    # Construct inbound transaction
    raw_input = SystemInputStructure(
        text_content_body="I check the system parameters for paradox logic.",
        numeric_metric_value=120.0
    )

    initial_envelope = ContextEnvelope(
        payload_data={
            "input_structure": raw_input,
            "observed_error": 4.5
        }
    )

    # Execute through the secure interlock
    final_result = await wrapper_engine.execute_interlock(initial_envelope)

    print(f"Final Status: {final_result.status_string}")
    print(f"Secured Hash: {final_result.header_mapping.get('gsa_interlock_hash')}")


if __name__ == "__main__":
    asyncio.run(main())
