"""凭证有效性校验。"""

from __future__ import annotations

from typing import Any

import ccxt.async_support as ccxt  # type: ignore
from pysdk.grvt_ccxt_env import GrvtEnv as GrvtCcxtEnv
from pysdk.grvt_ccxt_pro import GrvtCcxtPro
from pysdk.grvt_raw_async import GrvtRawAsync
from pysdk.grvt_raw_base import GrvtApiConfig, GrvtError
from pysdk.grvt_raw_env import GrvtEnv as GrvtRawEnv
from pysdk.grvt_raw_types import ApiGetAllInitialLeverageRequest

from ..config import AppConfig


def _is_valid_hex_key(value: str) -> bool:
    normalized = value.strip()
    if normalized.startswith(("0x", "0X")):
        normalized = normalized[2:]
    if not normalized:
        return False
    if len(normalized) % 2 != 0:
        return False
    try:
        bytes.fromhex(normalized)
        return True
    except ValueError:
        return False


class CredentialsValidator:
    """严格校验交易所凭证是否可用。"""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def validate(self, credentials: dict[str, dict[str, str]]) -> dict[str, Any]:
        paradex_payload = credentials.get("paradex") if isinstance(credentials.get("paradex"), dict) else {}
        grvt_payload = credentials.get("grvt") if isinstance(credentials.get("grvt"), dict) else {}

        paradex_result = await self._validate_paradex(paradex_payload)
        grvt_result = await self._validate_grvt(grvt_payload)

        ok = bool(paradex_result["valid"] and grvt_result["valid"])
        return {
            "ok": ok,
            "message": "凭证校验通过" if ok else "凭证校验未通过",
            "data": {
                "paradex": paradex_result,
                "grvt": grvt_result,
            },
        }

    async def _validate_paradex(self, payload: dict[str, str]) -> dict[str, Any]:
        checks: dict[str, bool] = {
            "required_fields": False,
            "load_markets": False,
            "fetch_balance": False,
            "fetch_positions": False,
        }

        l2_private_key = str(payload.get("l2_private_key") or "").strip()
        l2_address = str(payload.get("l2_address") or "").strip()
        if not l2_private_key or not l2_address:
            return {
                "valid": False,
                "reason": "Paradex 缺少必填字段：l2_private_key/l2_address",
                "checks": checks,
            }

        checks["required_fields"] = True

        client = ccxt.paradex(
            {
                "enableRateLimit": True,
                "walletAddress": l2_address,
                "privateKey": l2_private_key,
                "options": {
                    "paradexAccount": {
                        "privateKey": l2_private_key,
                        "address": l2_address,
                    }
                },
            }
        )

        try:
            await client.load_markets()
            checks["load_markets"] = True

            await client.fetch_balance()
            checks["fetch_balance"] = True

            target_market = self._config.symbols[0].paradex_market if self._config.symbols else "BTC/USD:USDC"
            await client.fetch_positions([target_market])
            checks["fetch_positions"] = True

            return {
                "valid": True,
                "reason": "Paradex 凭证有效",
                "checks": checks,
            }
        except Exception as exc:
            return {
                "valid": False,
                "reason": f"Paradex 校验失败: {exc}",
                "checks": checks,
            }
        finally:
            await client.close()

    async def _validate_grvt(self, payload: dict[str, str]) -> dict[str, Any]:
        checks: dict[str, bool] = {
            "required_fields": False,
            "load_markets": False,
            "fetch_positions": False,
            "fetch_max_leverage": False,
        }

        api_key = str(payload.get("api_key") or "").strip()
        private_key = str(payload.get("private_key") or "").strip()
        trading_account_id = str(payload.get("trading_account_id") or "").strip()

        if not api_key or not private_key or not trading_account_id:
            return {
                "valid": False,
                "reason": "GRVT 缺少必填字段：api_key/private_key/trading_account_id",
                "checks": checks,
            }

        checks["required_fields"] = True
        if not _is_valid_hex_key(private_key):
            return {
                "valid": False,
                "reason": "GRVT private_key 格式错误：必须是十六进制字符串（可带 0x 前缀）",
                "checks": checks,
            }

        ccxt_client = GrvtCcxtPro(
            env=self._resolve_grvt_ccxt_env(),
            parameters={
                "trading_account_id": trading_account_id,
                "private_key": private_key,
                "api_key": api_key,
            },
        )

        try:
            await ccxt_client.load_markets()
            checks["load_markets"] = True

            target_market = self._config.symbols[0].grvt_market if self._config.symbols else "BTC_USDT_Perp"
            await ccxt_client.fetch_positions([target_market])
            checks["fetch_positions"] = True
        except Exception as exc:
            session = getattr(ccxt_client, "_session", None)
            if session is not None and not session.closed:
                await session.close()
            return {
                "valid": False,
                "reason": f"GRVT 私有接口校验失败: {exc}",
                "checks": checks,
            }

        session = getattr(ccxt_client, "_session", None)
        if session is not None and not session.closed:
            await session.close()

        raw_client = GrvtRawAsync(
            GrvtApiConfig(
                env=self._resolve_grvt_raw_env(),
                trading_account_id=trading_account_id,
                private_key=private_key,
                api_key=api_key,
                logger=None,
            )
        )

        try:
            response = await raw_client.get_all_initial_leverage_v1(
                ApiGetAllInitialLeverageRequest(sub_account_id=trading_account_id)
            )
            if isinstance(response, GrvtError):
                return {
                    "valid": False,
                    "reason": f"GRVT 杠杆接口失败: {response.code} {response.message}",
                    "checks": checks,
                }

            checks["fetch_max_leverage"] = len(response.results) > 0
            if not checks["fetch_max_leverage"]:
                return {
                    "valid": False,
                    "reason": "GRVT 杠杆接口返回为空",
                    "checks": checks,
                }

            return {
                "valid": True,
                "reason": "GRVT 凭证有效",
                "checks": checks,
            }
        except Exception as exc:
            return {
                "valid": False,
                "reason": f"GRVT 杠杆校验异常: {exc}",
                "checks": checks,
            }
        finally:
            session = getattr(raw_client, "_session", None)
            if session is not None and not session.closed:
                await session.close()

    def _resolve_grvt_ccxt_env(self) -> GrvtCcxtEnv:
        env = self._config.grvt.environment.lower().strip()
        if env == "testnet":
            return GrvtCcxtEnv.TESTNET
        if env == "staging":
            return GrvtCcxtEnv.STAGING
        if env == "dev":
            return GrvtCcxtEnv.DEV
        return GrvtCcxtEnv.PROD

    def _resolve_grvt_raw_env(self) -> GrvtRawEnv:
        env = self._config.grvt.environment.lower().strip()
        if env == "testnet":
            return GrvtRawEnv.TESTNET
        if env == "staging":
            return GrvtRawEnv.STAGING
        if env == "dev":
            return GrvtRawEnv.DEV
        return GrvtRawEnv.PROD
