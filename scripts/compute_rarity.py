"""
计算稀有度：跑 app/pipelines.py 里的两条聚合管道，自检，并把排行同步到 Redis。

用法：
    python scripts/compute_rarity.py                # 计算所有系列
    python scripts/compute_rarity.py pudgypenguins  # 只算一个系列
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import db  # noqa: E402
from app.pipelines import compute_rarity  # noqa: E402

cids = sys.argv[1:] or [c["_id"] for c in db.collections.find({}, {"_id": 1})]
for cid in cids:
    result = compute_rarity(cid)
    print(result)
    if not (result.get("frequency_check") and result.get("rank_check")):
        sys.exit(f"[{cid}] 自检未通过")

print("稀有度前 5：")
for t in db.tokens.find({"collection_id": "pudgypenguins"},
                        {"name": 1, "rarity.score": 1, "rarity.rank": 1}).sort("rarity.rank", 1).limit(5):
    print(" ", t["rarity"]["rank"], t["name"], t["rarity"]["score"])
