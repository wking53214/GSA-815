"""telephony_capability: GSA-815 owns the telephony_ingest contract and
registers it with the kernel's validator."""
import cassette_capabilities as kernel_caps
from cassette_schema import validate_cassette
from cassettes.ivr_cassette import IvrCassette
import telephony_capability


def test_the_capability_is_registered_with_the_kernel_validator():
    assert kernel_caps.CAPABILITY_TELEPHONY_INGEST in kernel_caps.CAPABILITIES
    cap = kernel_caps.CAPABILITIES[kernel_caps.CAPABILITY_TELEPHONY_INGEST]
    assert set(cap.REQUIRED_PARAMETERS) == set(telephony_capability.TelephonyIngest.REQUIRED_PARAMETERS)


def test_registering_twice_changes_nothing():
    before = dict(kernel_caps.CAPABILITIES), dict(kernel_caps.PARAMETER_OWNERS)
    telephony_capability.register()
    assert (dict(kernel_caps.CAPABILITIES), dict(kernel_caps.PARAMETER_OWNERS)) == before


def test_every_telephony_parameter_has_an_owner():
    for param in telephony_capability.TelephonyIngest.REQUIRED_PARAMETERS:
        assert kernel_caps.PARAMETER_OWNERS[param] == kernel_caps.CAPABILITY_TELEPHONY_INGEST


def test_the_ivr_cassette_is_a_telephony_ingest_and_still_validates():
    cassette = IvrCassette()
    assert isinstance(cassette, telephony_capability.TelephonyIngest)
    validate_cassette(cassette)
