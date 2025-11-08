from __future__ import annotations

from typing import List, Dict, Set, Optional
from dataclasses import dataclass
import time

@dataclass
class FilterConfig:
    min_age_days: int = 7
    liquidity_min: float = 50000.0
    liquidity_max: float = 800000.0
    fdv_min: float = 50000.0  
    fdv_max: float = 800000.0
    tx_count_max: int = 2000

class QuickNodePoolFilter:
    """
    Фильтрация пулов по базовым критериям используя только QuickNode
    """
    
    def __init__(self, cfg, http):
        self.cfg = cfg
        self.http = http
        
        # Загружаем конфигурацию фильтров из cfg
        self.filter_config = FilterConfig(
            min_age_days=getattr(cfg, 'revival_min_age_days', 7),
            liquidity_min=getattr(cfg, 'liquidity_min', 50000.0),
            liquidity_max=getattr(cfg, 'liquidity_max', 800000.0),
            fdv_min=getattr(cfg, 'fdv_min', 50000.0),
            fdv_max=getattr(cfg, 'fdv_max', 800000.0),
            tx_count_max=getattr(cfg, 'tx24h_max', 2000),
        )
        
        self._log_fn = lambda msg: print(f"[pool_filter] {msg}")
        
        # NATIVE токены для каждой сети
        self.native_tokens = {
            "solana": {
                "So11111111111111111111111111111111111111112",  # SOL (wrapped)
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"   # USDT
            },
            "ethereum": {
                "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
                "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
                "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
            },
            "base": {
                "0x4200000000000000000000000000000000000006",  # WETH
                "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC
            },
            "bsc": {
                "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
                "0x55d398326f99059ff775485246999027b3197955",  # USDT
                "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
            }
        }
    
    def apply_initial_filters(self, pools: List[Dict]) -> List[Dict]:
        """
        Применяем базовые фильтры к тысячам пулов
        """
        self._log_fn(f"Applying filters to {len(pools)} pools...")
        
        filtered_pools = []
        stats = {
            'total_input': len(pools),
            'rejected_not_token_native': 0,
            'rejected_too_young': 0,
            'rejected_liquidity': 0,
            'rejected_fdv': 0,
            'rejected_tx_count': 0,
            'accepted': 0
        }
        
        for pool in pools:
            chain = pool.get('chain', '')
            
            # 1. Фильтр TOKEN/NATIVE пар
            if not self._is_token_native_pair(pool, chain):
                stats['rejected_not_token_native'] += 1
                continue
            
            # 2. Фильтр по возрасту (>7 дней) - пока пропускаем, будем получать позже
            # if not self._is_pool_old_enough(pool, chain):
            #     stats['rejected_too_young'] += 1
            #     continue
            
            # Добавляем пул для дальнейшей обработки
            # Остальные фильтры (ликвидность, FDV) требуют дополнительных данных
            filtered_pools.append(pool)
            stats['accepted'] += 1
        
        self._log_fn(f"Filter results: {stats['accepted']}/{stats['total_input']} pools passed initial filters")
        return filtered_pools
    
    def apply_advanced_filters(self, pools_with_metadata: List[Dict]) -> List[Dict]:
        """
        Применяем продвинутые фильтры после получения метаданных
        """
        self._log_fn(f"Applying advanced filters to {len(pools_with_metadata)} pools...")
        
        filtered_pools = []
        stats = {
            'total_input': len(pools_with_metadata),
            'rejected_too_young': 0,
            'rejected_liquidity': 0,
            'rejected_fdv': 0,
            'rejected_tx_count': 0,
            'accepted': 0
        }
        
        for pool in pools_with_metadata:
            chain = pool.get('chain', '')
            
            # 1. Фильтр по возрасту (>7 дней)
            if not self._is_pool_old_enough(pool, chain):
                stats['rejected_too_young'] += 1
                continue
            
            # 2. Фильтр по ликвидности
            liquidity = pool.get('liquidity_usd', 0.0)
            if not (self.filter_config.liquidity_min <= liquidity <= self.filter_config.liquidity_max):
                stats['rejected_liquidity'] += 1
                continue
            
            # 3. Фильтр по FDV
            fdv = pool.get('fdv_usd', 0.0)
            if fdv > 0 and not (self.filter_config.fdv_min <= fdv <= self.filter_config.fdv_max):
                stats['rejected_fdv'] += 1
                continue
            
            # 4. Фильтр по транзакциям (если есть данные)
            tx_count = pool.get('tx_count_24h', 0)
            if tx_count > 0 and tx_count > self.filter_config.tx_count_max:
                stats['rejected_tx_count'] += 1
                continue
            
            filtered_pools.append(pool)
            stats['accepted'] += 1
        
        self._log_fn(f"Advanced filter results: {stats['accepted']}/{stats['total_input']} pools passed all filters")
        return filtered_pools
    
    def _is_token_native_pair(self, pool: Dict, chain: str) -> bool:
        """
        Проверяем что это TOKEN/NATIVE пара (не NATIVE/NATIVE)
        """
        native_tokens = self.native_tokens.get(chain, set())
        
        # Нормализуем адреса к нижнему регистру
        native_tokens_lower = {token.lower() for token in native_tokens}
        
        base_mint = (pool.get('base_mint') or pool.get('token0', '')).lower()
        quote_mint = (pool.get('quote_mint') or pool.get('token1', '')).lower()
        
        # Quote должен быть NATIVE, base - не NATIVE
        is_quote_native = quote_mint in native_tokens_lower
        is_base_native = base_mint in native_tokens_lower
        
        # Хотим: quote = native, base = НЕ native
        # ИЛИ: base = native, quote = НЕ native (обратная пара)
        return (is_quote_native and not is_base_native) or (is_base_native and not is_quote_native)
    
    def _is_pool_old_enough(self, pool: Dict, chain: str) -> bool:
        """
        Проверяем возраст пула >7 дней
        """
        age_days = self._get_pool_age_days(pool, chain)
        return age_days >= self.filter_config.min_age_days
    
    def _get_pool_age_days(self, pool: Dict, chain: str) -> int:
        """
        Получаем возраст пула в днях
        """
        # Пробуем получить из уже существующих полей
        if 'pool_age_days' in pool:
            return int(pool['pool_age_days'])
        
        if 'creation_time' in pool:
            creation_time = pool['creation_time']
        elif 'createdAtTimestamp' in pool:
            creation_time = pool['createdAtTimestamp']
        elif 'blockTime' in pool:
            creation_time = pool['blockTime']
        else:
            # Нет информации о времени создания
            return 0
        
        if not creation_time:
            return 0
        
        try:
            age_seconds = time.time() - int(creation_time)
            return int(age_seconds / 86400)  # Конвертируем в дни
        except (ValueError, TypeError):
            return 0
    
    def _calculate_liquidity_usd(self, pool: Dict, chain: str) -> float:
        """
        Рассчитываем ликвидность в USD
        """
        # Если уже есть, используем
        if 'liquidity_usd' in pool:
            return float(pool['liquidity_usd'])
        
        if 'liquidity' in pool:
            return float(pool['liquidity'])
        
        # Иначе нужно рассчитать из reserves/amounts
        # Это требует знания цен токенов
        return 0.0
    
    def enrich_pools_with_metadata(self, pools: List[Dict]) -> List[Dict]:
        """
        Обогащаем пулы дополнительными метаданными
        """
        from .token_metadata import QuickNodeTokenMetadata
        from .price_calculator import QuickNodePriceCalculator
        
        metadata_fetcher = QuickNodeTokenMetadata(self.cfg, self.http)
        price_calc = QuickNodePriceCalculator(self.cfg, self.http)
        
        enriched_pools = []
        
        for pool in pools:
            chain = pool.get('chain', '')
            
            # Получаем creation time если нет
            if 'creation_time' not in pool and 'createdAtTimestamp' not in pool:
                pool = self._add_creation_time(pool, chain)
            
            # Рассчитываем ликвидность и FDV
            pool = price_calc.calculate_pool_metrics(pool, chain)
            
            enriched_pools.append(pool)
        
        return enriched_pools
    
    def _add_creation_time(self, pool: Dict, chain: str) -> Dict:
        """
        Добавляем время создания пула
        """
        if chain == "solana":
            from .solana_collector import SolanaPoolCollector
            collector = SolanaPoolCollector(self.cfg, self.http)
            creation_time = collector.get_pool_creation_time(pool['address'])
            if creation_time:
                pool['creation_time'] = creation_time
        else:
            # Для EVM можно получить через блок
            # Пока пропускаем для упрощения
            pass
        
        return pool
