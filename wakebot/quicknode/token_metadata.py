from __future__ import annotations

from typing import Dict, Optional, List
import json

class QuickNodeTokenMetadata:
    """
    Получение метаданных токенов через QuickNode
    """
    
    def __init__(self, cfg, http):
        self.cfg = cfg
        self.http = http
        self._log_fn = lambda msg: print(f"[token_metadata] {msg}")
        self._cache = {}  # Простой кеш для метаданных
    
    def get_token_metadata(self, token_address: str, chain: str) -> Optional[Dict]:
        """
        Получаем метаданные токена (symbol, name, decimals, total_supply)
        """
        cache_key = f"{chain}:{token_address}"
        
        # Проверяем кеш
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        if chain == "solana":
            metadata = self._get_solana_token_metadata(token_address)
        else:
            metadata = self._get_evm_token_metadata(token_address, chain)
        
        # Кешируем результат
        if metadata:
            self._cache[cache_key] = metadata
        
        return metadata
    
    def _get_solana_token_metadata(self, token_address: str) -> Optional[Dict]:
        """
        Получаем метаданные Solana токена через getAccountInfo
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                token_address,
                {
                    "encoding": "jsonParsed",
                    "commitment": "finalized"
                }
            ]
        }
        
        try:
            response = self.http.quicknode_solana_rpc(payload)
            result = response.get('result', {})
            value = result.get('value', {})
            
            if not value:
                return None
            
            data = value.get('data', {})
            
            # Для SPL токенов данные в parsed формате
            if isinstance(data, dict) and 'parsed' in data:
                parsed = data['parsed']
                info = parsed.get('info', {})
                
                return {
                    'address': token_address,
                    'decimals': info.get('decimals', 9),
                    'supply': info.get('supply', '0'),
                    'chain': 'solana'
                }
            
            return None
            
        except Exception as e:
            self._log_fn(f"Error getting Solana token metadata for {token_address}: {e}")
            return None
    
    def _get_evm_token_metadata(self, token_address: str, chain: str) -> Optional[Dict]:
        """
        Получаем метаданные EVM токена через стандартные ERC20 методы
        """
        # ERC20 function signatures
        name_sig = "0x06fdde03"  # name()
        symbol_sig = "0x95d89b41"  # symbol()
        decimals_sig = "0x313ce567"  # decimals()
        total_supply_sig = "0x18160ddd"  # totalSupply()
        
        # Batch запрос для всех методов
        batch_requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_call",
                "params": [{"to": token_address, "data": name_sig}, "latest"]
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "eth_call",
                "params": [{"to": token_address, "data": symbol_sig}, "latest"]
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "eth_call",
                "params": [{"to": token_address, "data": decimals_sig}, "latest"]
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "eth_call",
                "params": [{"to": token_address, "data": total_supply_sig}, "latest"]
            }
        ]
        
        try:
            responses = self.http.quicknode_batch_rpc(batch_requests)
            
            if len(responses) < 4:
                return None
            
            # Парсим результаты
            name = self._decode_string(responses[0].get('result', ''))
            symbol = self._decode_string(responses[1].get('result', ''))
            decimals = self._decode_uint(responses[2].get('result', '0x'))
            total_supply = self._decode_uint(responses[3].get('result', '0x'))
            
            return {
                'address': token_address,
                'name': name,
                'symbol': symbol,
                'decimals': decimals if decimals is not None else 18,
                'total_supply': total_supply if total_supply is not None else 0,
                'chain': chain
            }
            
        except Exception as e:
            self._log_fn(f"Error getting EVM token metadata for {token_address} on {chain}: {e}")
            return None
    
    def _decode_string(self, hex_data: str) -> str:
        """Декодируем string из hex данных"""
        try:
            if not hex_data or hex_data == '0x':
                return ''
            
            # Убираем 0x prefix
            hex_data = hex_data[2:] if hex_data.startswith('0x') else hex_data
            
            # Конвертируем в bytes
            data_bytes = bytes.fromhex(hex_data)
            
            # Пропускаем первые 64 байта (offset + length)
            if len(data_bytes) < 64:
                return ''
            
            # Читаем длину строки
            length = int.from_bytes(data_bytes[32:64], 'big')
            
            # Читаем саму строку
            if len(data_bytes) < 64 + length:
                return ''
            
            string_bytes = data_bytes[64:64 + length]
            return string_bytes.decode('utf-8', errors='ignore')
            
        except Exception:
            return ''
    
    def _decode_uint(self, hex_data: str) -> Optional[int]:
        """Декодируем uint из hex данных"""
        try:
            if not hex_data or hex_data == '0x':
                return None
            
            return int(hex_data, 16)
            
        except Exception:
            return None
    
    def batch_get_token_metadata(self, token_addresses: List[str], chain: str) -> Dict[str, Dict]:
        """
        Получаем метаданные для батча токенов
        """
        results = {}
        
        for token_address in token_addresses:
            metadata = self.get_token_metadata(token_address, chain)
            if metadata:
                results[token_address] = metadata
        
        return results
