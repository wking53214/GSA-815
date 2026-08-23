"""
GSA-815 ← PERCEIVE Gate Integration

Enforces that GSA-815 operations only execute with PERCEIVE approval.
Prevents any bypass of governance orchestrator.
"""

import sys
import os

# Add observe-perceive to path for import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..', 'observe-perceive'))

from governance_contracts import ExecutionApproval, GovernanceApproval


class PerceiveGate:
    """Enforces PERCEIVE approval for all GSA-815 operations."""

    @staticmethod
    def require_perceive_approval(execution_approval: ExecutionApproval) -> bool:
        """
        Verify that PERCEIVE has approved this operation.

        Args:
            execution_approval: The ExecutionApproval from governance flow

        Returns:
            True if approved

        Raises:
            Exception if not approved (fail-closed)
        """
        # Fail closed if not approved
        if execution_approval.approval != GovernanceApproval.APPROVED:
            raise Exception(
                f"PERCEIVE approval required: {execution_approval.approval.value}"
            )

        # Verify conservation decision is present
        if not execution_approval.conservation_decision_id:
            raise Exception("Missing conservation decision ID")

        if not execution_approval.conservation_receipt_id:
            raise Exception("Missing conservation receipt ID")

        # Verify audit hashes are present
        if not execution_approval.governance_audit_hash:
            raise Exception("Missing governance audit hash")

        if not execution_approval.conservation_audit_hash:
            raise Exception("Missing conservation audit hash")

        return True

    @staticmethod
    def gate_operation(execution_approval: ExecutionApproval, operation_func, *args, **kwargs):
        """
        Execute operation only with valid PERCEIVE approval.

        Args:
            execution_approval: The ExecutionApproval from governance
            operation_func: The GSA-815 operation to execute
            *args: Operation arguments
            **kwargs: Operation keyword arguments

        Returns:
            Operation result

        Raises:
            Exception if approval invalid (fail-closed)
        """
        # Verify approval
        PerceiveGate.require_perceive_approval(execution_approval)

        # Execute operation only after approval verified
        return operation_func(*args, **kwargs)
