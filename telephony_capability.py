"""The telephony_ingest capability contract, owned by GSA-815.

The kernel is domain-blind; phone-call ingest is this application's
business. Importing this module registers the capability with the
kernel's validator (cassette_capabilities.CAPABILITIES) so a cassette
that declares "telephony_ingest" still validates. Registration is
idempotent: against a kernel that still ships its own copy, the
kernel's entry is left in place.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple

from cassette_capabilities import (
    CAPABILITIES,
    CAPABILITY_TELEPHONY_INGEST,
    PARAMETER_OWNERS,
)


class TelephonyIngest(ABC):
    """Contract for domains that ingest phone calls.

    Owns the ingest thresholds AND the call-shaped judgment surface.
    A domain that enables this capability judges calls with the fixed
    (resolved, duration, friction_count, emotion_data) signature; a
    domain that doesn't is judged only through the kernel's
    judge(episode) and never has to fake call-center parameters.
    """

    NAME = CAPABILITY_TELEPHONY_INGEST
    REQUIRED_PARAMETERS: Dict[str, str] = {
        # A wait longer than this, at any node, is one friction event.
        "long_wait_threshold": "float",
        # Twilio ingest: calls longer than this contribute 2 friction points.
        "twilio_long_duration_threshold": "int",
        # Twilio ingest: calls longer than this contribute 1 friction point.
        "twilio_medium_duration_threshold": "int",
        # Twilio ingest: non-completed calls shorter than this are dropped-call friction.
        "twilio_short_duration_threshold": "int",
    }
    REQUIRED_METHODS: Tuple[str, ...] = (
        "score_outcome_quality",
        "diagnose_abandonment",
        "get_friction_thresholds",
    )

    @abstractmethod
    def score_outcome_quality(self, resolved: bool, duration: float,
                              friction_count: int, emotion_data: Dict):
        """Score one call with this domain's own rules; returns
        QualityResult (the cassette owns score arithmetic AND tier
        cutoffs -- see cassette_interface.QualityResult)."""

    @abstractmethod
    def diagnose_abandonment(self, journey: List[str], friction: List,
                             emotion: Dict, resolved: bool) -> Dict:
        """Name, in domain vocabulary, why a call abandoned."""

    @abstractmethod
    def get_friction_thresholds(self) -> Dict[str, float]:
        """Domain-specific friction detection thresholds."""


def register() -> None:
    """Make the kernel's validator know this capability. Safe to repeat."""
    CAPABILITIES.setdefault(TelephonyIngest.NAME, TelephonyIngest)
    for param in TelephonyIngest.REQUIRED_PARAMETERS:
        PARAMETER_OWNERS.setdefault(param, TelephonyIngest.NAME)


register()
