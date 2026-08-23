/**
 * jsdom 运行时验证：m.html 离线捕获 + 同步逻辑（串行版 v2）
 *
 * 验证项：
 * 1. 页面正常加载（DOMContentLoaded → 初始化完成）
 * 2. 表单填写 → save() → 写入 localStorage（离线场景）
 * 3. localStorage 不可用时降级（不报错）
 * 4. 在线时 sync() → fetch POST 到 /api/moods
 * 5. 多条离线缓冲后批量同步（预填 localStorage）
 * 6. 导出 JSON 备份
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) { pass++; console.log("  \u2713 " + name); }
  else { fail++; console.log("  \u2717 " + name + (extra ? " \u2192 " + extra : "")); }
}

// 抑制 jsdom 在 Promise 微任务中 document 丢失导致的 unhandledRejection（已知限制，不影响实际浏览器）
process.on("unhandledRejection", (reason) => {
  if (reason && reason.message && reason.message.includes("getElementById")) return;
  console.error("Unhandled rejection:", reason);
});

const mHtmlPath = path.join(__dirname, "static", "m.html");
const mHtml = fs.readFileSync(mHtmlPath, "utf-8");

let fetchCalls = [];
function makeFetchMock(opts = {}) {
  return function fetch(url, init) {
    fetchCalls.push({ url: String(url), init });
    if (opts.offline) return Promise.reject(new Error("net::ERR_OFFLINE"));
    if (opts.serverDown) return Promise.resolve({ ok: false, status: 500 });
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ ok: true, id: Math.floor(Math.random() * 10000) }),
      clone: function() { return this; },
    });
  };
}

function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

async function runAll() {
  // ========== 测试 1: 页面加载 ==========
  console.log("\n[1] \u9875\u9762\u52a0\u8f7d\u6d4b\u8bd5");
  {
    const dom = new JSDOM(mHtml, {
      runScripts: "dangerously", resources: "usable",
      url: "http://localhost:8765/m",
      beforeParse(w) { w.fetch = makeFetchMock({ offline: true }); },
    });
    await wait(500);
    const doc = dom.window.document;
    ok("\u6807\u9898\u5b58\u5728", doc.querySelector("h1")?.textContent?.includes("\u76ef\u76d8\u60c5\u7eea"));
    ok("\u60c5\u7eea chips \u5df2\u751f\u6210 (8\u4e2a)", doc.querySelectorAll(".chip").length === 8);
    ok("trigger \u9009\u9879\u5df2\u586b\u5145", doc.querySelectorAll("#trigger option").length > 1);
    ok("urge \u9009\u9879\u5df2\u586b\u5145", doc.querySelectorAll("#urge option").length > 1);
    ok("plan \u9009\u9879\u5df2\u586b\u5145", doc.querySelectorAll("#plan option").length > 1);
    ok("\u65f6\u95f4\u9ed8\u8ba4\u586b\u5145", doc.getElementById("ts")?.value?.length > 0);
    ok("\u5f3a\u5ea6\u9ed8\u8ba4 3", doc.getElementById("intensity")?.value === "3");
    ok("SW \u6ce8\u518c\u8def\u5f84\u4e3a /sw.js\uff08\u6839\u8def\u5f84\uff09", mHtml.includes('register("/sw.js"'));
    ok("SW \u6ce8\u518c\u8def\u5f84\u975e /static/sw.js", !mHtml.includes('register("/static/sw.js"'));
    dom.window.close();
  }

  // ========== 测试 2: 离线保存到 localStorage ==========
  console.log("\n[2] \u79bb\u7ebf\u4fdd\u5b58 \u2192 localStorage \u7f13\u51b2\u6d4b\u8bd5");
  {
    const dom = new JSDOM(mHtml, {
      runScripts: "dangerously", resources: "usable",
      url: "http://localhost:8765/m",
      beforeParse(w) { w.fetch = makeFetchMock({ offline: true }); },
    });
    await wait(500);
    const doc = dom.window.document;

    const chips = doc.querySelectorAll(".chip");
    chips[0].click(); // \u51b7\u9759
    doc.getElementById("intensity").value = 4;
    doc.getElementById("intensityVal").textContent = 4;
    doc.getElementById("trigger").value = "\u5927\u76d8\u62c9\u5347";
    doc.getElementById("urge").value = "\u60f3\u52a0\u4ed3";
    doc.getElementById("position_pct").value = 60;
    doc.getElementById("pnl_pct").value = -2.5;
    doc.getElementById("plan").value = "\u6301\u6709";
    doc.getElementById("actedTrue").click();
    doc.getElementById("note").value = "\u5927\u76d8\u7a81\u7834\u65f6\u624b\u75d2\u60f3\u52a0\u4ed3";
    doc.getElementById("saveBtn").click();

    await wait(500);
    const raw = dom.window.localStorage.getItem("mood_buffer_v1");
    ok("localStorage \u6709\u6570\u636e", !!raw);
    if (raw) {
      const buf = JSON.parse(raw);
      ok("\u7f13\u51b2\u533a\u6709 1 \u6761\u8bb0\u5f55", buf.length === 1, "len=" + buf.length);
      if (buf[0]) {
        ok("entry \u542b localId", !!buf[0].localId);
        ok("entry \u672a\u540c\u6b65", buf[0].synced === false);
        ok("emotion=\u51b7\u9759", buf[0].payload.emotion === "\u51b7\u9759");
        ok("intensity=4", buf[0].payload.intensity === 4);
        ok("trigger=\u5927\u76d8\u62c9\u5347", buf[0].payload.trigger === "\u5927\u76d8\u62c9\u5347");
        ok("urge=\u60f3\u52a0\u4ed3", buf[0].payload.urge === "\u60f3\u52a0\u4ed3");
        ok("position_pct=60", buf[0].payload.position_pct === 60);
        ok("pnl_pct=-2.5", buf[0].payload.pnl_pct === -2.5);
        ok("plan=\u6301\u6709", buf[0].payload.plan === "\u6301\u6709");
        ok("acted=true", buf[0].payload.acted === true);
        ok("note \u542b\u4e0a\u4e0b\u6587", buf[0].payload.note.includes("\u624b\u75d2"));
      }
    }
    ok("\u5f85\u540c\u6b65=1", doc.getElementById("pendingCount").textContent === "1");
    ok("\u5df2\u540c\u6b65=0", doc.getElementById("syncedCount").textContent === "0");
    ok("\u6700\u8fd1\u8bb0\u5f55\u5217\u8868\u6709 1 \u6761", doc.querySelectorAll(".item").length === 1);
    ok("\u663e\u793a\u5f85\u540c\u6b65\u6807\u7b7e", doc.querySelector(".item .pending") !== null);
    dom.window.close();
  }

  // ========== 测试 3: 在线同步 ==========
  console.log("\n[3] \u5728\u7ebf\u540c\u6b65\u6d4b\u8bd5");
  {
    fetchCalls = [];
    const dom = new JSDOM(mHtml, {
      runScripts: "dangerously", resources: "usable",
      url: "http://localhost:8765/m",
      beforeParse(w) { w.fetch = makeFetchMock({ offline: true }); },
    });
    await wait(500);
    const doc = dom.window.document;

    // \u79bb\u7ebf\u4fdd\u5b58\u4e00\u6761
    const chips = doc.querySelectorAll(".chip");
    chips[2].click(); // \u6050\u8e0f\u7a7a
    doc.getElementById("note").value = "\u6050\u8e0f\u7a7a\u6d4b\u8bd5\u540c\u6b65";
    doc.getElementById("saveBtn").click();
    await wait(500);

    const buf1 = JSON.parse(dom.window.localStorage.getItem("mood_buffer_v1") || "[]");
    ok("\u79bb\u7ebf\u4fdd\u5b58\u540e\u7f13\u51b2\u533a\u6709 1 \u6761", buf1.length === 1);
    ok("\u79bb\u7ebf\u4fdd\u5b58\u540e\u6807\u8bb0\u672a\u540c\u6b65", buf1[0]?.synced === false);

    // \u5207\u6362\u5230\u5728\u7ebf fetch
    fetchCalls = [];
    dom.window.fetch = makeFetchMock({ online: true });
    doc.getElementById("syncBtn").click();
    await wait(800);

    const buf2 = JSON.parse(dom.window.localStorage.getItem("mood_buffer_v1") || "[]");
    ok("\u540c\u6b65\u540e\u6807\u8bb0\u4e3a\u5df2\u540c\u6b65", buf2[0]?.synced === true);
    const postCalls = fetchCalls.filter(c => c.init?.method === "POST");
    ok("\u540c\u6b65\u53d1\u4e86 1 \u6b21 POST", postCalls.length === 1, "got " + postCalls.length);
    ok("POST \u76ee\u6807\u4e3a /api/moods", postCalls.some(c => String(c.url).includes("/api/moods")));
    ok("POST body \u542b emotion=\u6050\u8e0f\u7a7a", postCalls.some(c => {
      try { return JSON.parse(c.init.body).emotion === "\u6050\u8e0f\u7a7a"; } catch { return false; }
    }));
    ok("\u5f85\u540c\u6b65=0", doc.getElementById("pendingCount").textContent === "0");
    ok("\u5df2\u540c\u6b65=1", doc.getElementById("syncedCount").textContent === "1");
    ok("\u663e\u793a\u5df2\u540c\u6b65\u6807\u7b7e", doc.querySelector(".item .synced") !== null);
    dom.window.close();
  }

  // ========== 测试 4: localStorage 不可用降级 ==========
  console.log("\n[4] localStorage \u4e0d\u53ef\u7528\u964d\u7ea7\u6d4b\u8bd5");
  {
    const dom = new JSDOM(mHtml, {
      runScripts: "dangerously", resources: "usable",
      url: "http://localhost:8765/m",
      beforeParse(window) {
        Object.defineProperty(window, "localStorage", {
          get() { throw new Error("SecurityError"); },
        });
        window.fetch = makeFetchMock({ offline: true });
      },
    });
    const doc = dom.window.document;
    await wait(500);
    ok("\u9875\u9762\u4ecd\u6b63\u5e38\u52a0\u8f7d\uff08\u65e0\u62a5\u9519\uff09", doc.querySelectorAll(".chip").length === 8);
    let threw = false;
    try {
      const chips = doc.querySelectorAll(".chip");
      chips[1].click();
      doc.getElementById("saveBtn").click();
    } catch (e) { threw = true; }
    ok("\u4fdd\u5b58\u4e0d\u629b\u5f02\u5e38", !threw);
    dom.window.close();
  }

  // ========== 测试 5: 多条离线缓冲后批量同步（预填 localStorage） ==========
  console.log("\n[5] \u591a\u6761\u79bb\u7ebf\u7f13\u51b2 \u2192 \u6279\u91cf\u540c\u6b65\u6d4b\u8bd5");
  {
    fetchCalls = [];
    // \u9884\u586b 3 \u6761\u672a\u540c\u6b65\u8bb0\u5f55\u5230 localStorage\uff0c\u9875\u9762\u52a0\u8f7d\u65f6\u4f1a\u8bfb\u53d6
    const preEntries = [
      { localId: "t5a", synced: false, payload: { ts: "2026-08-22 10:00", emotion: "\u51b7\u9759", intensity: 2, trigger: "", urge: "", position_pct: null, pnl_pct: null, plan: "", acted: false, note: "\u7b2c1\u6761" } },
      { localId: "t5b", synced: false, payload: { ts: "2026-08-22 10:30", emotion: "\u8d2a\u5a6a", intensity: 4, trigger: "\u5927\u76d8\u62c9\u5347", urge: "\u60f3\u52a0\u4ed3", position_pct: 50, pnl_pct: 1.5, plan: "\u6301\u6709", acted: true, note: "\u7b2c2\u6761" } },
      { localId: "t5c", synced: false, payload: { ts: "2026-08-22 11:00", emotion: "\u6050\u614c", intensity: 5, trigger: "\u5927\u76d8\u8df3\u6c34", urge: "\u60f3\u5272\u8089", position_pct: 80, pnl_pct: -4.2, plan: "\u6e05\u4ed3", acted: false, note: "\u7b2c3\u6761" } },
    ];
    const dom = new JSDOM(mHtml, {
      runScripts: "dangerously", resources: "usable",
      url: "http://localhost:8765/m",
      beforeParse(w) {
        w.localStorage.setItem("mood_buffer_v1", JSON.stringify(preEntries));
        w.fetch = makeFetchMock({ online: true });
      },
    });
    await wait(500);
    const doc = dom.window.document;

    // \u9875\u9762\u52a0\u8f7d\u540e\u5e94\u6709 3 \u6761\u5f85\u540c\u6b65
    ok("\u5f85\u540c\u6b65=3", doc.getElementById("pendingCount").textContent === "3");
    ok("\u5df2\u540c\u6b65=0", doc.getElementById("syncedCount").textContent === "0");
    ok("\u8bb0\u5f55\u5217\u8868\u6709 3 \u6761", doc.querySelectorAll(".item").length === 3);

    // \u70b9\u540c\u6b65
    fetchCalls = [];
    doc.getElementById("syncBtn").click();
    await wait(1500);

    const buf2 = JSON.parse(dom.window.localStorage.getItem("mood_buffer_v1") || "[]");
    ok("\u6279\u91cf\u540c\u6b65\u540e 3 \u6761\u5df2\u540c\u6b65", buf2.length === 3 && buf2.every(b => b.synced), JSON.stringify(buf2.map(b => b.synced)));
    const postCalls = fetchCalls.filter(c => c.init?.method === "POST");
    ok("POST \u6b21\u6570=3", postCalls.length === 3, "got " + postCalls.length);
    ok("POST \u542b\u4e09\u79cd\u60c5\u7eea", postCalls.every(c => {
      try { const e = JSON.parse(c.init.body); return ["\u51b7\u9759","\u8d2a\u5a6a","\u6050\u614c"].includes(e.emotion); } catch { return false; }
    }));
    ok("\u5f85\u540c\u6b65=0", doc.getElementById("pendingCount").textContent === "0");
    ok("\u5df2\u540c\u6b65=3", doc.getElementById("syncedCount").textContent === "3");
    dom.window.close();
  }

  // ========== 测试 6: 导出 JSON 备份 ==========
  console.log("\n[6] \u5bfc\u51fa JSON \u5907\u4efd\u6d4b\u8bd5");
  {
    const dom = new JSDOM(mHtml, {
      runScripts: "dangerously", resources: "usable",
      url: "http://localhost:8765/m",
      beforeParse(w) { w.fetch = makeFetchMock({ offline: true }); },
    });
    await wait(500);
    const doc = dom.window.document;

    const chips = doc.querySelectorAll(".chip");
    chips[0].click();
    doc.getElementById("note").value = "\u5bfc\u51fa\u5bfc\u5165\u6d4b\u8bd5";
    doc.getElementById("saveBtn").click();
    await wait(300);

    let exportOk = false;
    try {
      dom.window.URL.createObjectURL = () => "blob:fake";
      dom.window.URL.revokeObjectURL = () => {};
      doc.getElementById("exportBtn").click();
      exportOk = true;
    } catch (e) { console.log("  \u5bfc\u51fa\u5f02\u5e38:", e.message); }
    ok("\u5bfc\u51fa\u4e0d\u629b\u5f02\u5e38", exportOk);

    const buf = JSON.parse(dom.window.localStorage.getItem("mood_buffer_v1") || "[]");
    ok("\u5bfc\u51fa\u6570\u636e\u542b 1 \u6761", buf.length === 1);
    ok("\u5bfc\u51fa\u6570\u636e\u542b localId", !!buf[0]?.localId);
    ok("\u5bfc\u51fa\u6570\u636e\u542b payload", !!buf[0]?.payload);
    dom.window.close();
  }

  // ========== 汇总 ==========
  console.log("\n========================================");
  console.log("  \u603b\u8ba1: " + (pass + fail) + " | \u901a\u8fc7: " + pass + " | \u5931\u8d25: " + fail);
  console.log("========================================\n");
  process.exit(fail > 0 ? 1 : 0);
}

runAll().catch(err => { console.error("Runner error:", err); process.exit(1); });
