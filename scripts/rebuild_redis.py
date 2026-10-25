"""
从 MongoDB 重新构建 Redis 稀缺度排行榜缓存。
当 Redis 服务重启或缓存清空时，可安全地从权威底表全量恢复 ZSet 排行数据。

用法：
    python scripts/rebuild_redis.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import db  # noqa: E402
from app.pipelines import sync_rarity_rank  # noqa: E402


def main():
    collections = list(db.collections.find({}, {"_id": 1}))
    if not collections:
        print("[Warn] 未检测到任何已导入的集合，请先运行 python scripts/import_data.py")
        sys.exit(1)

    for c in collections:
        cid = c["_id"]
        count = sync_rarity_rank(cid)
        print(f"[Success] rank:rarity:{cid} 排行榜构建完成，共计 {count} 件")


if __name__ == "__main__":
    main()
