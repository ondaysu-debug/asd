from __future__ import annotations

import base64
import base58
from typing import List, Dict, Optional
from dataclasses import dataclass
import time

@dataclass
class RaydiumPoolData:
    address: str
    base_mint: str
    quote_mint: str
    lp_mint: str
    base_amount: int
    quote_amount: int
    status: int
    version: int

class SolanaPoolCollector:
    """
    Массовый сбор пулов Raydium через QuickNode RPC
    """
    
    RAYDIUM_AMM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
    RAYDIUM_V4_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
    
    def __init__(self, cfg, http):
        self.cfg = cfg
        self.http = http
        self._log_fn = lambda msg: print(f"[solana_collector] {msg}")
    
    def get_all_raydium_pools(self) -> List[Dict]:
        """
        Получаем ВСЕ пулы Raydium через getProgramAccounts
        Returns: List[Dict] с полями: address, base_mint, quote_mint, lp_mint, etc.
        """
        self._log_fn("Fetching all Raydium pools via QuickNode...")
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getProgramAccounts",
            "params": [
                self.RAYDIUM_AMM_PROGRAM,
                {
                    "filters": [{"dataSize": 752}],  # Raydium AMM V4 pool size
                    "encoding": "base64",
                    "withContext": True
                }
            ]
        }
        
        try:
            response = self.http.quicknode_solana_rpc(payload)
            pools = self._decode_pool_accounts(response)
            self._log_fn(f"Successfully decoded {len(pools)} Raydium pools")
            return pools
        except Exception as e:
            self._log_fn(f"Error fetching Raydium pools: {e}")
            return []
    
    def _decode_pool_accounts(self, response: Dict) -> List[Dict]:
        """
        Декодируем бинарную структуру Raydium AMM пулов
        Структура данных (бинарный формат):
        - offset 0: version (u8)
        - offset 1: status (u8)
        - offset 8: base_mint (32 bytes)
        - offset 40: quote_mint (32 bytes)
        - offset 72: lp_mint (32 bytes) 
        - offset 376: base_amount (u64)
        - offset 384: quote_amount (u64)
        """
        pools = []
        
        result = response.get('result', {})
        accounts = result.get('value', []) if isinstance(result, dict) else []
        
        for account in accounts:
            try:
                pool_data = self._parse_single_pool(account)
                if pool_data:
                    pools.append(pool_data)
            except Exception as e:
                # Тихо пропускаем невалидные пулы
                continue
                
        return pools
    
    def _parse_single_pool(self, account: Dict) -> Optional[Dict]:
        """Парсим один Raydium пул из бинарных данных"""
        pubkey = account.get('pubkey', '')
        account_data = account.get('account', {})
        data_info = account_data.get('data', [])
        
        if not data_info or len(data_info) < 1:
            return None
            
        data_b64 = data_info[0]
        
        try:
            decoded_data = base64.b64decode(data_b64)
            
            # Минимальная длина для валидного пула
            if len(decoded_data) < 392:
                return None
            
            # Парсим бинарную структуру
            version = decoded_data[0]
            status = decoded_data[1]
            
            # Пропускаем неактивные пулы
            if status == 0:
                return None
            
            base_mint = base58.b58encode(decoded_data[8:40]).decode()
            quote_mint = base58.b58encode(decoded_data[40:72]).decode()
            lp_mint = base58.b58encode(decoded_data[72:104]).decode()
            
            # Парсим amounts (little-endian u64)
            base_amount = int.from_bytes(decoded_data[376:384], 'little')
            quote_amount = int.from_bytes(decoded_data[384:392], 'little')
            
            # Пропускаем пулы с нулевой ликвидностью
            if base_amount == 0 or quote_amount == 0:
                return None
            
            return {
                'address': pubkey,
                'base_mint': base_mint,
                'quote_mint': quote_mint, 
                'lp_mint': lp_mint,
                'base_amount': base_amount,
                'quote_amount': quote_amount,
                'status': status,
                'version': version,
                'chain': 'solana',
                'pool': pubkey,  # Унифицированный ключ
            }
            
        except Exception as e:
            return None
    
    def get_pool_creation_time(self, pool_address: str) -> Optional[int]:
        """
        Определяем время создания пула через первую транзакцию
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                pool_address,
                {
                    "limit": 1000,  # Берем больше чтобы найти самую старую
                    "commitment": "finalized"
                }
            ]
        }
        
        try:
            response = self.http.quicknode_solana_rpc(payload)
            signatures = response.get('result', [])
            
            if not signatures:
                return None
            
            # Берем самую старую транзакцию (последнюю в списке)
            oldest_tx_sig = signatures[-1].get('signature', '')
            
            if not oldest_tx_sig:
                return None
            
            # Получаем детали транзакции
            tx_payload = {
                "jsonrpc": "2.0",
                "id": 1, 
                "method": "getTransaction",
                "params": [
                    oldest_tx_sig,
                    {
                        "encoding": "json",
                        "maxSupportedTransactionVersion": 0,
                        "commitment": "finalized"
                    }
                ]
            }
            
            tx_response = self.http.quicknode_solana_rpc(tx_payload)
            tx_data = tx_response.get('result', {})
            
            return tx_data.get('blockTime')
            
        except Exception as e:
            self._log_fn(f"Error getting pool creation time for {pool_address}: {e}")
            return None
    
    def batch_get_pool_creation_times(self, pool_addresses: List[str]) -> Dict[str, int]:
        """
        Получаем времена создания для батча пулов одновременно
        """
        results = {}
        
        # Создаем batch запрос
        batch_requests = []
        for i, address in enumerate(pool_addresses):
            batch_requests.append({
                "jsonrpc": "2.0",
                "id": i,
                "method": "getSignaturesForAddress",
                "params": [
                    address,
                    {
                        "limit": 1000,
                        "commitment": "finalized"
                    }
                ]
            })
        
        try:
            responses = self.http.quicknode_batch_rpc(batch_requests)
            
            # Обрабатываем ответы
            for i, response in enumerate(responses):
                if i >= len(pool_addresses):
                    break
                    
                pool_address = pool_addresses[i]
                signatures = response.get('result', [])
                
                if signatures:
                    # Берем самую старую транзакцию
                    oldest_sig = signatures[-1].get('signature', '')
                    if oldest_sig:
                        # Получаем blockTime из самой старой транзакции
                        # Для упрощения используем blockTime из getSignaturesForAddress
                        block_time = signatures[-1].get('blockTime')
                        if block_time:
                            results[pool_address] = block_time
        
        except Exception as e:
            self._log_fn(f"Error in batch_get_pool_creation_times: {e}")
        
        return results
