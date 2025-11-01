from __future__ import annotations

from typing import Dict, Tuple

from .constants import MAJOR_BASE_SYMBOLS, NATIVE_ADDR, NATIVE_SYMBOLS


def normalize_address(chain: str, address: str | None) -> str:
    if not address:
        return ""
    # Normalize addresses for EVM chains (case-insensitive)
    evm_chains = ("base", "ethereum", "bsc", "polygon", "arbitrum", "optimism", "avalanche")
    return address.lower() if chain in evm_chains else address


def is_token_native_pair(chain: str, base_token: Dict, quote_token: Dict) -> Tuple[bool, Dict, Dict]:
    """
    Convert pair to TOKEN/native if possible and return flag with normalized tokens.
    FIX: More robust token comparison with case normalization
    """
    native_raw = next(iter(NATIVE_ADDR.get(chain, set())), None)
    if not native_raw:
        print(f"[filter][{chain}] No native address defined for chain")
        return False, base_token, quote_token
    
    # FIX: Normalize addresses for comparison
    native_cmp = normalize_address(chain, native_raw)
    b_addr = normalize_address(chain, (base_token.get("address") or ""))
    q_addr = normalize_address(chain, (quote_token.get("address") or ""))

    # FIX: Also check symbols as fallback
    b_symbol = (base_token.get("symbol") or "").upper()
    q_symbol = (quote_token.get("symbol") or "").upper()
    native_symbols = {s.upper() for s in NATIVE_SYMBOLS.get(chain, set())}

    print(f"[filter][{chain}] Checking: {b_symbol}({b_addr})/{q_symbol}({q_addr}) vs native: {native_cmp}, native_symbols: {native_symbols}")

    # Check by address first (most reliable)
    if q_addr == native_cmp and b_addr != native_cmp:
        print(f"[filter][{chain}] ? Native pair by address: {b_symbol}/{q_symbol}")
        return True, base_token, quote_token
    if b_addr == native_cmp and q_addr != native_cmp:
        print(f"[filter][{chain}] ? Native pair by address (swapped): {q_symbol}/{b_symbol}")
        return True, quote_token, base_token
    
    # Fallback: check by symbol
    if q_symbol in native_symbols and b_symbol not in native_symbols:
        print(f"[filter][{chain}] ? Native pair by symbol: {b_symbol}/{q_symbol}")
        return True, base_token, quote_token
    if b_symbol in native_symbols and q_symbol not in native_symbols:
        print(f"[filter][{chain}] ? Native pair by symbol (swapped): {q_symbol}/{b_symbol}")
        return True, quote_token, base_token
        
    print(f"[filter][{chain}] ? Not a native pair: {b_symbol}/{q_symbol}")
    return False, base_token, quote_token


def is_base_token_acceptable(chain: str, token: Dict) -> bool:
    symbol = (token.get("symbol") or "").strip()
    address = normalize_address(chain, (token.get("address") or "").strip())
    
    print(f"[filter][{chain}] Checking base token: {symbol} ({address})")
    
    if not symbol or not address:
        print(f"[filter][{chain}] ? Missing symbol or address")
        return False
        
    if symbol.upper() in MAJOR_BASE_SYMBOLS:
        print(f"[filter][{chain}] ? Symbol in MAJOR_BASE_SYMBOLS: {symbol}")
        return False
        
    native_set = {normalize_address(chain, a) for a in NATIVE_ADDR.get(chain, set())}
    if address in native_set:
        print(f"[filter][{chain}] ? Address is native: {address}")
        return False
        
    if symbol.upper() in NATIVE_SYMBOLS.get(chain, set()):
        print(f"[filter][{chain}] ? Symbol in NATIVE_SYMBOLS: {symbol}")
        return False
        
    print(f"[filter][{chain}] ? Base token accepted: {symbol}")
    return True


def pool_data_filters(liquidity: float, liq_min: float, liq_max: float, tx24h: int, tx24h_max: int) -> bool:
    if not (liq_min <= liquidity <= liq_max):
        return False
    if tx24h > tx24h_max:
        return False
    return True
