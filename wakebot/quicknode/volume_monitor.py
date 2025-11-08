from __future__ import annotations

from typing import List, Dict, Optional
import time
from collections import defaultdict

class QuickNodeVolumeMonitor:
    """
    Мониторинг объемов пулов через QuickNode
    """
    
    def __init__(self, cfg, http):
        self.cfg = cfg
        self.http = http
        self.volume_history = defaultdict(list)
        self.last_update_time = {}
        self._log_fn = lambda msg: print(f"[volume_monitor] {msg}")
    
    def update_volumes_batch(self, pools: List[Dict]) -> List[Dict]:
        """
        Массовое обновление объемов для списка пулов
        """
        self._log_fn(f"Updating volumes for {len(pools)} pools...")
        
        updated_pools = []
        
        # Делим на батчи для эффективности
        batch_size = getattr(self.cfg, 'quicknode_batch_size', 100)
        
        for i in range(0, len(pools), batch_size):
            batch = pools[i:i + batch_size]
            batch_volumes = self._process_volume_batch(batch)
            updated_pools.extend(batch_volumes)
        
        self._log_fn(f"Volumes updated for {len(updated_pools)} pools")
        return updated_pools
    
    def _process_volume_batch(self, pools: List[Dict]) -> List[Dict]:
        """
        Обрабатываем батч пулов для обновления объемов
        """
        updated_pools = []
        
        # Группируем по chain для оптимизации
        pools_by_chain = defaultdict(list)
        for pool in pools:
            chain = pool.get('chain', '')
            pools_by_chain[chain].append(pool)
        
        # Обрабатываем каждую chain отдельно
        for chain, chain_pools in pools_by_chain.items():
            if chain == "solana":
                updated = self._process_solana_volumes(chain_pools)
            else:
                updated = self._process_evm_volumes(chain_pools, chain)
            
            updated_pools.extend(updated)
        
        return updated_pools
    
    def _process_solana_volumes(self, pools: List[Dict]) -> List[Dict]:
        """
        Обрабатываем объемы для Solana пулов
        """
        updated_pools = []
        
        for pool in pools:
            pool_address = pool['address']
            
            # Получаем транзакции пула за последние 24 часа
            transactions = self._get_solana_pool_transactions(pool_address)
            
            # Рассчитываем объемы
            volume_metrics = self._calculate_volume_from_transactions(pool, transactions)
            
            # Обновляем пул
            pool.update(volume_metrics)
            updated_pools.append(pool)
        
        return updated_pools
    
    def _process_evm_volumes(self, pools: List[Dict], chain: str) -> List[Dict]:
        """
        Обрабатываем объемы для EVM пулов
        """
        updated_pools = []
        
        for pool in pools:
            pool_address = pool['address']
            
            # Для EVM используем события Swap
            swaps = self._get_evm_pool_swaps(pool_address, chain)
            
            # Рассчитываем объемы
            volume_metrics = self._calculate_evm_volume_from_swaps(pool, swaps, chain)
            
            # Обновляем пул
            pool.update(volume_metrics)
            updated_pools.append(pool)
        
        return updated_pools
    
    def _get_solana_pool_transactions(self, pool_address: str, limit: int = 1000) -> List[Dict]:
        """
        Получаем транзакции Solana пула
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                pool_address,
                {
                    "limit": limit,
                    "commitment": "finalized"
                }
            ]
        }
        
        try:
            response = self.http.quicknode_solana_rpc(payload)
            return response.get('result', [])
        except Exception as e:
            self._log_fn(f"Error getting Solana transactions for {pool_address}: {e}")
            return []
    
    def _calculate_volume_from_transactions(self, pool: Dict, transactions: List[Dict]) -> Dict:
        """
        Расчет объемов из транзакций Solana
        """
        current_time = time.time()
        volume_24h = 0.0
        volume_1h = 0.0
        tx_count_24h = 0
        tx_count_1h = 0
        
        for tx in transactions:
            tx_time = tx.get('blockTime', 0)
            if not tx_time:
                continue
            
            tx_age_hours = (current_time - tx_time) / 3600
            
            if tx_age_hours <= 24:
                tx_count_24h += 1
                # Упрощенная метрика: каждая транзакция = 1 единица объема
                # В реальности нужно парсить transaction data для получения точного объема
                volume_24h += 1
            
            if tx_age_hours <= 1:
                tx_count_1h += 1
                volume_1h += 1
        
        return {
            'volume_24h': volume_24h,
            'volume_1h': volume_1h,
            'tx_count_24h': tx_count_24h,
            'tx_count_1h': tx_count_1h
        }
    
    def _get_evm_pool_swaps(self, pool_address: str, chain: str, blocks_back: int = 7200) -> List[Dict]:
        """
        Получаем Swap события для EVM пула
        (~7200 блоков = ~24 часа для большинства EVM сетей)
        """
        # Swap event signature (Uniswap V2)
        swap_topic = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
        
        try:
            # Получаем текущий блок
            latest_block_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_blockNumber",
                "params": []
            }
            
            latest_response = self.http.quicknode_evm_rpc(chain, latest_block_payload)
            latest_block = int(latest_response.get('result', '0x0'), 16)
            from_block = max(0, latest_block - blocks_back)
            
            # Получаем события Swap
            logs_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getLogs",
                "params": [{
                    "fromBlock": hex(from_block),
                    "toBlock": "latest",
                    "address": pool_address,
                    "topics": [swap_topic]
                }]
            }
            
            response = self.http.quicknode_evm_rpc(chain, logs_payload)
            return response.get('result', [])
            
        except Exception as e:
            self._log_fn(f"Error getting EVM swaps for {pool_address} on {chain}: {e}")
            return []
    
    def _calculate_evm_volume_from_swaps(self, pool: Dict, swaps: List[Dict], chain: str) -> Dict:
        """
        Расчет объемов из Swap событий EVM
        """
        # Получаем временные метки блоков для фильтрации по времени
        current_time = time.time()
        
        volume_24h = 0.0
        volume_1h = 0.0
        tx_count_24h = len(swaps)  # Упрощение
        tx_count_1h = 0
        
        # Для точного расчета нужно получить timestamps блоков
        # Пока используем упрощенную метрику на основе количества свапов
        
        # Предполагаем что последние 300 блоков = ~1 час (для большинства сетей)
        # Это грубое приближение, в production нужно использовать реальные timestamps
        
        if tx_count_24h > 0:
            # Примерная оценка: последние 1/24 свапов = за последний час
            tx_count_1h = max(1, tx_count_24h // 24)
            volume_24h = float(tx_count_24h)
            volume_1h = float(tx_count_1h)
        
        return {
            'volume_24h': volume_24h,
            'volume_1h': volume_1h,
            'tx_count_24h': tx_count_24h,
            'tx_count_1h': tx_count_1h
        }
    
    def calculate_volume_spike(self, pool: Dict) -> Optional[float]:
        """
        Рассчитываем коэффициент всплеска объема (vol1h / avg_vol_per_hour_24h)
        """
        vol1h = pool.get('volume_1h', 0.0)
        vol24h = pool.get('volume_24h', 0.0)
        
        if vol24h <= 0:
            return None
        
        # Средний объем за час = vol24h / 24
        avg_vol_per_hour = vol24h / 24.0
        
        if avg_vol_per_hour <= 0:
            return None
        
        # Коэффициент всплеска
        spike_ratio = vol1h / avg_vol_per_hour
        
        return spike_ratio
