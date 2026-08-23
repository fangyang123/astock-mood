/**
 * jsdom 验证：方案B 自动同步流程
 * 场景：手机离线记一条（存 localStorage, synced=false）
 *       → 回家连 Wi-Fi，Mac 可达 → 触发 sync() → POST 到 /api/moods → 标记 synced
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) { pass++; console.log("  \u2713 " + name); }
  else { fail++; console.log("  \u2717 " + name + (extra ? " \u2192 " + extra : "")); }
}
process.on("unhandledRejection", (r) => {
  if (r && r.message && r.message.includes("getElementById")) return;
  console.error("Unhandled rejection:", r);
});

const mHtml = fs.readFileSync(path.join(__dirname, "static", "m.html"), "utf-8");

let fetchCalls = [];
let macReachable = false;          // 模拟：初始不可达（手机在外）
function fetchMock(url, init) {
  const u = String(url);
  fetchCalls.push({ url: u, init });
  if (!macReachable) return Promise.reject(new Error("net::ERR_OFFLINE"));
  if (/\/api\/health$/.test(u)) return Promise.resolve({ ok: true, status: 200 });
  if (/\/api\/moods$/.test(u) && init && init.method === "POST") {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ id: 1 }) });
  }
  return Promise.reject(new Error("unexpected " + u));
}

const dom = new JSDOM(mHtml, {
  runScripts: "dangerously",
  url: "https://b53cda82385d490a99762dbcc8136540.app.workbuddy.link/",
  beforeParse(window) {
    window.fetch = fetchMock;
    window.AbortController = window.AbortController || class { constructor(){ this.signal=null; } abort(){} };
    // 干净 localStorage
    try { window.localStorage.clear(); } catch(e){}
  }
});
const { window } = dom;
const doc = window.document;
const wait = (ms) => new Promise(r => setTimeout(r, ms));

(async function run() {
  await wait(400);  // 等 DOMContentLoaded + 初始化

  console.log("\n[1] 页面加载 & 初始离线探测");
  ok("netStatus 显示离线（Mac 不可达）",
     /离线/.test(doc.getElementById("netStatus").textContent),
     doc.getElementById("netStatus").textContent);

  console.log("\n[2] 离线记一条情绪（存 localStorage, synced=false）");
  // 填表
  doc.getElementById("ts").value = "2026-08-22T15:30";
  // 选情绪“恐踏空”
  const chips = doc.getElementById("emotions").children;
  let clicked = false;
  for (const c of chips) { if (c.textContent === "恐踏空") { c.click(); clicked = true; break; } }
  ok("选中恐踏空芯片", clicked);
  doc.getElementById("intensity").value = "4";
  doc.getElementById("position_pct").value = "60";
  doc.getElementById("pnl_pct").value = "-2.5";
  doc.getElementById("trigger").value = "大盘拉升";
  doc.getElementById("urge").value = "想加仓";
  doc.getElementById("plan").value = "持有";
  doc.getElementById("actedTrue").click();   // 按情绪操作
  doc.getElementById("note").value = "测试自动同步";
  doc.getElementById("saveBtn").click();
  await wait(200);

  let buf = JSON.parse(window.localStorage.getItem("mood_buffer_v1") || "[]");
  ok("localStorage 写入 1 条", buf.length === 1, "len=" + buf.length);
  ok("该条 synced=false（待同步）", buf.length === 1 && buf[0].synced === false);
  ok("待同步计数显示 1", doc.getElementById("pendingCount").textContent === "1");
  ok("离线期间 moods POST 未成功（条目仍待同步）",
     buf.length === 1 && buf[0].synced === false,
     "synced=" + (buf[0] && buf[0].synced));

  console.log("\n[3] 回家连 Wi-Fi → Mac 可达 → 触发同步");
  fetchCalls = [];
  macReachable = true;             // 模拟连上家里 Wi-Fi
  doc.getElementById("syncBtn").click();
  await wait(800);

  const postCalls = fetchCalls.filter(c => /\/api\/moods$/.test(c.url) && c.init && c.init.method === "POST");
  ok("向 /api/moods 发起 1 次 POST", postCalls.length === 1, "POST 次数=" + postCalls.length);
  if (postCalls.length) {
    const body = JSON.parse(postCalls[0].init.body);
    ok("POST payload 含 emotion=恐踏空", body.emotion === "恐踏空", JSON.stringify(body).slice(0,60));
    ok("POST payload 含 intensity=4", body.intensity === 4);
    ok("POST payload 含 acted=true", body.acted === true);
  }

  buf = JSON.parse(window.localStorage.getItem("mood_buffer_v1") || "[]");
  ok("同步后该条 synced=true", buf.length === 1 && buf[0].synced === true);
  ok("待同步计数归 0", doc.getElementById("pendingCount").textContent === "0");
  ok("netStatus 显示已同步", /已同步/.test(doc.getElementById("netStatus").textContent),
     doc.getElementById("netStatus").textContent);

  console.log("\n[4] 再次打开页面（已 synced）不重复 POST");
  fetchCalls = [];
  doc.getElementById("syncBtn").click();
  await wait(600);
  const post2 = fetchCalls.filter(c => /\/api\/moods$/.test(c.url) && c.init && c.init.method === "POST");
  ok("已全同步时无新 POST", post2.length === 0, "POST 次数=" + post2.length);

  console.log("\n========== 结果: " + pass + " 通过, " + fail + " 失败 ==========");
  process.exit(fail ? 1 : 0);
})();
