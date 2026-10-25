"""
下载缩略图到 web/static/img/<系列>/<编号>.png，并把本地路径写进 tokens.image.local。
这样断网时图片也能显示。

用法：
    python scripts/download_images.py          # 只下载高稀缺度及焦点采样藏品（约 190 张）
    python scripts/download_images.py --all    # 全部下载（约 9,200 张，一百多 MB，要几分钟）

要先跑完 import_data.py 和 compute_rarity.py。需要联网，不需要 API key。
已经下载过的会跳过，所以中途断了可以重新运行接着下。
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import db  # noqa: E402

TOP_N = {"pudgypenguins": 100, "azuki": 24}   # 不加 --all 时每个系列下载稀有度前多少件
WORKERS = 8                                   # 同时下载的线程数


def is_image(path):
    """看文件开头的几个字节判断是不是图片（PNG / JPEG / WebP / GIF）。
    有的 CDN 地址会返回一段报错文字，存下来扩展名是 .png 但其实不是图片。"""
    if not path.exists():
        return False
    with open(path, "rb") as f:
        head = f.read(12)
    return head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8"))


def download(url, path):
    for attempt in range(4):
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code == 200:
                path.write_bytes(resp.content)
                if is_image(path):   # 必须确实是图片
                    return True
                path.unlink()        # 不是图片就删掉，换下一个地址
                return False
            if resp.status_code in (400, 404, 415):
                return False         # 这个地址本身有问题，重试也没用
        except requests.RequestException:
            pass
        time.sleep(1 + attempt * 2)  # 可能是被限流了，等一会儿再试
    return False


def fetch_one(cid, t, out_dir, sibling):
    """下载一件藏品的图片，成功返回 True。"""
    path = out_dir / f"{t['token_id']}.png"
    image = t.get("image") or {}
    # 依次尝试：缩略图 -> CDN 原图 -> 元数据登记的 IPFS 原始地址，哪个能下载用哪个
    urls = [u for u in (image.get("thumb"), image.get("cached")) if u]
    source = image.get("source") or ""
    if not source.startswith("ipfs://") and sibling:
        # 个别藏品的元数据没登记 IPFS 地址：同一系列的图片都在同一个 IPFS 目录下，
        # 只是文件名里的编号不同，所以借用别的藏品的地址换一下编号
        sid, ssrc = sibling
        source = ssrc.replace(f"/{sid}.png", f"/{t['token_id']}.png")
    if source.startswith("ipfs://"):
        urls.append("https://gateway.pinata.cloud/ipfs/" + source[len("ipfs://"):])

    ok = is_image(path) or any(download(u, path) for u in urls)
    # 把结果写回文档：成功记下本地路径，失败清空（页面会改用远程地址）
    local = f"/static/img/{cid}/{t['token_id']}.png" if ok else None
    if image.get("local") != local:
        db.tokens.update_one({"_id": t["_id"]}, {"$set": {"image.local": local}})
    return ok


def main():
    download_all = "--all" in sys.argv
    for cid, n in TOP_N.items():
        out_dir = ROOT / "web" / "static" / "img" / cid
        out_dir.mkdir(parents=True, exist_ok=True)
        fields = {"token_id": 1, "image": 1}

        if download_all:
            tokens = list(db.tokens.find({"collection_id": cid}, fields))
        else:
            # 稀有度前 n 件 + 焦点采样藏品 (showcase) + 历史下载记录（合并去重）
            tokens = list(db.tokens.find({"collection_id": cid}, fields).sort("rarity.rank", 1).limit(n))
            tokens += list(db.tokens.find({"collection_id": cid, "tags": "showcase"}, fields))
            tokens += list(db.tokens.find({"collection_id": cid, "image.local": {"$ne": None}}, fields))
            tokens = list({t["_id"]: t for t in tokens}.values())  # 去重

        # 找一件登记了 IPFS 图片地址的藏品，给「借用地址」做参照
        ref = db.tokens.find_one({"collection_id": cid, "image.source": {"$regex": r"^ipfs://.*\.png$"}},
                                 {"token_id": 1, "image.source": 1})
        sibling = (ref["token_id"], ref["image"]["source"]) if ref else None

        # 多线程下载：图片下载主要是在等网络，多开几个线程能快很多
        ok = done = 0
        failed = []
        with ThreadPoolExecutor(WORKERS) as pool:
            for t, success in zip(tokens, pool.map(lambda t: fetch_one(cid, t, out_dir, sibling), tokens)):
                done += 1
                if success:
                    ok += 1
                else:
                    failed.append(t["token_id"])
                if done % 500 == 0:
                    print(f"  [{cid}] 已处理 {done}/{len(tokens)}", flush=True)
        print(f"[{cid}] 本地图片 {ok}/{len(tokens)} 张" + (f"，失败的编号：{failed[:30]}" if failed else ""), flush=True)


if __name__ == "__main__":
    main()
