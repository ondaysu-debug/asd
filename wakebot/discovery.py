from __future__ import annotations

from typing import List, Dict, Tuple

from .config import Config
from .net_http import HttpClient
from .storage import Storage

# Import QuickNode collectors
from .quicknode.solana_collector import SolanaPoolCollector
from .quicknode.evm_collector import EVMPoolCollector
from .quicknode.pool_filter import QuickNodePoolFilter
from .quicknode.volume_monitor import QuickNodeVolumeMonitor


def unified_quicknode_discovery(
    cfg: Config,
    http: HttpClient, 
    storage: Storage,
    chain: str,
    cycle_idx: int
) -> Tuple[List[Dict], Dict[str, int]]:
    """
    Единый discovery через QuickNode API
    Заменяет ВСЕ существующие методы (GeckoTerminal, Raydium)
    """
    print(f"[discovery][{chain}] Starting QuickNode discovery...")
    
    # Выбираем соответствующий коллектор
    if chain == "solana":
        collector = SolanaPoolCollector(cfg, http)
        all_pools = collector.get_all_raydium_pools()
    else:
        collector = EVMPoolCollector(cfg, http)
        all_pools = collector.get_all_pools(chain)
    
    print(f"[discovery][{chain}] Collected {len(all_pools)} raw pools")
    
    # Применяем фильтры
    filter_engine = QuickNodePoolFilter(cfg, http)
    filtered_pools = filter_engine.apply_initial_filters(all_pools)
    
    print(f"[discovery][{chain}] After initial filtering: {len(filtered_pools)} pools")
    
    # Обогащаем метаданными (цена, ликвидность, FDV, возраст)
    # Это может быть медленно для большого количества пулов,
    # поэтому делаем это только для топ N пулов
    max_to_enrich = min(len(filtered_pools), cfg.max_monitored_pools)
    pools_to_enrich = filtered_pools[:max_to_enrich]
    
    print(f"[discovery][{chain}] Enriching {len(pools_to_enrich)} pools with metadata...")
    enriched_pools = filter_engine.enrich_pools_with_metadata(pools_to_enrich)
    
    # Применяем продвинутые фильтры (требуют метаданных)
    final_pools = filter_engine.apply_advanced_filters(enriched_pools)
    
    print(f"[discovery][{chain}] Final filtered pools: {len(final_pools)}")
    
    stats = {
        'pages_done': 1,
        'pages_planned': 1, 
        'scanned_pairs': len(all_pools),
        'filtered_pairs': len(final_pools),
        'sources_used': 1
    }
    
    return final_pools, stats


# LEGACY функция - сохраняем для обратной совместимости
def unified_gt_discovery(
    cfg: Config,
    http: HttpClient, 
    storage: Storage,
    chain: str,
    cycle_idx: int
) -> Tuple[List[Dict], Dict[str, int]]:
    """
    LEGACY: Старый метод через GeckoTerminal Megafilter
    Сохранен для обратной совместимости
    """
    from .gt_megafilter import GTMegafilterClient, MegafilterFilters
    
    # Создаем клиент megafilter
    megafilter_client = GTMegafilterClient(cfg, http)
    
    # Строим фильтры из конфигурации
    filters = MegafilterFilters(
        fdv_min=cfg.fdv_min,
        fdv_max=cfg.fdv_max,
        liquidity_min=cfg.liquidity_min, 
        liquidity_max=cfg.liquidity_max,
        volume_24h_min=cfg.min_prev24_usd,
        pool_age_min_hours=cfg.revival_min_age_days * 24,
        tx_count_max=cfg.tx24h_max
    )
    
    # Получаем пулы через megafilter
    pools = megafilter_client.discover_pools([chain], filters)
    
    # Статистика
    stats = {
        'pages_done': 1,
        'pages_planned': 1,
        'scanned_pairs': len(pools),
        'sources_used': 1
    }
    
    return pools, stats
