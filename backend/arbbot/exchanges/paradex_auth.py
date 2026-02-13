"""Paradex 凭证参数构造与容错。"""

from __future__ import annotations

from dataclasses import dataclass
from string import hexdigits
from typing import Any


@dataclass(slots=True)
class ParadexAuthCandidate:
    """Paradex 客户端凭证候选参数。"""

    kwargs: dict[str, Any]
    key_mode: str


def _parse_private_key_int(raw_key: str) -> int | None:
    normalized = raw_key.strip()
    if not normalized:
        return None

    if normalized.startswith(("0x", "0X")):
        payload = normalized[2:]
        if not payload:
            return None
        if not all(ch in hexdigits for ch in payload):
            return None
        return int(payload, 16)

    if normalized.isdigit():
        return int(normalized, 10)

    if all(ch in hexdigits for ch in normalized):
        return int(normalized, 16)

    return None


def build_paradex_auth_candidates(l2_private_key: str, l2_address: str) -> list[ParadexAuthCandidate]:
    """构建 Paradex 认证候选参数。

    先尝试字符串私钥；若可解析为整数，再追加整数私钥候选，
    以兼容部分签名器对 `%x` 的整数格式要求。
    """

    key = l2_private_key.strip()
    address = l2_address.strip()

    def _build(private_key_value: str | int, key_mode: str) -> ParadexAuthCandidate:
        return ParadexAuthCandidate(
            kwargs={
                "enableRateLimit": True,
                "walletAddress": address,
                "privateKey": private_key_value,
                "options": {
                    "paradexAccount": {
                        "privateKey": private_key_value,
                        "address": address,
                    }
                },
            },
            key_mode=key_mode,
        )

    candidates: list[ParadexAuthCandidate] = [_build(key, "string")]
    as_int = _parse_private_key_int(key)
    if as_int is not None:
        candidates.append(_build(as_int, "int"))
    return candidates


def should_retry_with_int_key(exc: Exception) -> bool:
    """判定异常是否命中私钥类型不兼容，可重试整数私钥。"""

    message = str(exc).lower()
    return "%x format" in message or "integer is required" in message

