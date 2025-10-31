#!/usr/bin/env python3
"""
Тестовый скрипт для диагностики работы CMC DEX API v4 с различными network_slug значениями.
Проверяет какие слоги работают и возвращают данные.
"""
import os
import sys
from dotenv import load_dotenv

# Add workspace to path
sys.path.insert(0, '/workspace')

from wakebot.config import Config
from wakebot.net_http import HttpClient


def test_all_networks():
    """Тестирование всех возможных сетевых слогов"""
    load_dotenv()
    cfg = Config.load()
    http = HttpClient(cfg)
    
    # Расширенный список для тестирования
    test_slugs = [
        # Основные сети
        "ethereum", "bsc", "base", "solana",
        # Альтернативные имена для BSC
        "bnb-chain", "bnb", "binance-smart-chain", "binance",
        # Другие популярные сети
        "polygon", "matic", "arbitrum", "optimism",
        "avalanche", "fantom", "cronos",
    ]
    
    working_slugs = {}
    failed_slugs = {}
    
    print("=" * 80)
    print("CMC DEX API v4 Network Slug Testing")
    print("=" * 80)
    print(f"API Base: {cfg.cmc_dex_base}")
    print(f"API Key: {'✓ Set' if cfg.cmc_api_key else '✗ Missing'}")
    print("=" * 80)
    
    for slug in test_slugs:
        print(f"\n🧪 Testing: {slug}")
        url = f"{cfg.cmc_dex_base}/spot-pairs/latest?network_slug={slug}&limit=2"
        
        try:
            doc = http.cmc_get_json(url, timeout=10.0) or {}
            
            # Проверка статуса API
            status = doc.get("status", {})
            error_code = status.get("error_code")
            
            if error_code and error_code != 0:
                error_msg = status.get("error_message", "Unknown error")
                print(f"❌ {slug}: {error_msg}")
                failed_slugs[slug] = error_msg
            else:
                # Проверка данных
                data = doc.get("data")
                if isinstance(data, list):
                    print(f"✅ {slug}: SUCCESS - {len(data)} items (data is list)")
                    if data:
                        first_item = data[0]
                        print(f"   First item type: {type(first_item)}")
                        if isinstance(first_item, dict):
                            print(f"   First item keys: {list(first_item.keys())[:10]}")
                            # Проверка наличия важных полей
                            has_id = "id" in first_item or "pool_id" in first_item
                            has_base = "base_address" in first_item or "base" in first_item
                            has_quote = "quote_address" in first_item or "quote" in first_item
                            print(f"   Has ID: {has_id}, Has Base: {has_base}, Has Quote: {has_quote}")
                    working_slugs[slug] = len(data)
                elif isinstance(data, dict):
                    print(f"⚠️  {slug}: Data is dict (unexpected), keys: {list(data.keys())}")
                    # Попробуем извлечь список из dict
                    items = data.get("items") or data.get("pairs") or data.get("list") or []
                    if items:
                        print(f"   Found {len(items)} items in nested structure")
                        working_slugs[slug] = len(items)
                    else:
                        failed_slugs[slug] = "Data is dict without items"
                else:
                    print(f"❌ {slug}: Data is {type(data)} (expected list)")
                    failed_slugs[slug] = f"Data type: {type(data)}"
                
        except Exception as e:
            print(f"❌ {slug}: EXCEPTION - {type(e).__name__}: {e}")
            failed_slugs[slug] = str(e)
    
    # Результаты
    print("\n" + "=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    
    if working_slugs:
        print(f"\n✅ Working slugs ({len(working_slugs)}):")
        for slug, count in sorted(working_slugs.items()):
            print(f"   • {slug:30s} → {count} items")
    else:
        print("\n❌ No working slugs found!")
    
    if failed_slugs:
        print(f"\n❌ Failed slugs ({len(failed_slugs)}):")
        for slug, reason in sorted(failed_slugs.items()):
            print(f"   • {slug:30s} → {reason}")
    
    print("\n" + "=" * 80)
    print("Recommended config.py chain_slugs mapping:")
    print("=" * 80)
    if working_slugs:
        print("\ncfg.chain_slugs = {")
        # Предложить маппинг для основных сетей
        for chain_name in ["ethereum", "bsc", "base", "solana", "polygon"]:
            # Найти работающий слог для этой сети
            candidates = [s for s in working_slugs.keys() if chain_name in s or s in chain_name]
            if candidates:
                print(f'    "{chain_name}": "{candidates[0]}",')
        print("}")
    
    return working_slugs, failed_slugs


def test_ohlcv_endpoint(network_slug: str, pair_address: str):
    """Тест OHLCV endpoint для конкретной пары"""
    load_dotenv()
    cfg = Config.load()
    http = HttpClient(cfg)
    
    print(f"\n🧪 Testing OHLCV for {network_slug}/{pair_address}")
    url = f"{cfg.cmc_dex_base}/pairs/ohlcv/latest?network_slug={network_slug}&contract_address={pair_address}&interval=1h&limit=25"
    print(f"URL: {url}")
    
    try:
        doc = http.cmc_get_json(url, timeout=10.0) or {}
        
        status = doc.get("status", {})
        error_code = status.get("error_code")
        
        if error_code and error_code != 0:
            error_msg = status.get("error_message", "Unknown error")
            print(f"❌ OHLCV Error: {error_msg}")
        else:
            print(f"✅ OHLCV Success")
            print(f"   Response keys: {list(doc.keys())}")
            data = doc.get("data", {})
            if isinstance(data, dict):
                attrs = data.get("attributes", {})
                candles = attrs.get("candles", [])
                print(f"   Candles count: {len(candles)}")
                if candles:
                    print(f"   First candle: {candles[0]}")
                    print(f"   Last candle: {candles[-1]}")
    except Exception as e:
        print(f"❌ OHLCV Exception: {type(e).__name__}: {e}")


if __name__ == "__main__":
    working, failed = test_all_networks()
    
    # Если есть работающие сети, протестируем OHLCV
    if "ethereum" in working:
        # Пример адреса пары на Ethereum (можно заменить на реальный)
        test_ohlcv_endpoint("ethereum", "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640")
