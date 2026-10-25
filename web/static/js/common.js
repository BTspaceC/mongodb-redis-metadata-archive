// 所有页面共用的小工具：导航栏、当前系列、请求封装、图片地址

// 当前选中的系列：优先用地址栏的 ?c=，其次用上次选的，默认 pudgypenguins
const params = new URLSearchParams(location.search);
const CID = params.get("c") || localStorage.getItem("cid") || "pudgypenguins";
localStorage.setItem("cid", CID);

// 请求接口，返回 { data, cache, ms, status }。cache 和 ms 来自后端的响应头
async function api(path, options) {
  const resp = await fetch(path, options);
  let data = null;
  try { data = await resp.json(); } catch (e) { /* 没有响应体 */ }
  return {
    data,
    status: resp.status,
    cache: resp.headers.get("X-Cache"),
    ms: resp.headers.get("X-Query-Ms"),
    source: resp.headers.get("X-Source"),   // 排行榜接口用：redis / mongodb / unavailable
  };
}

// 图片地址：本地有缩略图就用本地的（断网可用），否则用 CDN 上的缩略图
function imgUrl(image) {
  if (!image) return PLACEHOLDER;
  return image.local || image.thumb || image.cached || PLACEHOLDER;
}

// 图片加载失败（比如断网）时显示的占位图
const PLACEHOLDER = "data:image/svg+xml," + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#dbe7f5"/>' +
  '<text x="50" y="56" font-size="12" text-anchor="middle" fill="#6b7c93">暂无图片</text></svg>');

function imgTag(image, cls) {
  // 加载失败时：先换成 CDN 原图再试一次，还不行才显示占位图
  const backup = (image && image.cached) || "";
  return `<img class="${cls || ""}" loading="lazy" src="${imgUrl(image)}" data-backup="${backup}" onerror="imgFallback(this)">`;
}

function imgFallback(img) {
  const backup = img.dataset.backup;
  img.dataset.backup = "";
  if (backup && img.src !== backup) {
    img.src = backup;
  } else {
    img.onerror = null;
    img.src = PLACEHOLDER;
  }
}

// 防止把数据里的特殊字符当成 HTML
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, ch => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

// X-Cache 三种状态对应的说明文字
const CACHE_TEXT = {
  HIT: "来自 Redis 缓存",
  MISS: "查询了 MongoDB",
  BYPASS: "Redis 不可用，已降级为直接查 MongoDB",
};

function shortAddr(a) {
  return a ? a.slice(0, 6) + "…" + a.slice(-4) : "暂无";
}

// 画导航栏，并填充右上角的系列下拉框
async function renderNav(active) {
  const pages = [
    ["index.html", "首页"], ["browse.html", "浏览"], ["rank.html", "排行"],
    ["stats.html", "统计"], ["console.html", "管理控制台"],
  ];
  const nav = document.createElement("div");
  nav.className = "nav";
  nav.innerHTML = `<a class="logo" href="index.html">🐧 数字藏品档案</a>` +
    pages.map(([href, name]) => `<a class="link ${href === active ? "active" : ""}" href="${href}">${name}</a>`).join("") +
    `<a class="link" href="/docs" target="_blank">接口文档</a><select id="cidSelect" title="切换系列"></select>`;
  document.body.prepend(nav);

  const { data } = await api("/api/collections");
  const select = document.getElementById("cidSelect");
  select.innerHTML = (data || []).map(c =>
    `<option value="${c._id}" ${c._id === CID ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  select.onchange = () => {
    localStorage.setItem("cid", select.value);
    // 详情页切换系列没有意义，回到浏览页
    location.href = active === "token.html" ? "browse.html" : location.pathname;
  };
}
