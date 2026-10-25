"""
导入脚本：读 data/raw 下的本地快照 -> 清洗 -> 写入 MongoDB -> 建校验器和索引。
全程不联网、不需要 API key。可以反复运行（每次先删掉该系列旧数据再导入）。

用法：
    python scripts/import_data.py            # 导入 data/raw 下的所有系列
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 让脚本能 import app 包

from app.db import db  # noqa: E402

# 系列的固定信息（合约地址已在 Etherscan 上核对）
COLLECTIONS = {
    "pudgypenguins": {"name": "Pudgy Penguins", "contract": "0xBd3531dA5CF5857e7CfAA92426877b022e612cf8"},
    "azuki": {"name": "Azuki", "contract": "0xED5AF388653567Af2F388E6224dC7C4b3241C544"},
}

# 重点藏品焦点采样：导入时标记 showcase 标签以支持样本优先索引
SHOWCASE = {"pudgypenguins": [0, 1, 1234, 6873, 8887]}

# tokens 集合的校验器：只强制三个核心字段，其余字段完全放开。
# 回答「灵活 schema 会不会让数据变乱」：核心字段有约束，扩展字段才灵活。
TOKENS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["collection_id", "token_id", "attributes"],
        "properties": {
            "collection_id": {"bsonType": "string", "description": "所属系列，必填"},
            "token_id": {"bsonType": ["int", "long"], "minimum": 0, "description": "藏品编号，必填"},
            "attributes": {
                "bsonType": "array",
                "description": "特征数组，每个元素必须有 trait_type 和 value",
                "items": {"bsonType": "object", "required": ["trait_type", "value"]},
            },
        },
    }
}


def setup_collection():
    """创建 tokens 集合并挂上校验器；集合已存在就用 collMod 更新校验器。然后建索引。"""
    if "tokens" not in db.list_collection_names():
        db.create_collection("tokens", validator=TOKENS_VALIDATOR)
    else:
        db.command("collMod", "tokens", validator=TOKENS_VALIDATOR)

    # 索引一：按（系列, 编号）查，唯一
    db.tokens.create_index([("collection_id", 1), ("token_id", 1)], unique=True)
    # 索引二：特征筛选用的多键索引（attributes 是数组，MongoDB 会为每个元素建一条索引项）
    db.tokens.create_index([("attributes.trait_type", 1), ("attributes.value", 1)], name="attr_trait_value")
    # 索引三：稀有度排序与分页
    db.tokens.create_index([("collection_id", 1), ("rarity.rank", 1)])


def clean_attributes(nft):
    """从原始元数据里取出特征数组，统一 trait_type 的大小写和首尾空格。"""
    meta = (nft.get("raw") or {}).get("metadata") or {}
    # Pudgy 的元数据字段叫 attributes，Azuki 的叫 traits，结构一样
    raw_attrs = meta.get("attributes") or meta.get("traits") or []
    attrs = []
    for a in raw_attrs:
        if not isinstance(a, dict) or a.get("trait_type") is None or a.get("value") is None:
            continue
        attrs.append({
            "trait_type": str(a["trait_type"]).strip().title(),  # " background " -> "Background"
            "value": str(a["value"]).strip(),
        })
    return attrs


def build_token(cid, nft, trait_types):
    """把 API 返回的一件藏品整理成 tokens 集合里的文档。"""
    token_id = int(nft["tokenId"])
    attrs = clean_attributes(nft)

    # 缺少某个维度就补一条 value 为 "None" 的特征。
    # 稀有度计算需要这一步：「没有帽子」本身也是一种特征，而且每个维度的频率之和才能等于 1。
    have = {a["trait_type"] for a in attrs}
    for t in trait_types:
        if t not in have:
            attrs.append({"trait_type": t, "value": "None"})

    image = nft.get("image") or {}
    meta = (nft.get("raw") or {}).get("metadata") or {}
    local_file = ROOT / "web" / "static" / "img" / cid / f"{token_id}.png"
    doc = {
        "_id": f"{cid}:{token_id}",  # 系列:编号，天然唯一
        "collection_id": cid,
        "token_id": token_id,
        "name": nft.get("name") or f"{COLLECTIONS[cid]['name']} #{token_id}",
        "image": {
            "cached": image.get("cachedUrl"),
            "thumb": image.get("thumbnailUrl"),
            "original": image.get("originalUrl"),
            "source": meta.get("image"),  # 元数据里登记的原始地址，通常是 ipfs://...
            # 缩略图已经下载到本地的话，记下本地路径，断网也能显示
            "local": f"/static/img/{cid}/{token_id}.png" if local_file.exists() else None,
        },
        "attributes": attrs,
        "trait_count": sum(1 for a in attrs if a["value"] != "None"),
        "transfers": [],
        "tags": ["showcase"] if token_id in SHOWCASE.get(cid, []) else [],
        "notes": "",
        "updated_at": datetime.now(timezone.utc),
    }
    return doc


def import_collection(cid):
    raw_dir = ROOT / "data" / "raw" / cid
    pages = sorted(raw_dir.glob("page_*.json"))
    if not pages:
        print(f"[{cid}] 没有找到快照，跳过")
        return

    nfts = []
    for p in pages:
        nfts.extend(json.loads(p.read_text(encoding="utf-8"))["nfts"])

    # 个别藏品 Alchemy 返回的元数据是空的，用 fetch_data.py 从 tokenURI 补采的 metadata_fix.json 补上
    fix_file = raw_dir / "metadata_fix.json"
    if fix_file.exists():
        fixes = json.loads(fix_file.read_text(encoding="utf-8"))
        for nft in nfts:
            if nft["tokenId"] in fixes and not (nft.get("raw") or {}).get("metadata"):
                nft["raw"] = {"metadata": fixes[nft["tokenId"]]}
                nft["name"] = nft.get("name") or fixes[nft["tokenId"]].get("name")

    # 第一遍：统计这个系列一共有哪些特征维度
    trait_types = sorted({a["trait_type"] for nft in nfts for a in clean_attributes(nft)})

    # 第二遍：生成文档
    docs = [build_token(cid, nft, trait_types) for nft in nfts]

    # 合并转移记录快照（scripts/fetch_transfers.py 生成，只有部分藏品有）
    tf_file = raw_dir / "transfers.json"
    if tf_file.exists():
        transfers = json.loads(tf_file.read_text(encoding="utf-8"))
        for d in docs:
            item = transfers.get(str(d["token_id"]))
            if item:
                for t in item["transfers"]:
                    if t.get("time"):
                        t["time"] = datetime.fromisoformat(t["time"])
                d["transfers"] = item["transfers"][-20:]  # 只内嵌最近 20 条
                d["owner"] = item.get("owner")

    # 先删旧数据再批量插入，保证脚本可重复运行
    db.tokens.delete_many({"collection_id": cid})
    db.tokens.insert_many(docs)

    # 系列描述取自 API 返回内容
    contract_meta = (nfts[0].get("contract") or {}).get("openSeaMetadata") or {}
    db.collections.replace_one({"_id": cid}, {
        "_id": cid,
        "name": COLLECTIONS[cid]["name"],
        "chain": "ethereum",
        "standard": "ERC-721",
        "contract": COLLECTIONS[cid]["contract"],
        "token_count": len(docs),        # 以实际导入数量为准
        "trait_types": trait_types,
        "description": contract_meta.get("description") or nfts[0].get("description") or "",
        "imported_at": datetime.now(timezone.utc),
    }, upsert=True)

    print(f"[{cid}] 导入 {len(docs)} 件，特征维度 {len(trait_types)} 个：{trait_types}")


def main():
    setup_collection()
    for cid in COLLECTIONS:
        import_collection(cid)
    print("tokens 总数：", db.tokens.count_documents({}))
    print("索引：", [i["name"] for i in db.tokens.list_indexes()])


if __name__ == "__main__":
    main()
