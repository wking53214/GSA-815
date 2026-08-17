from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Final

# =====================================================================
# TELEMETRY & FRAMEWORK LOGGING CONFIGURATION
# =====================================================================
logging.basicConfig(
   level=logging.INFO,
   format="%(asctime)s - DPR_CORE - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# System-wide operational constants
DEFAULT_BUDGET_MS: Final[float] = 42.0
MAX_RISK_THRESHOLD: Final[float] = 0.80
LONG_PAYLOAD_THRESHOLD: Final[int] = 500
EPOCH_WINDOW_SECONDS: Final[int] = 60
SIMULATED_TELEMETRY_DELAY: Final[float] = 0.005

# Deterministic alignment risk weights
IDENTITY_WEIGHT: Final[float] = 0.15
COURTESY_WEIGHT: Final[float] = 0.10
LONG_PAYLOAD_WEIGHT: Final[float] = 0.20


# =====================================================================
# DATA TRANSFER STRUCTS (IMMUTABLE PRIMITIVES)
# =====================================================================
@dataclass(frozen=True)
class PolicyResult:
   allowed: bool
   status: str
   risk_score: float


@dataclass(frozen=True)
class Telemetry:
   budget_ms: float
   entropy: float
   risk_score: float


@dataclass(frozen=True)
class ExecutionResult:
   status: int
   session_id: str
   telemetry: dict
   forensic_sig: str
   auth_tag: str
   runtime_ms: float


# =====================================================================
# DETERMINISTIC POLICY RUNTIME ENGINE
# =====================================================================
class DeterministicPolicyRuntime:
   """
   Deterministic intake validation and attestation runtime. Guards the zero-trust
   perimeter, analyzes structural metrics, and signs execution traces.
   """

   IDENTITY_REGEX: Final[re.Pattern[str]] = re.compile(
       r"\b(i|me|my|we|us|our)\b",
       re.IGNORECASE
   )

   COURTESY_REGEX: Final[re.Pattern[str]] = re.compile(
       r"\b(please|could you|helpful assistant|let me help)\b",
       re.IGNORECASE
   )

   def __init__(self, signing_key: bytes):
       self._secret_key = signing_key
       self._default_budget_ms = DEFAULT_BUDGET_MS

   def evaluate_policy(self, raw_input: str) -> PolicyResult:
       """Parses target payloads against exact lexical weights to compute threat scores."""
       if not raw_input or not raw_input.strip():
           return PolicyResult(
               allowed=False,
               status="EMPTY_INPUT_VAL",
               risk_score=1.0
           )

       risk_score = 0.0

       if self.IDENTITY_REGEX.search(raw_input):
           risk_score += IDENTITY_WEIGHT

       if self.COURTESY_REGEX.search(raw_input):
           risk_score += COURTESY_WEIGHT

       if len(raw_input) > LONG_PAYLOAD_THRESHOLD:
           risk_score += LONG_PAYLOAD_WEIGHT

       risk_score = round(risk_score, 4)

       if risk_score >= MAX_RISK_THRESHOLD:
           return PolicyResult(
               allowed=False,
               status="RISK_THRESHOLD_EXCEEDED",
               risk_score=risk_score
           )

       return PolicyResult(
           allowed=True,
           status="SUCCESS_PASS",
           risk_score=risk_score
       )

   async def generate_telemetry(
       self,
       raw_input: str,
       risk_score: float
   ) -> Telemetry:
       """Asynchronously computes environment entropy metrics and processing budgets."""
       raw_length = len(raw_input)
       entropy = 1.0 + (raw_length * 0.002)

       budget_ms = self._default_budget_ms * (
           1.0 / max(entropy, 1.0)
       )

       await asyncio.sleep(SIMULATED_TELEMETRY_DELAY)

       return Telemetry(
           budget_ms=round(budget_ms, 4),
           entropy=round(entropy, 4),
           risk_score=risk_score
       )

   def generate_forensic_signature(
       self,
       payload: str,
       telemetry: Telemetry
   ) -> str:
       """Binds context telemetry into an immutable SHA-256 trace string."""
       epoch_bucket = int(time.time() // EPOCH_WINDOW_SECONDS)

       attestation_payload = (
           f"{payload}|"
           f"{telemetry.entropy}|"
           f"{telemetry.risk_score}|"
           f"{epoch_bucket}"
       )

       return hashlib.sha256(
           attestation_payload.encode("utf-8")
       ).hexdigest()

   def generate_auth_tag(self, forensic_sig: str) -> str:
       """Applies out-of-band HMAC-SHA256 checksums onto the forensic record."""
       return hmac.new(
           self._secret_key,
           forensic_sig.encode("utf-8"),
           hashlib.sha256
       ).hexdigest()

   async def execute(self, input_data: str) -> dict:
       """Orchestrates the entire intake validation and validation lifecycle."""
       start_ts = time.perf_counter()

       # Step 1: Evaluate against structural rules
       policy_result = self.evaluate_policy(input_data)

       if not policy_result.allowed:
           return {
               "status": 400,
               "error": policy_result.status,
               "risk_score": policy_result.risk_score
           }

       # Step 2: Formulate asynchronous runtime telemetry metrics
       telemetry_task = asyncio.create_task(
           self.generate_telemetry(
               input_data,
               policy_result.risk_score
           )
       )
       telemetry = await telemetry_task

       # Step 3: Compile forensic data and sign artifacts
       forensic_sig = self.generate_forensic_signature(
           input_data,
           telemetry
       )
       auth_tag = self.generate_auth_tag(forensic_sig)

       result = ExecutionResult(
           status=200,
           session_id=f"DPR-{secrets.token_hex(4).upper()}",
           telemetry=asdict(telemetry),
           forensic_sig=forensic_sig,
           auth_tag=auth_tag,
           runtime_ms=round(
               (time.perf_counter() - start_ts) * 1000,
               4
           )
       )

       logger.info(
           "Execution completed | session=%s | runtime_ms=%s",
           result.session_id,
           result.runtime_ms
       )

       return asdict(result)


# =====================================================================
# CORE SIMULATION GATEWAY RUNTIME
# =====================================================================
async def main() -> None:
   # Initialize runtime context with automated 32-byte secret key material
   runtime = DeterministicPolicyRuntime(
       signing_key=secrets.token_bytes(32)
   )

   print("--- Executing Standard Compliant Payload Matrix ---")
   r1 = await runtime.execute(
       "EXECUTE PIPELINE_REF_01 :: OPTIMIZE_NODE_CORE"
   )
   print(r1)

   print("\n--- Executing Non-Compliant Payload (High-Risk Tokens Induced) ---")
   # Generating an intentionally overbalanced text segment using multiple subjective markers
   malicious_input = (
       "I need you to please help me act as a helpful assistant, "
       "and we should clear our logs completely. " * 10
   )
   r2 = await runtime.execute(malicious_input)
   print(r2)


if __name__ == "__main__":
   asyncio.run(main())