"""
Production Harness - Ties all systems together

Real Twilio → Real Prometheus → Real PostgreSQL → Real Claude → Real Governance

The generic governance pipeline lives in governed_pipeline.py and everything
specific to phone calls lives in ivr_pack.py (the first domain pack, see
domain_pack.py). This class is the IVR wrapper around that pipeline: it builds
the IVR working parts (call parser, observer, scorer, metrics, intent learner),
and keeps the names and entry points callers already use.
"""

import os
from typing import Dict

from twilio_log_ingestion import TwilioLogParser, TwilioStreamAdapter
from metrics_prometheus import PrometheusMetrics
from observe_perceive_core import ObserveCore
from sentinel_core import SentinelCore
from queue_staffing_bayes_integration import (
    BayesianIntentEngine
)
from governed_pipeline import GovernedPipeline
from ivr_pack import IvrPack


class IcebergProductionHarness(GovernedPipeline):
    """Complete production system: all components wired together.

    The IVR wrapper: a GovernedPipeline running the IVR domain pack. See
    GovernedPipeline for the construction arguments and the fail-closed
    cassette binding rule.
    """

    def __init__(self, config: Dict, cassette=None,
                 require_cassette_binding: bool = True):
        super().__init__(config, IvrPack(self), cassette=cassette,
                         require_cassette_binding=require_cassette_binding)

    def _init_domain_components(self):
        """Build the IVR working parts the IVR pack reads."""

        # Data sources
        self.twilio_parser = TwilioLogParser(cassette=self.cassette)
        self.twilio_adapter = None  # Will init if API key provided

        # Observability
        self.metrics = PrometheusMetrics()
        self.observer = ObserveCore()
        self.sentinel = SentinelCore(self.cassette)

        # Operations
        self.bayes = BayesianIntentEngine()

    def _init_domain_optional_components(self):
        """Initialize IVR components that require external credentials"""

        # Twilio
        if self.config.get("twilio_account_sid"):
            try:
                self.twilio_adapter = TwilioStreamAdapter(
                    api_key=self.config.get("twilio_api_key", ""),
                    api_secret=self.config.get("twilio_api_secret", ""),
                    account_sid=self.config.get("twilio_account_sid", "")
                )
                print("✓ Twilio log adapter connected")
            except Exception as e:
                print(f"⚠ Twilio not available: {e}")

    def _on_cassette_swapped(self, cassette):
        self.sentinel = SentinelCore(cassette)
        self.twilio_parser.cassette = cassette

    def _assemble_live_episode(self, *args, **kwargs):
        """Kept so existing callers keep working. The logic lives in the IVR pack."""
        return self.pack.assemble_live_episode(*args, **kwargs)

    def process_call(self, twilio_record: Dict) -> Dict:
        """Process one call through complete pipeline"""
        return self.process(twilio_record)

    def process_batch(self, twilio_records: list) -> Dict:
        """Process batch of calls through complete pipeline"""
        
        results = []
        for record in twilio_records:
            result = self.process_call(record)
            results.append(result)
        
        summary = self.metrics.get_summary()
        # calls_total from get_summary() is self.metrics.calls_total -- a
        # cumulative, process-lifetime counter (correct for /metrics, which
        # reports the harness's running totals). Reusing it here as a
        # per-batch figure is wrong: it silently includes every call this
        # harness instance has ever processed, not just this batch, so it
        # drifts from calls_processed (len(results), correctly batch-scoped)
        # by however many calls preceded this batch in the harness's
        # lifetime. Override it to the batch-local count so both fields
        # describe the same scope.
        summary["calls_total"] = len(results)
        summary["calls_processed"] = len(results)
        summary["results"] = results
        
        return summary
    
    def export_metrics(self) -> str:
        """Export Prometheus metrics"""
        return self.metrics.export_prometheus()
    
    def verify_ledger(self) -> Dict:
        """Verify ledger integrity (if connected)"""
        if not self.ledger:
            return {"error": "Ledger not connected"}
        
        return self.ledger.verify_chain(mode="tolerant")
    
    def shutdown(self):
        """Cleanup resources"""
        if self.ledger:
            self.ledger.close()


def _require_env(name: str) -> str:
    """Read a required secret from the environment. There is no default: a
    well-known fallback password would let a misconfigured deployment
    connect with a guessable credential."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def main():
    """Run production harness"""
    
    print("\n" + "="*70)
    print("ICEBERG PRODUCTION HARNESS - END-TO-END INTEGRATION")
    print("="*70)
    
    # Load config from environment
    config = {
        "postgres_host": os.getenv("POSTGRES_HOST", "localhost"),
        "postgres_port": int(os.getenv("POSTGRES_PORT", 5432)),
        "postgres_db": os.getenv("POSTGRES_DB", "iceberg"),
        "postgres_user": os.getenv("POSTGRES_USER", "iceberg"),
        "postgres_password": _require_env("POSTGRES_PASSWORD"),
        "claude_api_key": os.getenv("CLAUDE_API_KEY"),
        "twilio_account_sid": os.getenv("TWILIO_ACCOUNT_SID"),
        "twilio_api_key": os.getenv("TWILIO_API_KEY"),
        "twilio_api_secret": os.getenv("TWILIO_API_SECRET"),
    }
    
    # Initialize harness
    harness = IcebergProductionHarness(config)
    
    # Simulate batch of calls
    print("\n[BATCH 1] Processing 5 calls through production pipeline...")
    
    mock_calls = [
        {"sid": "CA001", "status": "completed", "duration": 120, "from": "+1111", "to": "+billing"},
        {"sid": "CA002", "status": "completed", "duration": 150, "from": "+2222", "to": "+tech"},
        {"sid": "CA003", "status": "no-answer", "duration": 30, "from": "+1111", "to": "+billing"},
        {"sid": "CA004", "status": "completed", "duration": 200, "from": "+3333", "to": "+sales"},
        {"sid": "CA005", "status": "failed", "duration": 10, "from": "+2222", "to": "+tech"},
    ]
    
    summary = harness.process_batch(mock_calls)
    
    print("\n[RESULTS]")
    print(f"  Calls processed: {summary['calls_processed']}")
    print(f"  Total calls: {summary['calls_total']}")
    print(f"  Resolved: {summary['calls_resolved']}")
    print(f"  Abandoned: {summary['calls_abandoned']}")
    print(f"  Abandonment rate: {summary['abandonment_rate']*100:.1f}%")
    print(f"  Avg wait: {summary['avg_wait_time']:.1f}s")
    print(f"  Governance actions: {summary['governance_actions']}")
    
    # Export metrics
    print("\n[PROMETHEUS METRICS]")
    metrics_text = harness.export_metrics()
    print(metrics_text[:500] + "..." if len(metrics_text) > 500 else metrics_text)
    
    # Verify ledger if connected
    if harness.ledger:
        print("\n[LEDGER VERIFICATION]")
        verify = harness.verify_ledger()
        print(f"  Ledger OK: {verify.get('ok')}")
        print(f"  Entries: {verify.get('entries', 0)}")
    
    harness.shutdown()
    
    print("\n" + "="*70)
    print("PRODUCTION HARNESS COMPLETE")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
