"""
所有 MongoDB 聚合管道都集中在这个文件。
scripts/compute_rarity.py 和网站的「重新计算」按钮共用 compute_rarity()。

稀有度口径（统计稀有度）：
    score(藏品) = 各维度 1 / frequency 之和，frequency = 该特征值出现次数 / 系列总件数
特征值越少见，frequency 越小，1/frequency 越大，总分越高。
"""
import time

import redis

from app import cache
from app.db import db, rds


def trait_stats_pipeline(cid, n):
    """管道一：统计每个特征值的出现次数和频率，结果写入 trait_stats 集合。"""
    return [
        # 只算一个系列
        {"$match": {"collection_id": cid}},
        # 把 attributes 数组拆开：一件藏品有 k 个特征，就变成 k 行
        {"$unwind": "$attributes"},
        # 按（系列, 维度, 取值）分组，数一数每个特征值出现了几次
        {"$group": {
            "_id": {"c": "$collection_id", "t": "$attributes.trait_type", "v": "$attributes.value"},
            "count": {"$sum": 1},
        }},
        # 频率 = 出现次数 / 系列总件数（n 由程序先用 count_documents 得到）
        {"$set": {"frequency": {"$divide": ["$count", n]}}},
        # 把结果写进 trait_stats；_id 相同就整条替换，所以可以反复重算
        {"$merge": {"into": "trait_stats", "whenMatched": "replace", "whenNotMatched": "insert"}},
    ]


def rarity_pipeline(cid):
    """管道二：给每件藏品算总分、排名，写回 tokens.rarity。"""
    return [
        {"$match": {"collection_id": cid}},
        {"$unwind": "$attributes"},
        # 拼出和 trait_stats._id 一模一样的 key（字段顺序 c、t、v 必须一致，内嵌文档比较看顺序）
        {"$set": {"k": {"c": "$collection_id", "t": "$attributes.trait_type", "v": "$attributes.value"}}},
        # 关联 trait_stats，拿到这个特征值的频率（相当于 SQL 的 LEFT JOIN）
        {"$lookup": {"from": "trait_stats", "localField": "k", "foreignField": "_id", "as": "stat"}},
        # $lookup 的结果是数组，拆成单个文档
        {"$unwind": "$stat"},
        # 再按藏品分组，把各维度的 1/frequency 加起来得到总分
        {"$group": {"_id": "$_id", "score": {"$sum": {"$divide": [1, "$stat.frequency"]}}}},
        # 先四舍五入到两位小数再排名：浮点数相加的顺序不同会产生极小误差，
        # 不先取整的话，页面上分数相同的两件藏品名次可能不同
        {"$set": {"score": {"$round": ["$score", 2]}}},
        # 窗口函数：按总分从高到低排名（需要 MongoDB 5.0+）；同分并列
        {"$setWindowFields": {"sortBy": {"score": -1}, "output": {"rank": {"$rank": {}}}}},
        # 整理成 tokens 里 rarity 字段的形状
        {"$project": {"rarity": {
            "score": "$score",
            "rank": "$rank",
            "method": "statistical",
            "computed_at": "$$NOW",
        }}},
        # 按 _id 合并回 tokens：只更新 rarity 字段，其他字段不动；找不到的丢弃
        {"$merge": {"into": "tokens", "on": "_id", "whenMatched": "merge", "whenNotMatched": "discard"}},
    ]


def sync_rarity_rank(cid):
    """把 MongoDB 里的稀有度分同步到 Redis 排行榜（ZSet）。Redis 丢了也能靠这个函数重建。"""
    key = f"rank:rarity:{cid}"
    # 只取编号和分数
    cursor = db.tokens.find({"collection_id": cid, "rarity.score": {"$exists": True}},
                            {"token_id": 1, "rarity.score": 1})
    mapping = {str(t["token_id"]): t["rarity"]["score"] for t in cursor}
    pipe = rds.pipeline()   # 管道：多条命令一次发给 Redis，减少网络往返
    pipe.delete(key)        # 整体重写：先删旧榜
    if mapping:
        pipe.zadd(key, mapping)  # member = 编号，score = 稀有度分
    pipe.execute()
    return len(mapping)


