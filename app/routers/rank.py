"""
排行榜接口：名次和分数都来自 Redis 的 ZSet，再去 MongoDB 补上名称和图片用于展示。
"""
import redis
from fastapi import APIRouter, Response

from app.db import db, rds

router = APIRouter(prefix="/api/rank")


def top_n(key, cid, n):
    # ZREVRANGE：按 score 从高到低取前 n 个（新版 Redis 也可以写成 ZRANGE key 0 n-1 REV）
    pairs = rds.zrevrange(key, 0, n - 1, withscores=True)
    ids = [f"{cid}:{member}" for member, _ in pairs]
    # 名称和图片不存 Redis，用一次 $in 查询从 MongoDB 补全
    info = {t["_id"]: t for t in db.tokens.find({"_id": {"$in": ids}}, {"name": 1, "image": 1, "rarity": 1})}
    result = []
    for i, (member, score) in enumerate(pairs):
        t = info.get(f"{cid}:{member}", {})
        result.append({
            "position": i + 1,
            "token_id": int(member),
            "score": score,
            "name": t.get("name"),
            "image": t.get("image"),
            "rarity": t.get("rarity"),
        })
    return result


@router.get("/rarity/{cid}")
def rarity_rank(cid: str, response: Response, n: int = 50):
    """稀有度排行，score = 稀有度分。"""
    try:
        response.headers["X-Source"] = "redis"
        return top_n(f"rank:rarity:{cid}", cid, n)
    except redis.RedisError:
        # Redis 不可用时降级：稀有度本来就存在 MongoDB 里，直接按排名索引查
        response.headers["X-Source"] = "mongodb"
        tokens = db.tokens.find({"collection_id": cid, "rarity.rank": {"$exists": True}},
                                {"token_id": 1, "name": 1, "image": 1, "rarity": 1}
                                ).sort([("rarity.rank", 1), ("token_id", 1)]).limit(n)
        return [{"position": i + 1, "token_id": t["token_id"], "score": t["rarity"]["score"],
                 "name": t["name"], "image": t["image"], "rarity": t["rarity"]}
                for i, t in enumerate(tokens)]


@router.get("/views/{cid}")
def views_rank(cid: str, response: Response, n: int = 20):
    """浏览热度排行，score = 浏览次数。"""
    try:
        response.headers["X-Source"] = "redis"
        return top_n(f"rank:views:{cid}", cid, n)
    except redis.RedisError:
        # 浏览计数只存在 Redis 里，Redis 不可用时没有数据可以返回
        response.headers["X-Source"] = "unavailable"
        return []
