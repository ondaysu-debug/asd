from __future__ import annotations

from typing import Dict, Tuple

from .constants import MAJOR_BASE_SYMBOLS, NATIVE_ADDR, NATIVE_SYMBOLS


def normalize_address(chain: str, address: str | None) -> str:
    if not address:
        return ""
    return address.lower() if chain in ("base", "ethereum") else address


def is_token_native_pair(chain: str, base_token: Dict, quote_token: Dict) -> Tuple[bool, Dict, Dict]:
    """
    Convert pair to TOKEN/native if possible and return flag with normalized tokens.
    Returns (True, token_side, native_side) if match found, else (False, base_token, quote_token).
    """
    native_raw = next(iter(NATIVE_ADDR.get(chain, set())), None)
    if not native_raw:
        return False, base_token, quote_token
    native_cmp = normalize_address(chain, native_raw)

    b_addr = normalize_address(chain, (base_token.get("address") or ""))
    q_addr = normalize_address(chain, (quote_token.get("address") or ""))

    if q_addr == native_cmp and b_addr != native_cmp:
        return True, base_token, quote_token
    if b_addr == native_cmp and q_addr != native_cmp:
        return True, quote_token, base_token
    return False, base_token, quote_token


def is_base_token_acceptable(chain: str, token: Dict) -> bool:
    symbol = (token.get("symbol") or "").strip()
    address = normalize_address(chain, (token.get("address") or "").strip())
    if not symbol or not address:
        return False
    if symbol.upper() in MAJOR_BASE_SYMBOLS:
        return False
    native_set = {normalize_address(chain, a) for a in NATIVE_ADDR.get(chain, set())}
    if address in native_set:
        return False
    if symbol.upper() in NATIVE_SYMBOLS.get(chain, set()):
        return False
    return True


def pool_data_filters(liquidity: float, liq_min: float, liq_max: float, tx24h: int, tx24h_max: int) -> bool:
    if not (liq_min <= liquidity <= liq_max):
        return False
    if tx24h > tx24h_max:
        return False
    return True
