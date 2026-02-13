from __future__ import annotations

from arbbot.exchanges.paradex_auth import build_paradex_auth_candidates, should_retry_with_int_key


def test_build_paradex_auth_candidates_add_int_candidate_for_hex_key() -> None:
    candidates = build_paradex_auth_candidates("0x10", "0xabc")

    assert len(candidates) == 2
    assert candidates[0].key_mode == "string"
    assert candidates[0].kwargs["privateKey"] == "0x10"
    assert candidates[1].key_mode == "int"
    assert candidates[1].kwargs["privateKey"] == 16
    assert candidates[1].kwargs["options"]["paradexAccount"]["privateKey"] == 16


def test_build_paradex_auth_candidates_keep_single_candidate_for_non_hex_key() -> None:
    candidates = build_paradex_auth_candidates("not-hex", "0xabc")

    assert len(candidates) == 1
    assert candidates[0].key_mode == "string"


def test_should_retry_with_int_key_on_type_error_message() -> None:
    assert should_retry_with_int_key(TypeError("%x format: an integer is required, not str"))
    assert should_retry_with_int_key(ValueError("integer is required"))
    assert not should_retry_with_int_key(RuntimeError("network timeout"))

