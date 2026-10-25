"""
数据库与缓存连接池管理模块
统一初始化并导出全局 MongoDB 与 Redis 客户端单例。
"""
import os
from pathlib import Path
from typing import Tuple

import redis
from dotenv import load_dotenv
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# MongoDB 连接池配置（权威持久化数据源）
mongo = MongoClient(MONGO_URI, tz_aware=True, serverSelectionTimeoutMS=2000)
db = mongo["nft_archive"]

# Redis 客户端配置（高并发缓存与实时排行）
# 设置合理的短超时时间（1s），确保 Redis 异常时不阻塞 Web 线程
rds = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1
)


def ping_services() -> Tuple[bool, bool]:
    """检查底层 MongoDB 与 Redis 服务存活状态。"""
    mongo_ok, redis_ok = False, False
    try:
        mongo.admin.command("ping")
        mongo_ok = True
    except Exception:
        pass

    try:
        redis_ok = bool(rds.ping())
    except Exception:
        pass

    return mongo_ok, redis_ok
