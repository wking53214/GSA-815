"""
Program Name: GSA_Universal_Cryptographic_Interlock_Engine
Description: A production-grade middleware core providing cryptographic state 
            attestation, non-linear graph traversal, and temporal boundary 
            locking for unified governance pipelines.
Version-Control-ID: 7a8f9c2d1e0b3a5e9f8c6d4b2a1e0f8c
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from types import MappingProxyType
from typing import Any, Callable, Dict, Final, List, Optional, Protocol, Union

# ============================================================
# DIAGNOSTIC/REPAIR LOG:
# 1. Identified broken structural typing on the Protocol interface.
#    Fix: Applied explicit Protocol signature alignment.
# 2. Identified potential memory leak in header tracking keys.
#    Fix: Implemented explicit popping of branch IDs upon convergence.
# 3. Fixed circular import vulnerability during structural freeze.
#    Fix: Decoupled serialization logic into local utility blocks.
# ============================================================

# ============================================================
# PROTOCOLS & CORE COMPLIANCE INTERFACES
# ============================================================
class GovernanceModuleInterface(Protocol):
   """Defines the unified asynchronous footprint required for all GSA system components."""
   async def execute_governance_logic(self, context_envelope: Any) -> Any:
       ...

# ============================================================
# CRYPTOGRAPHIC DETERMINISTIC STATE CALCULATION UTILITIES
# ============================================================
def generate_deterministic_state_hash(
   parent_hash: str, 
   iteration_index: int, 
   payload_envelope: Any, 
   anchor_registry: Optional[List[str]] = None
) -> str:
   """
   Computes a deterministic SHA-256 block hash incorporating the linear history,
   iteration sequences, graph convergence arrays, payload data, and state schemas.
   """
   serialized_payload = json.dumps(payload_envelope.payload_data, sort_keys=True, default=str)
   serialized_session = json.dumps(payload_envelope.session_state_mapping, sort_keys=True, default=str)
   
   sorted_anchors = "||".join(sorted(anchor_registry)) if anchor_registry else "NONE"
   
   buffer_source = (
       f"parent:{parent_hash}||"
       f"iter:{iteration_index}||"
       f"graph:[{sorted_anchors}]||"
       f"payload:{serialized_payload}||"
       f"session:{serialized_session}"
   )
   
   return hashlib.sha256(buffer_source.encode("utf-8")).hexdigest()

# ============================================================
# UNIVERSAL CRYPTOGRAPHIC ADAPTER (THE WRAPPER ENGINE)
# ============================================================
class UniversalAdapterEngine:
   """
   The Universal Adapter wrapper. Encloses any synchronous or asynchronous GSA module,
   enforcing linear, cyclical, fork-join, static anchor, and temporal doorway controls.
   """
   def __init__(
       self, 
       governance_module: Any, 
       translation_bridge: Optional[Callable[[Any, Any], Any]] = None
   ) -> None:
       self.module = governance_module
       self.bridge = translation_bridge or (lambda m, env: env)
       self.component_identifier = type(governance_module).__name__

   async def process_payload(self, context_envelope: Any) -> Any:
       """Processes the envelope data layer, managing the structural state ledger."""
       headers = dict(context_envelope.header_mapping)
       chain_history = list(headers.get("gsa_chain_history", []))
       graph_forks = dict(headers.get("gsa_graph_forks", {}))
       static_anchors = dict(headers.get("gsa_static_anchors", {}))
       
       loop_iteration = headers.get("gsa_loop_iteration", 0)
       reentry_target_id = headers.get("gsa_reentry_target_id")
       
       upstream_hash = "GENESIS_ANCHOR"
       convergence_branch_keys: List[str] = []
       branch_hash_list: List[str] = []

       # --------------------------------------------------------
       # PHASE 1: INBOUND VERIFICATION & ROUTING
       # --------------------------------------------------------
       if reentry_target_id and reentry_target_id in static_anchors:
           saved_anchor = static_anchors[reentry_target_id]
           provided_hash = headers.get("gsa_interlock_hash")
           
           if provided_hash != saved_anchor:
               return replace(context_envelope, status_string="GSA_ANCHOR_MISMATCH")
           
           headers.pop("gsa_reentry_target_id", None)
           upstream_hash = saved_anchor
       else:
           convergence_branch_keys = [k for k, v in graph_forks.items() if v == self.component_identifier]
           if convergence_branch_keys:
               branch_hash_list = [headers.get(f"gsa_branch_hash_{k}", "") for k in convergence_branch_keys]
               upstream_hash = "||".join(branch_hash_list)
               for k in convergence_branch_keys:
                   graph_forks.pop(k, None)
                   headers.pop(f"gsa_branch_hash_{k}", None)
           else:
               upstream_hash = chain_history[-1] if chain_history else "GENESIS_ANCHOR"
               if chain_history:
                   provided_hash = headers.get("gsa_interlock_hash")
                   prior_anchor = chain_history[-2] if len(chain_history) > 1 else "GENESIS_ANCHOR"
                   expected_hash = generate_deterministic_state_hash(prior_anchor, loop_iteration, context_envelope)
                   if provided_hash != expected_hash:
                       return replace(context_envelope, status_string="GSA_CHAIN_BREAK")

       headers["gsa_graph_forks"] = graph_forks
       working_envelope = replace(context_envelope, header_mapping=MappingProxyType(headers))

       # --------------------------------------------------------
       # PHASE 2: EXECUTION OVER INTERFACE BOUNDARY
       # --------------------------------------------------------
       if hasattr(self.module, "execute_governance_logic"):
           output_envelope = await self.module.execute_governance_logic(working_envelope)
       else:
           loop = asyncio.get_event_loop()
           output_envelope = await loop.run_in_executor(None, self.bridge, self.module, working_envelope)

       # --------------------------------------------------------
       # PHASE 3: STAMPING & LOCKING
       # --------------------------------------------------------
       outbound_headers = dict(output_envelope.header_mapping)
       static_anchor_trigger = outbound_headers.pop("gsa_set_static_anchor_id", None)
       next_iteration = loop_iteration + 1
       
       final_hash = generate_deterministic_state_hash(
           upstream_hash, next_iteration, output_envelope, 
           anchor_registry=branch_hash_list if convergence_branch_keys else None
       )
       
       chain_history.append(final_hash)
       if static_anchor_trigger:
           static_anchors[static_anchor_trigger] = final_hash
           outbound_headers["gsa_interlock_hash"] = final_hash
       else:
           outbound_headers["gsa_interlock_hash"] = final_hash

       outbound_headers.update({
           "gsa_chain_history": chain_history,
           "gsa_static_anchors": static_anchors,
           "gsa_loop_iteration": next_iteration,
           "gsa_last_actor": self.component_identifier
       })
       
       return replace(output_envelope, header_mapping=MappingProxyType(outbound_headers))

# ============================================================
# STANDALONE EXIT DOORWAY MODULE (TEMPORAL INTERLOCK)
# ============================================================
class TemporalBoundaryGate:
   """Holds execution until external synchronization conditions match internal timing."""