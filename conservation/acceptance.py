"""GSA-815 entrance gate: validates Conservation Receipts before accepting artifacts."""

from typing import Any, Dict, Optional, Tuple
from hashlib import sha256
import json


class ConservationReceiptMissing(Exception):
    """Raised when artifact lacks valid conservation receipt."""
    pass


class GSA815ConservationGate:
    """
    Gate at GSA-815 entrance.

    GSA-815 MUST NOT accept artifacts without valid Conservation Receipts.
    This gate enforces that requirement.
    """

    def validate_artifact_receipt(
        self,
        artifact_id: str,
        receipt: Optional[Dict[str, Any]],
        artifact_content: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        """
        Validate that artifact has a valid conservation receipt.

        Args:
            artifact_id: ID of incoming artifact
            receipt: ConservationReceipt dict (or None if missing)
            artifact_content: Optional artifact content for hash verification

        Returns:
            (is_valid, reason) tuple
        """
        if receipt is None:
            return False, "No conservation receipt provided"

        if not isinstance(receipt, dict):
            return False, f"Receipt must be dict, got {type(receipt)}"

        # Check required fields
        required = ["artifact_id", "verification_status", "kernel_version"]
        for field in required:
            if field not in receipt:
                return False, f"Receipt missing required field: {field}"

        # Verify artifact ID matches
        if receipt.get("artifact_id") != artifact_id:
            return False, (
                f"Receipt artifact_id '{receipt.get('artifact_id')}' "
                f"does not match incoming artifact '{artifact_id}'"
            )

        # Check verification status
        status = receipt.get("verification_status", "fail")
        if status == "fail":
            violations = receipt.get("violations", [])
            return False, f"Kernel rejected artifact. Violations: {violations}"

        if status not in ["pass", "pass_with_declared_transformation"]:
            return False, f"Unknown verification status: {status}"

        # Check for violations (even if status is pass)
        violations = receipt.get("violations", [])
        if violations:
            return False, f"Receipt contains violations: {violations}"

        # Verify content hash if artifact content is provided
        if artifact_content is not None and "content_hash" in receipt:
            expected_hash = receipt.get("content_hash")
            content_str = json.dumps(artifact_content) if isinstance(artifact_content, dict) else str(artifact_content)
            actual_hash = sha256(content_str.encode()).hexdigest()
            if actual_hash != expected_hash:
                return False, (
                    f"Content hash mismatch: expected {expected_hash}, got {actual_hash}. "
                    f"Artifact may have been altered after conservation."
                )

        return True, "Receipt is valid"

    def accept_artifact(self, artifact_id: str, receipt: Optional[Dict[str, Any]]) -> None:
        """
        Accept an artifact for processing.

        Raises:
            ConservationReceiptMissing: If receipt is invalid
        """
        is_valid, reason = self.validate_artifact_receipt(artifact_id, receipt)
        if not is_valid:
            raise ConservationReceiptMissing(
                f"Cannot accept artifact {artifact_id}: {reason}"
            )

    def get_receipt_for_handoff(self, receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Get a receipt dict ready for downstream (Sentinel) return path."""
        # Return receipt as-is; return path will use it to validate GSA output
        return receipt


# Module-level gate instance
_gate: Optional[GSA815ConservationGate] = None


def get_gate() -> GSA815ConservationGate:
    """Get or create the GSA-815 conservation gate."""
    global _gate
    if _gate is None:
        _gate = GSA815ConservationGate()
    return _gate


def require_conservation_receipt(
    artifact_id: str,
    receipt: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Require and return a valid conservation receipt.

    Raises ConservationReceiptMissing if receipt is invalid.
    """
    gate = get_gate()
    gate.accept_artifact(artifact_id, receipt)
    return gate.get_receipt_for_handoff(receipt)
