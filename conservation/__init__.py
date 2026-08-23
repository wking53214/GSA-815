"""
Conservation Kernel integration for GSA-815.

Ensures GSA-815 accepts only artifacts that have passed Conservation Kernel
verification, and ensures GSA-815 results pass back through the Kernel before
being returned to Sentinel.
"""

from .acceptance import GSA815ConservationGate
from .return_gateway import GSA815ReturnPath

__all__ = [
    "GSA815ConservationGate",
    "GSA815ReturnPath",
]