def compute_rarity(cid):
    """跑完两条管道 + 自检 + 同步 Redis，返回耗时等信息。"""
    start = time.perf_counter()
    n = db.tokens.count_documents({"collection_id": cid})
    if n == 0:
        return {"collection": cid, "tokens": 0, "error": "该系列没有数据"}

    # 先清掉这个系列旧的统计，避免残留已经不存在的特征值
    db.trait_stats.delete_many({"_id.c": cid})
    db.tokens.aggregate(trait_stats_pipeline(cid, n))
    db.tokens.aggregate(rarity_pipeline(cid))

    # 自检一：同一维度下所有取值的 frequency 之和应为 1
    sums = list(db.trait_stats.aggregate([
        {"$match": {"_id.c": cid}},
        {"$group": {"_id": "$_id.t", "total": {"$sum": "$frequency"}}},
    ]))
    freq_ok = all(abs(s["total"] - 1) < 1e-6 for s in sums)
    # 自检二：每件藏品都有排名
    ranked = db.tokens.count_documents({"collection_id": cid, "rarity.rank": {"$exists": True}})

    # 同步 Redis 排行榜，并删掉已经过期的聚合缓存
    try:
        synced = sync_rarity_rank(cid)
        cache.clear_prefix(f"stats:{cid}:")
        cache.clear_prefix(f"token:{cid}:")  # 详情里带着稀有度，也要失效
        cache.delete("stats:all:compare")
    except redis.RedisError:
        # 稀有度已经写进 MongoDB 了；Redis 恢复后运行 scripts/rebuild_redis.py 重建排行榜即可
        synced = "Redis 不可用，未同步"

    return {
        "collection": cid,
        "tokens": n,
        "trait_types": len(sums),
        "frequency_check": freq_ok,
        "ranked": ranked,
        "rank_check": ranked == n,
        "redis_synced": synced,
        "seconds": round(time.perf_counter() - start, 3),
    }


# ---------- 统计页用的三个较简单的聚合 ----------

def trait_distribution(cid):
    """特征分布：读 trait_stats，按维度分组，列出每个取值的件数和占比。"""
    return list(db.trait_stats.aggregate([
        {"$match": {"_id.c": cid}},
        {"$sort": {"count": -1}},  # 先按件数排好，$push 进数组时就是有序的
        {"$group": {
            "_id": "$_id.t",
            "values": {"$push": {"value": "$_id.v", "count": "$count", "frequency": "$frequency"}},
        }},
        {"$project": {"_id": 0, "trait_type": "$_id", "values": 1}},
        {"$sort": {"trait_type": 1}},
    ]))


# 分数区间的边界。稀有度分是长尾分布（绝大多数一两百分，极少数几万分），所以前面切得细、后面切得粗
SCORE_BOUNDARIES = [0, 80, 100, 120, 140, 160, 180, 200, 250, 300, 400, 500, 750, 1000, 2000]


def rarity_buckets(cid):
    """稀有度分桶：$bucket 按固定边界把总分分段，统计每段件数，用来画直方图。"""
    buckets = list(db.tokens.aggregate([
        {"$match": {"collection_id": cid, "rarity.score": {"$exists": True}}},
        {"$bucket": {
            "groupBy": "$rarity.score",
            "boundaries": SCORE_BOUNDARIES,   # 左闭右开：[0,80)、[80,100) ...
            "default": "2000+",               # 超过最后一个边界的都归到这一桶
            "output": {"count": {"$sum": 1}},
        }},
    ]))
    # 把桶的下界换成好读的区间文字，例如 100 -> "100–120"
    result = []
    for b in buckets:
        if b["_id"] == "2000+":
            label = "2000+"
        else:
            upper = SCORE_BOUNDARIES[SCORE_BOUNDARIES.index(b["_id"]) + 1]
            label = f"{b['_id']}–{upper}"
        result.append({"range": label, "count": b["count"]})
    return result


def compare_collections():
    """系列对比：按 collection_id 分组，统计件数、平均特征数、平均稀有度分。"""
    return list(db.tokens.aggregate([
        {"$group": {
            "_id": "$collection_id",
            "tokens": {"$sum": 1},
            "avg_trait_count": {"$avg": "$trait_count"},
            "avg_score": {"$avg": "$rarity.score"},
            "max_score": {"$max": "$rarity.score"},
        }},
        {"$project": {"_id": 0, "collection_id": "$_id", "tokens": 1,
                      "avg_trait_count": {"$round": ["$avg_trait_count", 2]},
                      "avg_score": {"$round": ["$avg_score", 2]},
                      "max_score": 1}},
        {"$sort": {"tokens": -1}},
    ]))
