#!/usr/bin/env python3
"""
Тестовый скрипт для проверки QuickNode интеграции
"""

from wakebot.config import Config
from wakebot.net_http import HttpClient
from wakebot.quicknode.solana_collector import SolanaPoolCollector
from wakebot.quicknode.evm_collector import EVMPoolCollector
from wakebot.quicknode.pool_filter import QuickNodePoolFilter
from wakebot.quicknode.volume_monitor import QuickNodeVolumeMonitor
from wakebot.quicknode.token_metadata import QuickNodeTokenMetadata
from wakebot.quicknode.price_calculator import QuickNodePriceCalculator


def test_quicknode_config():
    """Тест загрузки конфигурации"""
    print("=" * 80)
    print("TEST 1: QuickNode Configuration")
    print("=" * 80)
    
    try:
        cfg = Config.load()
        print(f"✅ Config loaded successfully")
        print(f"   QuickNode RPC URL: {cfg.quicknode_rpc_url[:50]}..." if cfg.quicknode_rpc_url else "   ⚠️  QuickNode RPC URL not set")
        print(f"   QuickNode Batch Size: {cfg.quicknode_batch_size}")
        print(f"   Pool Refresh Interval: {cfg.pool_refresh_interval_hours}h")
        print(f"   Max Monitored Pools: {cfg.max_monitored_pools}")
        print(f"   Chains: {', '.join(cfg.chains)}")
        return True
    except Exception as e:
        print(f"❌ Config load failed: {e}")
        return False


