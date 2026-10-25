"""
服务探针与健康检查脚本。
供 start.bat 及生产探针快速检测 MongoDB 与 Redis 连通性。

用法：
    python scripts/check_services.py mongo          # 检查 MongoDB
    python scripts/check_services.py redis          # 检查 Redis
    python scripts/check_services.py wait-redis     # 轮询等待 Redis 就绪 (最多 30 秒)
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402
from app.db import MONGO_URI, rds  # noqa: E402


def check_mongo() -> bool:
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        return True
    except Exception:
        return False


def check_redis() -> bool:
    try:
        return bool(rds.ping())
    except Exception:
        return False


def wait_redis(timeout: int = 30) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if check_redis():
            return True
        time.sleep(1)
    return False


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "mongo"
    if action == "mongo":
        sys.exit(0 if check_mongo() else 1)
    elif action == "redis":
        sys.exit(0 if check_redis() else 1)
    elif action == "wait-redis":
        sys.exit(0 if wait_redis() else 1)
    else:
        print(f"Unknown action: {action}")
        sys.exit(2)
