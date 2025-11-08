from __future__ import annotations

from typing import Dict, Optional
import time

class QuickNodePriceCalculator:
    """
    Расчет цен, ликвидности и FDV используя QuickNode данные
    """
    
    def __init__(self, cfg, http):
        self.cfg = cfg
        self.http = http
        self._log_fn = lambda msg: print(f"[price_calculator] {msg}")
        
        # Известные цены для stablecoins и wrapped нативных токенов
        self.known_prices = {
            # Solana
            "So11111111111111111111111111111111111111112": 150.0,  # SOL (примерная цена)
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 1.0,  # USDC
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 1.0,  # USDT
            
            # Ethereum
            "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": 3000.0,  # WETH
            "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": 1.0,  # USDC
            "0xdac17f958d2ee523a2206206994597c13d831ec7": 1.0,  # USDT
            
            # Base
            "0x4200000000000000000000000000000000000006": 3000.0,  # WETH
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 1.0,  # USDC
            
            # BSC
            "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": 600.0,  # WBNB
            "0x55d398326f99059ff775485246999027b3197955": 1.0,  # USDT
            "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": 1.0,  # USDC
        }
    
    def calculate_pool_metrics(self, pool: Dict, chain: str) -> Dict:
        """
        Рассчитываем метрики пула: цену токена, ликвидность USD, FDV
        """
        if chain == "solana":
            return self._calculate_solana_metrics(pool)
        else:
            return self._calculate_evm_metrics(pool, chain)
    
    def _calculate_solana_metrics(self, pool: Dict) -> Dict:
        """
        Рассчитываем метрики для Solana пула
        """
        base_mint = pool.get('base_mint', '')
        quote_mint = pool.get('quote_mint', '')
        base_amount = pool.get('base_amount', 0)
        quote_amount = pool.get('quote_amount', 0)
        
        if base_amount <= 0 or quote_amount <= 0:
            return pool
        
        # Получаем цену quote токена (обычно SOL, USDC, USDT)
        quote_price = self.known_prices.get(quote_mint, 0.0)
        
        if quote_price <= 0:
            return pool
        
        # Получаем метаданные токенов для decimals
        from .token_metadata import QuickNodeTokenMetadata
        metadata_fetcher = QuickNodeTokenMetadata(self.cfg, self.http)
        
        base_metadata = metadata_fetcher.get_token_metadata(base_mint, 'solana')
        quote_metadata = metadata_fetcher.get_token_metadata(quote_mint, 'solana')
        
        base_decimals = base_metadata.get('decimals', 9) if base_metadata else 9
        quote_decimals = quote_metadata.get('decimals', 9) if quote_metadata else 9
        
        # Нормализуем amounts с учетом decimals
        base_amount_normalized = base_amount / (10 ** base_decimals)
        quote_amount_normalized = quote_amount / (10 ** quote_decimals)
        
        # Цена base токена в quote токенах
        token_price_in_quote = quote_amount_normalized / base_amount_normalized if base_amount_normalized > 0 else 0
        
        # Цена base токена в USD
        token_price_usd = token_price_in_quote * quote_price
        
        # Ликвидность = quote_amount * 2 (т.к. пул 50/50)
        liquidity_usd = quote_amount_normalized * quote_price * 2
        
        # FDV = token_price_usd * total_supply
        fdv_usd = 0.0
        if base_metadata and 'supply' in base_metadata:
            try:
                total_supply = int(base_metadata['supply'])
                total_supply_normalized = total_supply / (10 ** base_decimals)
                fdv_usd = token_price_usd * total_supply_normalized
            except (ValueError, TypeError):
                pass
        
        # Обновляем пул
        pool['token_price_usd'] = token_price_usd
        pool['liquidity_usd'] = liquidity_usd
        pool['fdv_usd'] = fdv_usd
        pool['base_decimals'] = base_decimals
        pool['quote_decimals'] = quote_decimals
        
        return pool
    
    def _calculate_evm_metrics(self, pool: Dict, chain: str) -> Dict:
        """
        Рассчитываем метрики для EVM пула
        """
        token0 = pool.get('token0', '') or pool.get('base_mint', '')
        token1 = pool.get('token1', '') or pool.get('quote_mint', '')
        
        # Получаем резервы если их нет
        if 'reserve0' not in pool or 'reserve1' not in pool:
            from .evm_collector import EVMPoolCollector
            collector = EVMPoolCollector(self.cfg, self.http)
            reserves = collector.get_pool_reserves(chain, pool['address'])
            
            if reserves:
                pool['reserve0'] = reserves['reserve0']
                pool['reserve1'] = reserves['reserve1']
            else:
                return pool
        
        reserve0 = pool.get('reserve0', 0)
        reserve1 = pool.get('reserve1', 0)
        
        if reserve0 <= 0 or reserve1 <= 0:
            return pool
        
        # Нормализуем адреса
        token0_lower = token0.lower()
        token1_lower = token1.lower()
        
        # Определяем какой токен - quote (native)
        quote_token = None
        quote_reserve = 0
        base_token = None
        base_reserve = 0
        
        if token0_lower in self.known_prices:
            quote_token = token0_lower
            quote_reserve = reserve0
            base_token = token1_lower
            base_reserve = reserve1
        elif token1_lower in self.known_prices:
            quote_token = token1_lower
            quote_reserve = reserve1
            base_token = token0_lower
            base_reserve = reserve0
        else:
            return pool
        
        quote_price = self.known_prices.get(quote_token, 0.0)
        
        if quote_price <= 0:
            return pool
        
        # Получаем метаданные для decimals
        from .token_metadata import QuickNodeTokenMetadata
        metadata_fetcher = QuickNodeTokenMetadata(self.cfg, self.http)
        
        base_metadata = metadata_fetcher.get_token_metadata(base_token, chain)
        quote_metadata = metadata_fetcher.get_token_metadata(quote_token, chain)
        
        base_decimals = base_metadata.get('decimals', 18) if base_metadata else 18
        quote_decimals = quote_metadata.get('decimals', 18) if quote_metadata else 18
        
        # Нормализуем резервы
        base_reserve_normalized = base_reserve / (10 ** base_decimals)
        quote_reserve_normalized = quote_reserve / (10 ** quote_decimals)
        
        # Цена base токена
        token_price_in_quote = quote_reserve_normalized / base_reserve_normalized if base_reserve_normalized > 0 else 0
        token_price_usd = token_price_in_quote * quote_price
        
        # Ликвидность
        liquidity_usd = quote_reserve_normalized * quote_price * 2
        
        # FDV
        fdv_usd = 0.0
        if base_metadata and 'total_supply' in base_metadata:
            try:
                total_supply = base_metadata['total_supply']
                total_supply_normalized = total_supply / (10 ** base_decimals)
                fdv_usd = token_price_usd * total_supply_normalized
            except (ValueError, TypeError):
                pass
        
        # Обновляем пул
        pool['token_price_usd'] = token_price_usd
        pool['liquidity_usd'] = liquidity_usd
        pool['fdv_usd'] = fdv_usd
        pool['base_token'] = base_token
        pool['quote_token'] = quote_token
        pool['base_decimals'] = base_decimals
        pool['quote_decimals'] = quote_decimals
        
        return pool
    
    def get_token_price_usd(self, token_address: str, chain: str) -> Optional[float]:
        """
        Получаем цену токена в USD
        """
        # Проверяем известные цены
        token_lower = token_address.lower()
        if token_lower in self.known_prices:
            return self.known_prices[token_lower]
        
        # Для неизвестных токенов нужно искать пул с известным токеном
        # Это сложнее и требует дополнительной логики
        # Пока возвращаем None
        return None