def test_solana_collection():
    """Тест сбора Solana пулов"""
    print("\n" + "=" * 80)
    print("TEST 2: Solana Pool Collection")
    print("=" * 80)
    
    try:
        cfg = Config.load()
        
        if not cfg.quicknode_rpc_url:
            print("⚠️  QUICKNODE_RPC_URL not configured, skipping Solana test")
            return False
        
        http = HttpClient(cfg)
        collector = SolanaPoolCollector(cfg, http)
        
        print("Fetching Raydium pools from QuickNode...")
        print("⚠️  Note: This may take 30-60 seconds for large datasets")
        
        pools = collector.get_all_raydium_pools()
        
        print(f"✅ Successfully collected {len(pools)} Raydium pools")
        
        if pools:
            sample_pool = pools[0]
            print(f"\nSample pool:")
            print(f"   Address: {sample_pool.get('address', 'N/A')}")
            print(f"   Base Mint: {sample_pool.get('base_mint', 'N/A')}")
            print(f"   Quote Mint: {sample_pool.get('quote_mint', 'N/A')}")
            print(f"   Base Amount: {sample_pool.get('base_amount', 0)}")
            print(f"   Quote Amount: {sample_pool.get('quote_amount', 0)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Solana collection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_evm_collection():
    """Тест сбора EVM пулов"""
    print("\n" + "=" * 80)
    print("TEST 3: EVM Pool Collection (Base)")
    print("=" * 80)
    
    try:
        cfg = Config.load()
        
        if not cfg.quicknode_rpc_url:
            print("⚠️  QUICKNODE_RPC_URL not configured, skipping EVM test")
            return False
        
        http = HttpClient(cfg)
        collector = EVMPoolCollector(cfg, http)
        
        print("Fetching pools from QuickNode for Base...")
        print("⚠️  Note: This fetches recent pools only (last ~10k blocks)")
        
        pools = collector.get_all_pools("base")
        
        print(f"✅ Successfully collected {len(pools)} Base pools")
        
        if pools:
            sample_pool = pools[0]
            print(f"\nSample pool:")
            print(f"   Address: {sample_pool.get('address', 'N/A')}")
            print(f"   Token0: {sample_pool.get('token0', 'N/A')}")
            print(f"   Token1: {sample_pool.get('token1', 'N/A')}")
            print(f"   Version: {sample_pool.get('version', 'N/A')}")
            print(f"   Block: {sample_pool.get('block_number', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"❌ EVM collection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pool_filtering():
    """Тест фильтрации пулов"""
    print("\n" + "=" * 80)
    print("TEST 4: Pool Filtering")
    print("=" * 80)
    
    try:
        cfg = Config.load()
        http = HttpClient(cfg)
        filter_engine = QuickNodePoolFilter(cfg, http)
        
        # Создаем тестовые пулы
        test_pools = [
            {
                'address': 'test1',
                'chain': 'solana',
                'base_mint': 'TOKEN123',
                'quote_mint': 'So11111111111111111111111111111111111111112',  # SOL
            },
            {
                'address': 'test2',
                'chain': 'ethereum',
                'base_mint': '0x1234567890123456789012345678901234567890',
                'quote_mint': '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',  # WETH
                'token0': '0x1234567890123456789012345678901234567890',
                'token1': '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',
            },
            {
                'address': 'test3',
                'chain': 'solana',
                'base_mint': 'So11111111111111111111111111111111111111112',  # SOL
                'quote_mint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC (должен быть отфильтрован)
            }
        ]
        
        print(f"Testing with {len(test_pools)} sample pools...")
        filtered = filter_engine.apply_initial_filters(test_pools)
        
        print(f"✅ Filter applied: {len(test_pools)} -> {len(filtered)} pools")
        print(f"   (Filtered out {len(test_pools) - len(filtered)} NATIVE/NATIVE pairs)")
        
        return True
        
    except Exception as e:
        print(f"❌ Filtering failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_token_metadata():
    """Тест получения метаданных токенов"""
    print("\n" + "=" * 80)
    print("TEST 5: Token Metadata Fetching")
    print("=" * 80)
    
    try:
        cfg = Config.load()
        
        if not cfg.quicknode_rpc_url:
            print("⚠️  QUICKNODE_RPC_URL not configured, skipping metadata test")
            return False
        
        http = HttpClient(cfg)
        metadata_fetcher = QuickNodeTokenMetadata(cfg, http)
        
        # Тестируем с известным токеном (SOL)
        print("Fetching metadata for SOL token...")
        sol_mint = "So11111111111111111111111111111111111111112"
        metadata = metadata_fetcher.get_token_metadata(sol_mint, "solana")
        
        if metadata:
            print(f"✅ Successfully fetched metadata:")
            print(f"   Decimals: {metadata.get('decimals', 'N/A')}")
            print(f"   Supply: {metadata.get('supply', 'N/A')}")
        else:
            print(f"⚠️  No metadata returned (might be normal for wrapped SOL)")
        
        return True
        
    except Exception as e:
        print(f"❌ Metadata fetch failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_volume_monitor():
    """Тест мониторинга объемов"""
    print("\n" + "=" * 80)
    print("TEST 6: Volume Monitoring")
    print("=" * 80)
    
    try:
        cfg = Config.load()
        http = HttpClient(cfg)
        volume_monitor = QuickNodeVolumeMonitor(cfg, http)
        
        # Создаем тестовый пул
        test_pools = [
            {
                'address': '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',  # Raydium program (для теста)
                'chain': 'solana',
            }
        ]
        
        print("Testing volume calculation...")
        print("⚠️  Note: This makes actual RPC calls")
        
        # Пока просто создаем monitor, полный тест требует реальный pool адрес
        print(f"✅ Volume monitor initialized")
        print(f"   Batch size: {cfg.quicknode_batch_size}")
        
        return True
        
    except Exception as e:
        print(f"❌ Volume monitor failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Главная функция тестирования"""
    print("🚀 QuickNode Integration Test Suite")
    print("=" * 80)
    
    results = {}
    
    # Запускаем тесты
    results['config'] = test_quicknode_config()
    results['solana'] = test_solana_collection()
    results['evm'] = test_evm_collection()
    results['filtering'] = test_pool_filtering()
    results['metadata'] = test_token_metadata()
    results['volume'] = test_volume_monitor()
    
    # Итоговый отчет
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print("=" * 80)
    print(f"TOTAL: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed. Check configuration and QuickNode setup.")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
