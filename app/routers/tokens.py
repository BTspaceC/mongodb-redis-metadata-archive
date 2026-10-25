"""
藏品相关接口：系列列表、浏览筛选、详情（走缓存）、修改标签备注。
"""
import time
from datetime import datetime, timezone

import redis
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app import cache
from app.db import db, rds

router = APIRouter(prefix="/api")

PAGE_SIZE = 24


@router.get("/collections")
def list_collections():
    """系列列表，直接读 MongoDB 的 collections 集合。"""
    return list(db.collections.find())


@router.get("/tokens")
def list_tokens(collection: str = "pudgypenguins", traits: str = "", sort: str = "rarity", page: int = 1):
    """
    浏览与筛选。traits 的格式是「维度:取值,维度:取值」。
    同一维度选了多个取值是「或」，不同维度之间是「且」。
    """
    query = {"collection_id": collection}

    # 把 "Background:Blue,Background:Red,Head:Crown" 整理成 {"Background": ["Blue","Red"], "Head": ["Crown"]}
    wanted = {}
    for part in traits.split(","):
        if ":" in part:
            t, v = part.split(":", 1)
            wanted.setdefault(t, []).append(v)

    if wanted:
        # $elemMatch：要求数组里「同一个元素」同时满足 trait_type 和 value
        # $all：每个维度的条件都要满足。这个查询会用到 attributes 上的多键索引
        query["attributes"] = {"$all": [
            {"$elemMatch": {"trait_type": t, "value": {"$in": values}}}
            for t, values in wanted.items()
        ]}

    order = [("token_id", 1)] if sort == "id" else [("rarity.rank", 1), ("token_id", 1)]
    page = max(page, 1)
    total = db.tokens.count_documents(query)
    # 列表页只需要少数几个字段，用投影减少传输量
    items = list(
        db.tokens.find(query, {"token_id": 1, "name": 1, "image": 1, "rarity": 1, "collection_id": 1})
        .sort(order)
        .skip((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    return {"total": total, "page": page, "page_size": PAGE_SIZE, "items": items}


def load_token(cid, tid):
    """缓存未命中时调用：从 MongoDB 查一件藏品，并附上每个特征值的占比。"""
    token = db.tokens.find_one({"_id": f"{cid}:{tid}"})
    if token is None:
        return None
    # 一次查询取回这件藏品所有特征值的统计（_id 是内嵌文档，用 $in 批量匹配）
    keys = [{"c": cid, "t": a["trait_type"], "v": a["value"]} for a in token["attributes"]]
    stats = {(s["_id"]["t"], s["_id"]["v"]): s for s in db.trait_stats.find({"_id": {"$in": keys}})}
    for a in token["attributes"]:
        s = stats.get((a["trait_type"], a["value"]))
        a["count"] = s["count"] if s else None
        a["frequency"] = s["frequency"] if s else None
    return token


@router.get("/tokens/{cid}/{tid}")
def get_token(cid: str, tid: int, response: Response):
    """详情：Cache-Aside 读缓存，并给浏览热度榜加 1。"""
    start = time.perf_counter()
    token, status = cache.get_or_load(f"token:{cid}:{tid}", lambda: load_token(cid, tid), cache.TOKEN_TTL)
    ms = (time.perf_counter() - start) * 1000

    # 响应头指示当前缓存命中状态与查询耗时，供前端性能指标展示
    response.headers["X-Cache"] = status
    response.headers["X-Query-Ms"] = f"{ms:.2f}"

    if token is None:
        raise HTTPException(404, "藏品不存在", headers=dict(response.headers))

    # 浏览计数是高频小写入，放 Redis 的 ZSet 里：member = 编号，score = 浏览次数
    try:
        token["views"] = int(rds.zincrby(f"rank:views:{cid}", 1, str(tid)))
    except redis.RedisError:
        token["views"] = None  # Redis 不可用时不计数，页面显示「暂无」
    return token


class TokenPatch(BaseModel):
    tags: list[str] | None = None
    notes: str | None = None


@router.patch("/tokens/{cid}/{tid}")
def patch_token(cid: str, tid: int, body: TokenPatch):
    """改标签、备注。写操作的顺序：先更新 MongoDB，再删除 Redis 缓存。"""
    changes = {"updated_at": datetime.now(timezone.utc)}
    if body.tags is not None:
        changes["tags"] = body.tags
    if body.notes is not None:
        changes["notes"] = body.notes

    result = db.tokens.update_one({"_id": f"{cid}:{tid}"}, {"$set": changes})
    if result.matched_count == 0:
        raise HTTPException(404, "藏品不存在")

    # 删掉缓存而不是改缓存：下次读的时候自然会从 MongoDB 加载最新数据
    cache.delete(f"token:{cid}:{tid}")
    return {"ok": True}
