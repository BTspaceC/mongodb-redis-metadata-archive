"""
系统管理与监控接口：重算特征稀缺度、清空缓存、获取实时统计指标。
"""
import redis
from fastapi import APIRouter, HTTPException

from app import cache, pipelines
from app.db import db, rds

router = APIRouter(prefix="/api/admin")


@router.post("/recompute/{cid}")
def recompute(cid: str):
    """重新跑两条稀有度管道，并刷新 Redis 排行榜。返回值里带耗时和自检结果。"""
    return pipelines.compute_rarity(cid)


@router.post("/cache/clear")
def clear_cache():
    """只删 token:* 和 stats:* 两类缓存，不动排行榜（rank:*）。"""
    try:
        return {
            "token_keys_deleted": cache.clear_prefix("token:"),
            "stats_keys_deleted": cache.clear_prefix("stats:"),
        }
    except redis.RedisError:
        raise HTTPException(503, "Redis 不可用")


@router.get("/status")
def status():
    """获取系统底层 MongoDB 与 Redis 的实时监控统计指标。"""
    cids = [c["_id"] for c in db.collections.find({}, {"_id": 1})]
    try:
        redis_info = {
            "token_cache_keys": sum(1 for _ in rds.scan_iter("token:*", count=500)),
            "stats_cache_keys": sum(1 for _ in rds.scan_iter("stats:*", count=500)),
            "rarity_rank_size": {cid: rds.zcard(f"rank:rarity:{cid}") for cid in cids},
            "views_rank_size": {cid: rds.zcard(f"rank:views:{cid}") for cid in cids},
        }
    except redis.RedisError:
        redis_info = "Redis 不可用（网站已降级为直接查 MongoDB）"
    return {
        "mongodb": {
            "collections": db.collections.count_documents({}),
            "tokens": db.tokens.count_documents({}),
            "trait_stats": db.trait_stats.count_documents({}),
        },
        "redis": redis_info,
    }
