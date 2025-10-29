from wakebot.filters import normalize_address, is_token_native_pair, fdv_tx_filters, is_base_token_acceptable
from wakebot.constants import NATIVE_ADDR


def test_normalize_address_evm_lowercases():
    assert normalize_address("ethereum", "0xABCD") == "0xabcd"
    assert normalize_address("base", "0xABCD") == "0xabcd"
    assert normalize_address("solana", "SoABC") == "SoABC"


def test_is_token_native_pair_detection():
    chain = "ethereum"
    native = next(iter(NATIVE_ADDR[chain]))
    base = {"address": "0xToken", "symbol": "TKN"}
    quote = {"address": native, "symbol": "WETH"}
    ok, token_side, native_side = is_token_native_pair(chain, base, quote)
    assert ok and token_side is base and native_side is quote

    # swapped
    ok, token_side, native_side = is_token_native_pair(chain, quote, base)
    assert ok and token_side is base and native_side is quote

    # not native
    ok, *_ = is_token_native_pair(chain, base, base)
    assert not ok


def test_is_base_token_acceptable_filters_majors_and_natives():
    chain = "ethereum"
    native = next(iter(NATIVE_ADDR[chain]))
    # native address
    assert not is_base_token_acceptable(chain, {"address": native, "symbol": "WETH"})
    # major symbol
    assert not is_base_token_acceptable(chain, {"address": "0xToken1", "symbol": "USDC"})
    # valid
    assert is_base_token_acceptable(chain, {"address": "0xToken2", "symbol": "AAA"})


def test_fdv_tx_filters_range():
    assert fdv_tx_filters(100_000, 50_000, 800_000, 100, 2_000)
    assert not fdv_tx_filters(10_000, 50_000, 800_000, 100, 2_000)
    assert not fdv_tx_filters(900_000, 50_000, 800_000, 100, 2_000)
    assert not fdv_tx_filters(100_000, 50_000, 800_000, 5000, 2_000)
