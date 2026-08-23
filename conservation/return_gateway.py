"""GSA-815 return path: sends results back through Conservation Kernel."""

from typing import Any, Dict, Optional
from datetime import datetime


class GSA815ReturnPath:
    """
    GSA-815 exit gate: validates that results pass through Kernel before return.

    When GSA-815 produces a result, that result MUST pass through Conservation
    Kernel before being returned to Sentinel. This ensures GSA-815 transformations
    also preserve protected distinctions.
    """

    def __init__(self, kernel_instance: Optional[Any] = None):
        """Initialize return path."""
        self._kernel = kernel_instance
        self._kernel_lazy_loaded = False

    @property
    def kernel(self) -> Any:
        """Lazy-load Conservation Kernel on first use."""
        if self._kernel is None and not self._kernel_lazy_loaded:
            try:
                from conservation_kernel import ConservationKernel
                self._kernel = ConservationKernel()
                self._kernel_lazy_loaded = True
            except ImportError as e:
                raise RuntimeError(
                    "Conservation Kernel not installed. "
                    "Install with: pip install conservation-kernel"
                ) from e
        return self._kernel

    def process_gsa_result(
        self,
        result_id: str,
        result_content: Dict[str, Any],
        input_receipt: Optional[Dict[str, Any]],
        gsa_version: str = "815",
    ) -> Dict[str, Any]:
        """
        Process a GSA-815 result through Conservation Kernel.

        Args:
            result_id: Unique ID for this result
            result_content: The actual result data
            input_receipt: Original receipt that GSA-815 received (for lineage)
            gsa_version: GSA version identifier

        Returns:
            dict with:
                - "accepted": bool (whether Kernel accepted result)
                - "receipt": dict (ConservationReceipt if accepted)
                - "reason": str (if rejected)
        """
        try:
            # Build transformation record for GSA processing
            transformation_record = {
                "transformation_id": f"gsa-{result_id}-{datetime.utcnow().timestamp()}",
                "transformation_kind": "gsa815_governance",
                "input_artifact_ids": (
                    [input_receipt.get("artifact_id")] if input_receipt else []
                ),
                "output_artifact_id": result_id,
                "declared_changes": f"GSA-815 governance processing (v{gsa_version})",
                "actor": "GSA-815",
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

            # Create output artifact
            output_artifact = {
                "artifact_id": result_id,
                "content": result_content,
                "produced_by": "GSA-815",
                "created_at": datetime.utcnow().isoformat() + "Z",
            }

            # If we have input receipt, preserve its chain
            if input_receipt:
                transformation_record["input_artifact_ids"].append(
                    input_receipt.get("artifact_id", "unknown")
                )
                output_artifact["lineage"] = input_receipt.get("lineage", []) + [
                    input_receipt.get("artifact_id", "")
                ]

            # Submit to Kernel
            kernel_result = self.kernel.submit(
                input_artifacts=None,
                output=output_artifact,
                record=transformation_record,
            )

            # Check result
            if hasattr(kernel_result, "accepted"):
                accepted = kernel_result.accepted
            else:
                accepted = kernel_result.get("status") in [
                    "pass",
                    "pass_with_declared_transformation",
                ]

            return {
                "accepted": accepted,
                "receipt": self._to_receipt_dict(kernel_result),
                "reason": "GSA-815 result verified" if accepted else "Kernel rejected GSA result",
            }

        except Exception as e:
            return {
                "accepted": False,
                "receipt": None,
                "reason": f"Failed to process GSA result through Kernel: {e}",
            }

    def _to_receipt_dict(self, kernel_result: Any) -> Dict[str, Any]:
        """Convert Kernel result to receipt dict."""
        if hasattr(kernel_result, "to_dict"):
            return kernel_result.to_dict()
        elif isinstance(kernel_result, dict):
            return kernel_result
        else:
            return {
                "status": getattr(kernel_result, "status", "fail"),
                "transformation_id": getattr(kernel_result, "transformation_id", ""),
            }


# Module-level instance
_return_path: Optional[GSA815ReturnPath] = None


def get_return_path() -> GSA815ReturnPath:
    """Get or create the GSA-815 return path."""
    global _return_path
    if _return_path is None:
        _return_path = GSA815ReturnPath()
    return _return_path


def require_gsa_result_conservation(
    result_id: str,
    result_content: Dict[str, Any],
    input_receipt: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Require GSA-815 result to pass through Conservation Kernel.

    Returns dict with "accepted", "receipt", "reason" keys.
    Raises if result is rejected.
    """
    return_path = get_return_path()
    result = return_path.process_gsa_result(
        result_id=result_id,
        result_content=result_content,
        input_receipt=input_receipt,
    )
    if not result["accepted"]:
        raise RuntimeError(result["reason"])
    return result
