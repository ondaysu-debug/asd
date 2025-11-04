from __future__ import annotations
from typing import List, Dict, Optional
from dataclasses import dataclass
import time
from datetime import datetime, timezone

from .config import Config
from .net_http import HttpClient
from .filters import is_base_token_acceptable, is_token_native_pair, pool_data_filters


@dataclass
class MegafilterFilters:
    """Параметры фильтрации для megafilter"""
    fdv_min: float
    fdv_max: float
    liquidity_min: float
    liquidity_max: float
    volume_24h_min: float
    pool_age_min_hours: int  # 7 дней = 168 часов
    tx_count_max: int


class GTMegafilterClient:
    """
    Специализированный клиент для эндпоинта /pools/megafilter
    Заменяет ВСЕ существующие методы discovery
    """
    
    def __init__(self, cfg: Config, http: HttpClient):
        self.cfg = cfg
        self.http = http
        
    def discover_pools(self, networks: List[str], filters: MegafilterFilters) -> List[Dict]:
        """
        Основной метод discovery через megafilter
        """
        all_pools = []
        
        for network in networks:
            print(f"[discover][{network}] Starting megafilter discovery...")
            pools = self._discover_network_pools(network, filters)
            all_pools.extend(pools)
            time.sleep(0.5)  # Rate limiting между сетями
            
        print(f"[discover] Total pools found: {len(all_pools)}")
        return all_pools
    
    def _discover_network_pools(self, network: str, filters: MegafilterFilters) -> List[Dict]:
        """
        Discovery пулов для конкретной сети через megafilter
        """
        url = f"{self.cfg.gt_megafilter_base}/pools/megafilter"
        params = self._build_megafilter_params(network, filters)
        
        print(f"[discover][{network}] Megafilter URL: {url}")
        print(f"[discover][{network}] Megafilter params: {params}")
        
        try:
            response = self.http.megafilter_get_json(url, params=params, timeout=20.0)
            return self._parse_megafilter_response(response, network)
        except Exception as e:
            print(f"[discover][{network}] Megafilter discovery error: {e}")
            return []
    
    def _build_megafilter_params(self, network: str, filters: MegafilterFilters) -> Dict:
        """
        Построение параметров для megafilter запроса
        БЕЗ honeypot checks
        """
        return {
            "networks": network,
            "include": "base_token,quote_token,dex,network",
            "page": 1,
            "page_size": self.cfg.gt_megafilter_page_size,
            "sort": self.cfg.gt_megafilter_sort,
            "fdv_usd_min": filters.fdv_min,
            "fdv_usd_max": filters.fdv_max,
            "reserve_in_usd_min": filters.liquidity_min,
            "reserve_in_usd_max": filters.liquidity_max,
            "h24_volume_usd_min": filters.volume_24h_min,
            "pool_created_hour_min": filters.pool_age_min_hours,  # 👈 7 ДНЕЙ
            "tx_count_max": filters.tx_count_max,
            # НЕТ "checks": "no_honeypot"!
        }
    
    def _parse_megafilter_response(self, response: Dict, network: str) -> List[Dict]:
        """
        Парсинг ответа megafilter с ПОЛНЫМИ данными для немедленных алертов
        """
        pools = []
        
        data = response.get('data', [])
        included = response.get('included', [])
        
        # Создаем мапу токенов и dex'ов из included
        token_map = {}
        dex_map = {}
        
        for item in included:
            item_type = item.get('type')
            item_id = item.get('id')
            if item_type == 'token':
                token_map[item_id] = item.get('attributes', {})
            elif item_type == 'dex':
                dex_map[item_id] = item.get('attributes', {})
        
        for item in data:
            if item.get('type') != 'pool':
                continue
                
            attributes = item.get('attributes', {})
            relationships = item.get('relationships', {})
            
            # Извлекаем base_token и quote_token
            base_token_data = relationships.get('base_token', {}).get('data', {})
            quote_token_data = relationships.get('quote_token', {}).get('data', {})
            dex_data = relationships.get('dex', {}).get('data', {})
            
            base_token = token_map.get(base_token_data.get('id'), {})
            quote_token = token_map.get(quote_token_data.get('id'), {})
            dex_info = dex_map.get(dex_data.get('id'), {})
            
            # Применяем native pair фильтр
            ok, token_side, native_side = is_token_native_pair(network, base_token, quote_token)
            if not ok:
                continue
                
            # Применяем base token фильтр
            if not is_base_token_acceptable(network, token_side):
                continue
            
            # Извлекаем volume данные
            volume_usd = attributes.get('volume_usd', {})
            transactions = attributes.get('transactions', {})
            
            pool_data = {
                'chain': network,
                'pool': attributes.get('address', ''),
                'url': f"https://www.geckoterminal.com/{network}/pools/{attributes.get('address', '')}",
                'baseSymbol': token_side.get('symbol', ''),
                'baseAddr': token_side.get('address', ''),
                'quoteSymbol': native_side.get('symbol', ''),
                'quoteAddr': native_side.get('address', ''),
                'liquidity': float(attributes.get('reserve_in_usd', 0)),
                'fdv': float(attributes.get('fdv_usd', 0)),
                'tx24h': transactions.get('h24', {}).get('total', 0),
                
                # КРИТИЧЕСКИЕ ДАННЫЕ ДЛЯ НЕМЕДЛЕННЫХ АЛЕРТОВ:
                'volume_1h': float(volume_usd.get('h1', 0)),
                'volume_24h': float(volume_usd.get('h24', 0)),
                'pool_created_at': attributes.get('pool_created_at', ''),
                'pool_age_days': self._calculate_pool_age_days(attributes.get('pool_created_at', '')),
            }
            
            pools.append(pool_data)
            
        print(f"[discover][{network}] Parsed {len(pools)} pools with full metrics")
        return pools
    
    def _calculate_pool_age_days(self, pool_created_at: str) -> int:
        """Расчет возраста пула в днях"""
        if not pool_created_at:
            return 0
            
        try:
            created_dt = datetime.fromisoformat(pool_created_at.replace('Z', '+00:00'))
            now_dt = datetime.now(timezone.utc)
            age_days = (now_dt - created_dt).days
            return max(0, age_days)
        except Exception:
            return 0
