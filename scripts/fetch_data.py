"""
采集脚本：调用 Alchemy NFT API v3 的 getNFTsForContract，把原始响应按页存到 data/raw/<系列>/page_001.json。

用法：
    python scripts/fetch_data.py pudgypenguins          # 全量（约 89 页）
    python scripts/fetch_data.py azuki --max-items 300  # 对照系列只取 300 件

说明：
- 只有这个脚本需要联网和 API key；导入脚本只读本地快照。
- 快照里只保存响应内容，不保存请求 URL，所以不会把 key 写进仓库。
- 本项目不做价格相关功能，保存前把响应里的 floorPrice 字段去掉。
- Alchemy 偶尔会有个别藏品的元数据是空的。翻页结束后，脚本会按规划里的备选方案，
  用这些藏品的 tokenURI（ipfs://...）经 IPFS 网关直接取元数据 JSON，存到 metadata_fix.json，
  导入时用它补齐。原始分页快照保持原样不改。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# 系列 id -> 合约地址（已在 Etherscan 上核对）
CONTRACTS = {
    "pudgypenguins": "0xBd3531dA5CF5857e7CfAA92426877b022e612cf8",
    "azuki": "0xED5AF388653567Af2F388E6224dC7C4b3241C544",
}


def fetch_page(api_key, contract, start_token):
    """拉取一页（最多 100 件）。遇到限流（429）或网络错误就等一会儿重试。"""
    url = f"https://eth-mainnet.g.alchemy.com/nft/v3/{api_key}/getNFTsForContract"
    params = {"contractAddress": contract, "withMetadata": "true", "limit": 100}
    if start_token:
        params["startToken"] = start_token  # 上一页返回的 pageKey
    for attempt in range(8):
        try:
            resp = requests.get(url, params=params, timeout=60)
            if resp.status_code == 200:
                return resp.json()
            print(f"  HTTP {resp.status_code}，第 {attempt + 1} 次重试")
        except requests.RequestException as e:
            print(f"  网络错误 {e.__class__.__name__}，第 {attempt + 1} 次重试")
        time.sleep(2 + attempt * 2)
    sys.exit("多次重试仍失败，稍后重新运行本脚本即可断点续传")


def strip_price(page):
    """去掉价格字段（本项目定位是档案，不做行情）。"""
    for nft in page.get("nfts", []):
        meta = (nft.get("contract") or {}).get("openSeaMetadata") or {}
        meta.pop("floorPrice", None)


def fill_missing(out_dir):
    """备选方案：对元数据为空的藏品，按 tokenURI 从 IPFS 网关取元数据，存到 metadata_fix.json。"""
    fix_file = out_dir / "metadata_fix.json"
    fixes = json.loads(fix_file.read_text(encoding="utf-8")) if fix_file.exists() else {}
    missing = []
    for f in sorted(out_dir.glob("page_*.json")):
        for nft in json.loads(f.read_text(encoding="utf-8"))["nfts"]:
            meta = (nft.get("raw") or {}).get("metadata") or {}
            if not (meta.get("attributes") or meta.get("traits")) and nft["tokenId"] not in fixes:
                missing.append(nft)
    if not missing:
        print(f"元数据为空的藏品：0 件待补（已补 {len(fixes)} 件）")
        return

    print(f"有 {len(missing)} 件藏品元数据为空，改用 tokenURI 从 IPFS 获取")
    for nft in missing:
        token_uri = nft.get("tokenUri") or ""
        if not token_uri.startswith("ipfs://"):
            continue
        url = "https://gateway.pinata.cloud/ipfs/" + token_uri[len("ipfs://"):]
        for attempt in range(5):
            try:
                resp = requests.get(url, timeout=60)
                if resp.status_code == 200:
                    fixes[nft["tokenId"]] = resp.json()
                    break
            except (requests.RequestException, ValueError):
                pass
            time.sleep(2 + attempt * 2)
        else:
            print(f"  #{nft['tokenId']} 仍然取不到，导入后该藏品特征为空")
        fix_file.write_text(json.dumps(fixes, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(0.3)
    print(f"已补齐 {len(fixes)} 件，保存在 {fix_file}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("collection", choices=CONTRACTS.keys())
    parser.add_argument("--max-items", type=int, default=0, help="最多采集多少件，0 表示全量")
    args = parser.parse_args()

    api_key = os.getenv("ALCHEMY_API_KEY") or "demo"  # demo 是 Alchemy 的公开体验 key，有限流
    out_dir = ROOT / "data" / "raw" / args.collection
    out_dir.mkdir(parents=True, exist_ok=True)

    # 断点续传：已有的页直接读本地，从最后一页的 pageKey 接着拉
    page_no, start_token, total = 0, None, 0
    for f in sorted(out_dir.glob("page_*.json")):
        page = json.loads(f.read_text(encoding="utf-8"))
        page_no += 1
        total += len(page["nfts"])
        start_token = page.get("pageKey")
    if page_no and not start_token:
        print(f"已采集完成：{page_no} 页 {total} 件")
        fill_missing(out_dir)
        return

    while True:
        if args.max_items and total >= args.max_items:
            break
        page = fetch_page(api_key, CONTRACTS[args.collection], start_token)
        strip_price(page)
        page_no += 1
        total += len(page["nfts"])
        path = out_dir / f"page_{page_no:03d}.json"
        path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
        print(f"第 {page_no} 页：{len(page['nfts'])} 件，累计 {total} 件")
        start_token = page.get("pageKey")
        if not start_token:  # 没有 pageKey 说明已经是最后一页
            break
        time.sleep(0.3)

    print(f"完成：{page_no} 页，共 {total} 件，保存在 {out_dir}")
    fill_missing(out_dir)


if __name__ == "__main__":
    main()
