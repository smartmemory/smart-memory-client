"""SEC-AUTH-REVOCATION-1: SmartMemoryClient warns when SMARTMEMORY_API_KEY is a raw JWT.

A raw JWT in the api_key slot is not scoped or revocable per-key; minted
sm_live_/sm_test_ keys are. The client surfaces a DeprecationWarning for the
JWT-shaped value and stays silent for properly-prefixed keys.
"""

import warnings

import pytest

from smartmemory_client import SmartMemoryClient


def test_jwt_shaped_api_key_warns():
    with pytest.warns(DeprecationWarning, match="raw JWT"):
        SmartMemoryClient(api_key="eyJhbGciOiJIUzI1NiJ9.fakepayload.fakesig", base_url="http://localhost:9001")


def test_sm_live_prefixed_key_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)  # any DeprecationWarning → error
        # Must NOT raise: a properly-prefixed key is the recommended form.
        SmartMemoryClient(api_key="sm_live_abcdefghijklmnopqrstuvwxyz123456", base_url="http://localhost:9001")


def test_legacy_sk_key_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        SmartMemoryClient(api_key="sk_legacykey_abcdefghijklmnop", base_url="http://localhost:9001")
