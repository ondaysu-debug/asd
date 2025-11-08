from __future__ import annotations

from typing import List, Dict, Optional

class EVMPoolCollector:
    """
    Сбор пулов для EVM сетей (Base, Ethereum, BSC) через QuickNode
    """
    
    # Контракты DEX фабрик
    DEX_FACTORIES = {
        "ethereum": {
            "uniswap_v2": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
            "uniswap_v3": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
            "sushiswap": "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac"
        },
        "base": {
            "uniswap_v2": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
            "uniswap_v3": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
            "aerodrome": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
        },
        "bsc": {
            "pancakeswap_v2": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
            "pancakeswap_v3": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"
        }
    }
    
    # PairCreated event signature (Uniswap V2 style)
    PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
    
    # PoolCreated event signature (Uniswap V3 style)
    POOL_CREATED_TOPIC = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"
    
    def __init__(self, cfg, http):
        self.cfg = cfg
        self.http = http
        self._log_fn = lambda msg: print(f"[evm_collector] {msg}")
    
    def get_all_pools(self, network: str) -> List[Dict]:
        """
        Получаем пулы для EVM сети через events
        """
        self._log_fn(f"Fetching pools for {network}...")
        
        # Метод 1: Через события PairCreated (Uniswap V2 style)
        pools_v2 = self._get_pools_via_events(network, "v2")
        
        # Метод 2: Через события PoolCreated (Uniswap V3 style)
        pools_v3 = self._get_pools_via_events(network, "v3")
        
        all_pools = pools_v2 + pools_v3
        self._log_fn(f"Found {len(all_pools)} pools for {network} (v2: {len(pools_v2)}, v3: {len(pools_v3)})")
        
        return all_pools
    
    def _get_pools_via_events(self, network: str, version: str) -> List[Dict]:
        """
        Получаем пулы через чтение событий PairCreated/PoolCreated
        """
        factories = self.DEX_FACTORIES.get(network, {})
        
        if version == "v2":
            factory_key = "uniswap_v2"
            topic = self.PAIR_CREATED_TOPIC
        else:
            factory_key = "uniswap_v3"
            topic = self.POOL_CREATED_TOPIC
        
        factory_address = factories.get(factory_key)
        if not factory_address:
            return []
        
        # ВАЖНО: eth_getLogs с большим диапазоном может быть очень медленным
        # Для production лучше использовать инкрементальный подход или The Graph
        
        # Получаем последние блоки (например последние 10000 блоков)
        try:
            latest_block = self._get_latest_block_number(network)
            from_block = max(0, latest_block - 10000)  # Последние ~10k блоков
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getLogs",
                "params": [{
                    "fromBlock": hex(from_block),
                    "toBlock": "latest", 
                    "address": factory_address,
                    "topics": [topic]
                }]
            }
            
            response = self.http.quicknode_evm_rpc(network, payload)
            return self._parse_pair_events(response, network, version)
            
        except Exception as e:
            self._log_fn(f"Error fetching {version} pools for {network}: {e}")
            return []
    
    def _get_latest_block_number(self, network: str) -> int:
        """Получаем номер последнего блока"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_blockNumber",
            "params": []
        }
        
        try:
            response = self.http.quicknode_evm_rpc(network, payload)
            block_hex = response.get('result', '0x0')
            return int(block_hex, 16)
        except Exception as e:
            self._log_fn(f"Error getting latest block for {network}: {e}")
            return 0
    
    def _parse_pair_events(self, response: Dict, network: str, version: str) -> List[Dict]:
        """
        Парсим события создания пулов
        """
        pools = []
        logs = response.get('result', [])
        
        for log in logs:
            try:
                pool_data = self._parse_single_event(log, network, version)
                if pool_data:
                    pools.append(pool_data)
            except Exception as e:
                continue
        
        return pools
    
    def _parse_single_event(self, log: Dict, network: str, version: str) -> Optional[Dict]:
        """
        Парсим одно событие создания пула
        
        V2 PairCreated: 
        - topic[1]: token0
        - topic[2]: token1
        - data: pair address
        
        V3 PoolCreated:
        - topic[1]: token0
        - topic[2]: token1
        - topic[3]: fee
        - data: pool address
        """
        try:
            topics = log.get('topics', [])
            data = log.get('data', '')
            block_number = int(log.get('blockNumber', '0x0'), 16)
            
            if len(topics) < 3:
                return None
            
            # Извлекаем адреса токенов из topics
            token0 = '0x' + topics[1][-40:]  # Последние 40 символов (20 байт = 40 hex)
            token1 = '0x' + topics[2][-40:]
            
            # Извлекаем адрес пула из data
            if version == "v2":
                # V2: адрес пула в data
                pool_address = '0x' + data[-40:] if data else None
            else:
                # V3: адрес пула также в data
                pool_address = '0x' + data[26:66] if len(data) >= 66 else None
            
            if not pool_address or pool_address == '0x':
                return None
            
            return {
                'address': pool_address.lower(),
                'token0': token0.lower(),
                'token1': token1.lower(),
                'version': version,
                'chain': network,
                'block_number': block_number,
                'pool': pool_address.lower(),  # Унифицированный ключ
                'base_mint': token0.lower(),  # Для совместимости с Solana
                'quote_mint': token1.lower(),
            }
            
        except Exception as e:
            return None
    
    def get_pool_reserves(self, network: str, pool_address: str) -> Optional[Dict]:
        """
        Получаем резервы пула (для V2) через getReserves()
        """
        # getReserves() function signature
        function_sig = "0x0902f1ac"
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [
                {
                    "to": pool_address,
                    "data": function_sig
                },
                "latest"
            ]
        }
        
        try:
            response = self.http.quicknode_evm_rpc(network, payload)
            data = response.get('result', '')
            
            if not data or data == '0x':
                return None
            
            # Парсим результат (3 uint112 значения)
            # reserve0, reserve1, blockTimestampLast
            reserve0 = int(data[2:66], 16)  # Первые 32 байта
            reserve1 = int(data[66:130], 16)  # Вторые 32 байта
            
            return {
                'reserve0': reserve0,
                'reserve1': reserve1
            }
            
        except Exception as e:
            self._log_fn(f"Error getting reserves for {pool_address}: {e}")
            return None
    
    def batch_get_pool_reserves(self, network: str, pool_addresses: List[str]) -> Dict[str, Dict]:
        """
        Получаем резервы для батча пулов одновременно
        """
        results = {}
        function_sig = "0x0902f1ac"
        
        # Создаем batch запрос
        batch_requests = []
        for i, address in enumerate(pool_addresses):
            batch_requests.append({
                "jsonrpc": "2.0",
                "id": i,
                "method": "eth_call",
                "params": [
                    {
                        "to": address,
                        "data": function_sig
                    },
                    "latest"
                ]
            })
        
        try:
            responses = self.http.quicknode_batch_rpc(batch_requests)
            
            for i, response in enumerate(responses):
                if i >= len(pool_addresses):
                    break
                
                pool_address = pool_addresses[i]
                data = response.get('result', '')
                
                if data and data != '0x':
                    reserve0 = int(data[2:66], 16)
                    reserve1 = int(data[66:130], 16)
                    
                    results[pool_address] = {
                        'reserve0': reserve0,
                        'reserve1': reserve1
                    }
        
        except Exception as e:
            self._log_fn(f"Error in batch_get_pool_reserves: {e}")
        
        return results
