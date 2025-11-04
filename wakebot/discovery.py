from __future__ import annotations

from typing import List, Dict, Tuple

from .config import Config
from .filters import pool_data_filters
from .gt_megafilter import GTMegafilterClient, MegafilterFilters
from .net_http import HttpClient
from .storage import Storage


def unified_gt_discovery(
    cfg: Config,
    http: HttpClient, 
    storage: Storage,
    chain: str,
    cycle_idx: int
) -> Tuple[List[Dict], Dict[str, int]]:
    """
    Унифицированный discovery через GT Megafilter
    Полностью заменяет cmc_discover_candidates и gt_discover_candidates
    """
    print(f"[discover][{chain}] Starting unified GT discovery with megafilter...")
    
    # Создаем клиент megafilter
    megafilter_client = GTMegafilterClient(cfg, http)
    
    # Строим фильтры из конфигурации
    filters = MegafilterFilters(
        fdv_min=cfg.fdv_min,
        fdv_max=cfg.fdv_max,
        liquidity_min=cfg.liquidity_min, 
        liquidity_max=cfg.liquidity_max,
        volume_24h_min=cfg.min_prev24_usd,
        pool_age_min_hours=cfg.revival_min_age_days * 24,  # 👈 7 ДНЕЙ = 168 часов
        tx_count_max=cfg.tx24h_max
    )
    
    # Получаем пулы через megafilter
    pools = megafilter_client.discover_pools([chain], filters)
    
    # Применяем дополнительные фильтры
    filtered_pools = []
    for pool in pools:
        # Проверка через pool_data_filters (сохраняем 7 дней)
        if not pool_data_filters(
            fdv=pool['fdv'],
            fdv_min=cfg.fdv_min,
            fdv_max=cfg.fdv_max,
            tx24h=pool['tx24h'],
            tx24h_max=cfg.tx24h_max,
            pool_age_days=pool['pool_age_days'],
            min_age_days=cfg.revival_min_age_days  # 👈 7 ДНЕЙ
        ):
            continue
            
        filtered_pools.append(pool)
    
    stats = {
        'pages_done': 1,  # megafilter использует пагинацию внутри
        'pages_planned': 1,
        'scanned_pairs': len(pools),
        'sources_used': 1
    }
    
    print(f"[discover][{chain}] Discovery complete: {len(filtered_pools)} candidates after filters")
    return filtered_pools, stats
