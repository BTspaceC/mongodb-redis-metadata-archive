"""
Cache-Aside (旁路缓存) 模块与高可用容灾封装

核心策略：
1. 读流程：先查 Redis -> 命中直接返回；未命中查 MongoDB -> 回写 Redis 并返回。
2. 写流程：先写 MongoDB -> 成功后立即删除 Redis 缓存（Cache Invalidation）。
3. 容灾机制：
   - 缓存穿透防范：空值缓存 (Null Caching)，TTL 为 60 秒。
   - 缓存雪崩防范：TTL 随机抖动 (Jitter ±10%)，避免同批数据集中过期。
   - 缓存击穿防范：分布式互斥锁 (SET NX)，针对热点 Key 重建限流。
   - 降级保护：Redis 宕机或连接超时自动降级直查底表 (X-Cache: BYPASS)。
"""
import json
import random
import time
from typing import Any, Callable, Optional, Tuple

import redis

from app.db import rds

TOKEN_TTL = 600      # 藏品详情缓存 10 分钟
STATS_TTL = 3600     # 聚合结果缓存 1 小时
NULL_TTL = 60        # 空值占位缓存 60 秒
LOCK_TTL = 5         # 分布式锁超时 5 秒
NULL_MARKER = "__NULL__"  # 空值占位标识


def jitter(ttl: int) -> int:
    """为基础 TTL 增加 ±10% 的随机抖动，分散过期峰值，防范缓存雪崩。"""
    spread = max(1, ttl // 10)
    return ttl + random.randint(-spread, spread)


def acquire_lock(lock_key: str, expire: int = LOCK_TTL) -> bool:
    """使用 Redis SET NX EX 原子操作获取分布式互斥锁，用于防御热点 Key 缓存击穿。"""
    try:
        return bool(rds.set(lock_key, "1", nx=True, ex=expire))
    except redis.RedisError:
        return True  # Redis 异常时放行，降级直查底表


def release_lock(lock_key: str) -> None:
    """释放分布式互斥锁。"""
    try:
        rds.delete(lock_key)
    except redis.RedisError:
        pass


def get_or_load(key: str, loader: Callable[[], Any], ttl: int) -> Tuple[Any, str]:
    """
    Cache-Aside 读取流程封装。
    :param key: Redis 键名
    :param loader: 缓存未命中时执行的数据库查询闭包
    :param ttl: 基础缓存生存时间（秒）
    :return: (数据对象, 缓存状态: "HIT" | "MISS" | "BYPASS")
    """
    try:
        cached = rds.get(key)
    except redis.RedisError:
        return loader(), "BYPASS"  # 缓存不可用，自动降级穿透查底表

    if cached is not None:
        if cached == NULL_MARKER:
            return None, "HIT"  # 命中空值缓存，阻断无效穿透
        return json.loads(cached), "HIT"

    # 缓存未命中，执行底表加载
    data = loader()

    try:
        if data is None:
            rds.set(key, NULL_MARKER, ex=NULL_TTL)
        else:
            # 序列化入库，包含 TTL Jitter
            serialized = json.dumps(data, default=lambda o: o.isoformat(), ensure_ascii=False)
            rds.set(key, serialized, ex=jitter(ttl))
    except redis.RedisError:
        pass  # 回写缓存失败不影响本次业务主链路响应

    return data, "MISS"


def delete(key: str) -> None:
    """删除指定 Key 缓存，用于数据变更时的即时失效。"""
    try:
        rds.delete(key)
    except redis.RedisError:
        pass


def clear_prefix(prefix: str) -> int:
    """
    按前缀迭代清除匹配的所有缓存 Key。
    使用 SCAN 游标分批处理，严禁在生产中使用阻塞式的 KEYS * 指令。
    """
    count = 0
    try:
        for key in rds.scan_iter(match=f"{prefix}*", count=500):
            rds.delete(key)
            count += 1
    except redis.RedisError:
        pass
    return count
