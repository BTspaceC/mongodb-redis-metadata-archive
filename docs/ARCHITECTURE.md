# 系统架构与工程设计文档

本项目是一个高性能元数据归档、统计稀缺度分析与实时排行系统。核心技术栈基于 **FastAPI + MongoDB 7.0 + Redis 7.0 + 现代原生前端** 构建，专为非结构化链上元数据的快速索引、高并发复杂聚合与毫秒级查询设计。

---

## 1. 系统整体架构

系统采用清晰的分层解耦设计，包含数据采集清洗层、存储与聚合层、缓存加速层及 Web 服务交互层：

```text
               +-------------------------------------------------+
               |             Web Frontend (Dashboard)           |
               |  (Native HTML5 / ES6 Module / ECharts / CSS)    |
               +-----------------------+-------------------------+
                                       | HTTP RESTful API
                                       v
               +-------------------------------------------------+
               |               FastAPI Web Server                |
               | (Async ASGI / Routers / Pydantic / StaticMount) |
               +-----------+-------------------------+-----------+
                           |                         |
               Cache-Aside |                         | Query & Aggregate
                           v                         v
               +-----------------------+ +-----------------------+
               |     Redis 7.0 (ZSet)  | |     MongoDB 7.0       |
               | - String: Token Cache | | - tokens (JSONSchema) |
               | - ZSet: Rarity Rank   | | - trait_stats (Merge) |
               | - ZSet: Views Rank    | | - collections (Meta)  |
               +-----------------------+ +-----------------------+
                           ^                         ^
                           | Write Ranks             | Bulk Import
                           +------------+------------+
                                        |
               +------------------------+------------------------+
               |           Data Pipeline & ETL Engine            |
               | (Alchemy NFT API / Pinata IPFS Gateway / Clean) |
               +-------------------------------------------------+
```

---

## 2. 核心存储模型设计

### 2.1 MongoDB 关系与模式验证 (`$jsonSchema`)
针对 NFT 元数据特征维度多变、同类藏品属性不规整的问题，采用 **属性模式（Attribute Pattern）** 建模：

```json
{
  "_id": "pudgypenguins:1234",
  "collection_id": "pudgypenguins",
  "token_id": 1234,
  "name": "Pudgy Penguin #1234",
  "image": {
    "cached": "https://nft2-cdn.alchemy.com/...",
    "thumb": "https://nft2-cdn.alchemy.com/cdn-cgi/...",
    "original": "https://ipfs.io/ipfs/...",
    "source": "ipfs://...",
    "local": null
  },
  "attributes": [
    { "trait_type": "Background", "value": "Beige" },
    { "trait_type": "Head", "value": "Headband" }
  ],
  "trait_count": 5,
  "rarity": {
    "score": 142.85,
    "rank": 88,
    "method": "statistical",
    "computed_at": "2026-03-30T12:00:00Z"
  },
  "transfers": [ ... ],
  "tags": [],
  "notes": "",
  "updated_at": "..."
}
```

* **索引优化**：
  * `{ collection_id: 1, token_id: 1 }`：全局唯一索引，定位单件藏品。
  * `{ "attributes.trait_type": 1, "attributes.value": 1 }`：复合多键索引（Multikey Index），支撑高并发多维度属性筛选。
  * `{ collection_id: 1, "rarity.rank": 1 }`：稀缺度分级查询索引。

---

## 3. 统计稀缺度算法与聚合管道

### 3.1 稀缺度计算口径
系统采用业界通用的统计倒数模型（Trait Rarity Score）：
$$RarityScore = \sum_{i=1}^{N} rac{1}{Frequency_i} = \sum_{i=1}^{N} rac{TotalTokens}{Count(Trait_i)}$$

当藏品缺失某一维度时，由数据管道自动补全 `value: "None"`，确保特征频率归一化。

### 3.2 高性能 MongoDB 管道设计
1. **特征频次聚合管道**：通过 `$unwind` 展开、`$group` 聚合特征频次，并经 `$merge` 存入 `trait_stats` 集合。
2. **总分计算与窗口排名管道**：
   * 采用 `$lookup` 关联特征频次；
   * 通过 `$addFields` 累加特征倒数，四舍五入保留两位小数；
   * 利用 MongoDB 5.0+ `$setWindowFields` 窗口算子计算 `rank`（处理同分并列情形）；
   * 通过 `$merge` 高性能批量写回 `tokens` 集合。

---

## 4. Redis 高并发缓存与降级机制

采用 **Cache-Aside（旁路缓存）** 策略，并具备生产级容灾设计：
1. **TTL 抖动（Jitter）**：基础 TTL 600 秒增加 $\pm 10\%$ 随机抖动，彻底防范缓存雪崩。
2. **空值缓存（Null Caching）**：对不存在的 Token ID 写入 60 秒短期空值缓存，防止恶意穿透。
3. **ZSet 毫秒级排行榜**：
   * `rank:rarity:{cid}`：存储稀缺度总分，支持 $O(\log(N) + M)$ 分页。
   * `rank:views:{cid}`：原子级 `ZINCRBY` 实现高频热度自增。
4. **自动降级保护**：当 Redis 异常或离线时，系统自动切换为 MongoDB 索引查询（响应头携带 `X-Cache: BYPASS`），保障主链路 100% 可用。
