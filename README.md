# MongoDB + Redis 元数据档案与稀缺度分析引擎

一个用 MongoDB 做聚合统计、用 Redis 做缓存与排行、用 FastAPI 做查询服务的元数据档案系统。演示数据集为 9,188 条公开元数据快照（已存本地，见 `data/raw/`），不做价格、交易、钱包功能。

## 解决什么问题

元数据的特征维度不固定：不同系列的特征数量和字段名都不一样，按编号查很容易，按特征组合筛选很难。本项目用一套统一的建模 + 索引 + 聚合方案解决这个问题：

- **建模**：属性模式（Attribute Pattern），特征存为 `[{trait_type, value}]` 数组，维度不同也能共用同一套查询和索引。
- **索引**：`(collection_id, token_id)` 唯一索引、多键索引 `(attributes.trait_type, attributes.value)`、稀有度排序索引；核心字段用 `$jsonSchema` 校验。
- **聚合**：两条 MongoDB 聚合管道算稀有度并写回文档，详见下文。
- **缓存**：Redis 只放可重建的热数据，MongoDB 是唯一权威源。

## 稀有度口径

统计稀有度，公式为每件藏品各维度 `1 / 频率` 之和：

```
score = Σ (1 / frequency)，frequency = 该特征值出现次数 / 系列总件数
```

缺某个维度时补一条 `value: "None"`，这样每个维度的频率之和恰好为 1；总分先四舍五入到两位小数再排名，同分并列。

## MongoDB：两条聚合管道

`app/pipelines.py`，另有特征分布、分桶、系列对比三条统计聚合：

1. 特征频次：`$match → $unwind → $group → $set → $merge`，统计每个特征值的出现次数和频率，写入 `trait_stats`。
2. 稀有度与排名：`$unwind → $lookup → $group → $setWindowFields ($rank) → $merge`，算分、排名并写回 `tokens.rarity`，并做频率和为 1、每件都有排名两项自检。

`nft_archive` 库 3 个集合：`collections`（系列信息）、`tokens`（一件藏品一个文档，特征、稀有度、转移记录内嵌，转移记录只留最近 20 条）、`trait_stats`（特征值频次）。

## Redis：Cache-Aside + ZSet 排行

`app/cache.py`，详见 `docs/ARCHITECTURE.md`：

- **详情缓存**：String，10 分钟 TTL；**聚合结果缓存**：String，1 小时 TTL；TTL 加 ±10% 随机抖动，防雪崩。
- **空值缓存**：查不到的编号也缓存 60 秒，防穿透；**互斥锁**：热点 Key 重建用 `SET NX`，防击穿。
- **排行**：两个 ZSet，稀有度排行和浏览热度（`ZINCRBY` 自增）；重算后整体重写，丢了可从 MongoDB 重建。
- **降级**：Redis 不可用时直接查 MongoDB（响应头 `X-Cache: BYPASS`），只有浏览热度榜暂时为空。

## 服务与测试

- FastAPI + 原生 HTML/JS，6 个页面：首页、浏览、详情、排行、统计、演示控制台；接口文档在 `/docs`。
- 测试：`tests/` 共 12 项（ETL、缓存、API），用 mongomock / fakeredis，离线可跑：`pytest tests/ -q`。
- 管理接口（重算、清缓存）没有登录权限控制，只适合本机演示，不要直接暴露到公网。

## 快速开始

```bash
docker compose up -d   # 或本机 MongoDB + Redis
pip install -r requirements.txt
cp .env.example .env
python scripts/import_data.py
python scripts/compute_rarity.py
uvicorn app.main:app --port 8000
```

打开 <http://localhost:8000>。重新采集数据才需要联网（`scripts/fetch_*.py`），日常导入和运行只读本地快照，不需要 API key。图片默认走线上指引加载，断网演示可跑 `scripts/download_images.py` 缓存到本地。
