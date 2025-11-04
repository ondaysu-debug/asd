from __future__ import annotations
from typing import Tuple, Optional, Dict

from .config import Config
from .net_http import HttpClient
from .gecko import GeckoCache, fetch_gt_ohlcv_25h_with_age


class GTDataService:
    """
    Unified data service combining megafilter discovery + OHLCV monitoring
    """
    
    def __init__(self, cfg: Config, http: HttpClient, cache: GeckoCache):
        self.cfg = cfg
        self.http = http
        self.cache = cache
        
    def fetch_volume_metrics(self, chain: str, pool_address: str, pool_created_at: str = None) -> Tuple[float, float, bool, str]:
        """
        Получение volume метрик через GT OHLCV эндпоинты
        Возвращает: (vol1h, vol24h, ok_age, source)
        """
        try:
            vol1h, vol24h, ok_age = fetch_gt_ohlcv_25h_with_age(
                self.cfg, self.http, chain, pool_address, self.cache, pool_created_at
            )
            
            return vol1h, vol24h, ok_age, "GeckoTerminal OHLCV"
        except Exception as e:
            print(f"[{chain}] GT volume metrics error for {pool_address}: {e}")
            return 0.0, 0.0, False, "GeckoTerminal OHLCV"
    
    def get_pool_details(self, chain: str, pool_address: str) -> Optional[Dict]:
        """
        Получение детальной информации о пуле
        """
        from .gecko import _normalize_gt_chain
        
        gt_chain = _normalize_gt_chain(chain)
        url = f"{self.cfg.gecko_base}/networks/{gt_chain}/pools/{pool_address}"
        
        try:
            response = self.http.gt_get_json(url, timeout=15.0)
            data = response.get('data', {})
            attributes = data.get('attributes', {})
            
            return {
                'liquidity': float(attributes.get('reserve_in_usd', 0)),
                'volume_24h': float(attributes.get('volume_usd', {}).get('h24', 0)),
                'fdv': float(attributes.get('fdv_usd', 0)),
                'transactions_24h': attributes.get('transactions', {}).get('h24', {}),
                'pool_created_at': attributes.get('pool_created_at', ''),
            }
        except Exception as e:
            print(f"[{chain}] GT pool details error for {pool_address}: {e}")
            return None
