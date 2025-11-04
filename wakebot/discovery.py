from __future__ import annotations

from typing import List, Dict, Tuple

from .config import Config
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
    Упрощенный discovery через GT Megafilter для 1-минутных циклов.
    Возвращает данные готовые для немедленных алертов.
    """
    # Создаем клиент megafilter
    megafilter_client = GTMegafilterClient(cfg, http)
    
    # Строим фильтры из конфигурации
    filters = MegafilterFilters(
        fdv_min=cfg.fdv_min,
        fdv_max=cfg.fdv_max,
        liquidity_min=cfg.liquidity_min, 
        liquidity_max=cfg.liquidity_max,
        volume_24h_min=cfg.min_prev24_usd,
        pool_age_min_hours=cfg.revival_min_age_days * 24,  # 7 дней = 168 часов
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
