"""
统计接口：聚合结果走 Redis 缓存（TTL 1 小时，重算稀有度后主动删除）。
"""
import time

from fastapi import APIRouter, Response

from app import cache, pipelines

router = APIRouter(prefix="/api/stats")


def cached_stats(key, loader, response):
    start = time.perf_counter()
    data, status = cache.get_or_load(key, loader, cache.STATS_TTL)
    response.headers["X-Cache"] = status
    response.headers["X-Query-Ms"] = f"{(time.perf_counter() - start) * 1000:.2f}"
    return data


@router.get("/compare")
def compare(response: Response):
    """系列对比。"""
    return cached_stats("stats:all:compare", pipelines.compare_collections, response)


@router.get("/{cid}/traits")
def traits(cid: str, response: Response):
    """特征分布。"""
    return cached_stats(f"stats:{cid}:traits", lambda: pipelines.trait_distribution(cid), response)


@router.get("/{cid}/rarity-buckets")
def rarity_buckets(cid: str, response: Response):
    """稀有度分数分桶。"""
    return cached_stats(f"stats:{cid}:rarity-buckets", lambda: pipelines.rarity_buckets(cid), response)
