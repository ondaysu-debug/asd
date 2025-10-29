from __future__ import annotations

from typing import Dict, Set

# Native addresses per chain (EVM lowercased; Solana original casing)
NATIVE_ADDR: Dict[str, Set[str]] = {
    "base": {"0x4200000000000000000000000000000000000006"},  # WETH (Base)
    "ethereum": {"0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"},  # WETH (ETH)
    "solana": {"So11111111111111111111111111111111111111112"},  # SOL
}

# Symbols considered native/majors/mimics to exclude as TOKEN side
MAJOR_BASE_SYMBOLS: Set[str] = {
    "USDC",
    "USDT",
    "DAI",
    "WBTC",
    "BTC",
    "TETHER",
    "CIRCLE",
    "ETH",
    "WETH",
    "ETHEREUM",
    "SOL",
    "SOLANA",
    "BASE",
    "STETH",
    "WSTETH",
    "USDCE",
    "USDTE",
}

NATIVE_SYMBOLS: Dict[str, Set[str]] = {
    "base": {"BASE", "ETH", "WETH", "ETHEREUM"},
    "ethereum": {"ETH", "WETH", "ETHEREUM"},
    "solana": {"SOL", "SOLANA"},
}
