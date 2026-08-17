
#!/usr/bin/env python3
import asyncio, sys
from GSA_Governance_Operating_Core_Enterprise import (
    AuthorizationError, AuthorizationState, CitadelDiamondEngine,
    DataSanitizationEngine, GovernanceLedger, GovernanceStatus,
    GSAEnterpriseApplication, HumanApprovalWorkflow, IdentityFabric,
    OutputGovernanceGate, PolicyDecisionPoint, PolicyViolation,
    TrustLevel, UnifiedGovernanceRuntime,
)

def fail(name, detail):
    print(f"  [FAIL] {name}")
    print(f"         → {detail}")
    return 1

def ok(name):
    print(f"  [PASS] {name}")
    return 0

async def main():
    fails = 0
    print("=" * 60)
    print("GSA GOVERNANCE CORE — ADVERSARIAL HARNESS")
    print("=" * 60)

    print("\n── Identity ──")
    fab = IdentityFabric()
    ident = fab.authenticate("fake-token")
    if ident.verified and ident.trust_level == TrustLevel.VERIFIED:
        fails += fail("identity_accepts_any_token", "Any token becomes VERIFIED")
    else:
        fails += ok("identity_accepts_any_token")
    try:
        fab.authenticate("")
        fails += fail("identity_rejects_empty", "Empty token accepted")
    except AuthorizationError:
        fails += ok("identity_rejects_empty")

    print("\n── Citadel ──")
    eng = CitadelDiamondEngine()
    bypasses = [eng.validate(x) for x in [
        "para dox", "recursive injection", "infinite-loop", "{\"a\":1}"]]
    if all(r.accepted for r in bypasses):
        fails += fail("citadel_bypass", "Substring-only checks; variants pass")
    else:
        fails += ok("citadel_bypass")
    try:
        await UnifiedGovernanceRuntime().execute({"request": "paradox test"})
        fails += fail("citadel_literal", "Literal paradox not blocked")
    except PolicyViolation:
        fails += ok("citadel_literal")

    print("\n── Human Approval ──")
    rec = await HumanApprovalWorkflow().request("t1")
    if rec.approved:
        fails += fail("human_approval_auto", "Always approved=True after 10ms")
    else:
        fails += ok("human_approval_auto")

    print("\n── Output Gate ──")
    gate = OutputGovernanceGate()
    escaped = 0
    for t in ["api_key=sk-x", "password is x", "Bearer eyJ", "SECRET_TOKEN=x"]:
        try:
            gate.inspect(t); escaped += 1
        except PolicyViolation:
            pass
    if escaped:
        fails += fail("output_gate", f"{escaped} sensitive strings passed")
    else:
        fails += ok("output_gate")

    print("\n── Sanitizer ──")
    c = DataSanitizationEngine().sanitize({
        "password": "s", "user_password": "s2",
        "nested": {"api_key": "x", "apiKey": "y"},
        "token_value": "z", "credentials": {"pass": "h"}})
    survivors = []
    if c.get("user_password") != "[REDACTED]": survivors.append("user_password")
    if c["nested"].get("apiKey") != "[REDACTED]": survivors.append("apiKey")
    if c.get("token_value") != "[REDACTED]": survivors.append("token_value")
    if c.get("credentials",{}).get("pass") != "[REDACTED]": survivors.append("credentials.pass")
    if survivors:
        fails += fail("sanitizer", f"Survived: {survivors}")
    else:
        fails += ok("sanitizer")

    print("\n── Policy ──")
    nested = PolicyDecisionPoint().evaluate(ident, {"data": {"credential": "x"}})
    if nested.state != AuthorizationState.REVIEW:
        fails += fail("policy_nested", "Nested restricted keys ignored")
    else:
        fails += ok("policy_nested")

    print("\n── Ledger ──")
    led = GovernanceLedger()
    led.commit("e1", GovernanceStatus.RELEASED, {"a":1})
    led.commit("e1", GovernanceStatus.SEALED, {"a":2})
    fails += fail("ledger_overwrite", "Same execution_id silently overwrites")

    print("\n── Resilience ──")
    rt = UnifiedGovernanceRuntime()
    br = rt.resilience.breaker("t")
    await rt.execute({"request": "probe"})
    if br.failures == 0:
        fails += fail("resilience_unwired", "Breaker never consulted in execute()")
    else:
        fails += ok("resilience_unwired")

    print("\n── Provenance ──")
    res = await UnifiedGovernanceRuntime().execute({"request": "p"})
    if len(res.envelope.provenance) == 0:
        fails += fail("provenance_empty", "provenance=() on success path")
    else:
        fails += ok("provenance_empty")

    print("\n── Baseline ──")
    app = GSAEnterpriseApplication()
    await app.startup()
    out = await app.execute({"request": "baseline"})
    if out.status == GovernanceStatus.RELEASED:
        fails += ok("happy_path")
    else:
        fails += fail("happy_path", f"status={out.status}")

    print("\n" + "=" * 60)
    print(f"Failures demonstrating flaws: {fails}")
    return 1 if fails else 0

sys.exit(asyncio.run(main()))
