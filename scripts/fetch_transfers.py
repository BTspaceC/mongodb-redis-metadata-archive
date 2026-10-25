"""
采集转移记录（链上溯源数据）：只为稀有度前 50 件和带 showcase 标签的头部重点藏品拉取，每件最多保留最近 20 条。
结果存到 data/raw/pudgypenguins/transfers.json，由 import_data.py 合并进 tokens.transfers。

数据源：Blockscout 以太坊主网的公开接口（不需要 API key）
    GET https://eth.blockscout.com/api/v2/tokens/{合约}/instances/{编号}/transfers
返回结果按时间从新到旧排列，第一条的接收方就是当前持有人。

要先跑完 import_data.py 和 compute_rarity.py（需要排名）。

用法：
    python scripts/fetch_transfers.py
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import db  # noqa: E402

CID = "pudgypenguins"
CONTRACT = "0xBd3531dA5CF5857e7CfAA92426877b022e612cf8"
KEEP = 20  # 每件藏品只保留最近 20 条（有界数组，防止文档无限增长）


def fetch(token_id):
    url = f"https://eth.blockscout.com/api/v2/tokens/{CONTRACT}/instances/{token_id}/transfers"
    for attempt in range(5):
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code == 200:
                return resp.json()["items"]
        except requests.RequestException:
            pass
        time.sleep(2 + attempt * 2)
    return None


def main():
    out_file = ROOT / "data" / "raw" / CID / "transfers.json"
    result = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}

    top = db.tokens.find({"collection_id": CID}, {"token_id": 1}).sort("rarity.rank", 1).limit(50)
    showcase = db.tokens.find({"collection_id": CID, "tags": "showcase"}, {"token_id": 1})
    token_ids = sorted({t["token_id"] for t in top} | {t["token_id"] for t in showcase})

    for tid in token_ids:
        if str(tid) in result:  # 已经采集过的跳过，可以断点续传
            continue
        items = fetch(tid)
        if items is None:
            print(f"  #{tid} 采集失败，跳过")
            continue
        newest = items[:KEEP]  # 接口返回的是从新到旧
        transfers = [{
            "from": i["from"]["hash"],
            "to": i["to"]["hash"],
            "tx_hash": i.get("transaction_hash"),
            "block": i.get("block_number"),
            "time": (i.get("timestamp") or "").replace("Z", "+00:00") or None,
        } for i in reversed(newest)]  # 存成从旧到新，以后 $push 新记录是追加在末尾
        result[str(tid)] = {
            "owner": newest[0]["to"]["hash"] if newest else None,  # 最近一次转移的接收方 = 当前持有人
            "transfers": transfers,
        }
        print(f"  #{tid}: {len(transfers)} 条")
        out_file.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(0.3)

    print(f"完成：{len(result)} 件藏品的转移记录保存在 {out_file}")


if __name__ == "__main__":
    main()
