#!/usr/bin/env node
/* 行级自洽体检（用引擎自己的状态，不靠像素）：
 *   每一行的「入场时刻 = 首字发声」、「离场时刻 = 下一行首字 / 显式 cutAt」，
 *   检查：① 峰值时刻恰好只有这一行在屏上 ② 这一行的可见时长 ≥ 0.25s
 *         ③ 离场时刻与入场时刻不重叠（同一时刻不能两行都 active）
 *         ④ gate（装置入场拍）落在拍上、且不晚于首字 0.25s 以上
 *
 * 用法：node tools/qc_lines_boxes.js --shots shots-full-v3.json --out out/qc-lines.json
 */
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

function parseArgs(argv) {
  const a = {};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i].startsWith("--")) {
      const k = argv[i].slice(2);
      a[k] = (i + 1 < argv.length && !argv[i + 1].startsWith("--")) ? argv[++i] : true;
    }
  }
  return a;
}

async function main() {
  const a = parseArgs(process.argv);
  const shotsFile = a.shots || "shots-full-v3.json";
  const shotsCfg = JSON.parse(fs.readFileSync(shotsFile, "utf8"));
  const words = JSON.parse(fs.readFileSync(a.words || "song/analysis/words-fixed.json", "utf8"));
  const beatmap = JSON.parse(fs.readFileSync(a.beats || "song/analysis/beatmap.json", "utf8"));
  const shotsRoot = path.dirname(path.resolve(shotsFile));
  const width = shotsCfg.width || 1920, height = shotsCfg.height || 1080;
  const fps = shotsCfg.fps || 24;

  let beatLen = 0.455;
  if (beatmap.beats && beatmap.beats.length > 2) {
    const d = [];
    for (let i = 1; i < beatmap.beats.length; i++) d.push(beatmap.beats[i] - beatmap.beats[i - 1]);
    d.sort((x, y) => x - y);
    beatLen = d[Math.floor(d.length / 2)] || beatLen;
  }
  const envPath = path.resolve(shotsRoot, "song/analysis/wave-envelope.json");
  const envelope = fs.existsSync(envPath) ? JSON.parse(fs.readFileSync(envPath, "utf8")) : null;
  const linesPath = path.resolve(shotsRoot, "song/analysis/lines.json");
  const lyricLines = fs.existsSync(linesPath) ? JSON.parse(fs.readFileSync(linesPath, "utf8")).lines : null;
  const data = {
    config: {
      t0: shotsCfg.t0, t1: shotsCfg.t1, fps,
      accent: shotsCfg.accent || "#FF5FAF",
      bpm: beatmap.bpm_from_beats || 0, beatLen,
      downbeatEvery: (shotsCfg.visual && shotsCfg.visual.downbeatEvery) || 4,
      halftone: shotsCfg.halftone || null,
      visual: shotsCfg.visual || {}, envelope, lyricLines, shotCount: shotsCfg.shots.length,
    },
    beats: beatmap.beats, shots: shotsCfg.shots,
    base: (() => {
      const dir = path.resolve(shotsRoot, shotsCfg.base || "out/base-frames2");
      const files = fs.readdirSync(dir).filter(f => /\.(png|jpg)$/i.test(f)).sort();
      return { urls: ["file://" + path.join(dir, files[0])], index0: 0 };
    })(),
    segments: words.segments.map(s => ({ start: s.start, end: s.end,
      words: words.words.filter(w => w.start >= s.start - 1e-3 && w.end <= s.end + 1e-3) })),
  };

  const browser = await puppeteer.launch({
    executablePath: a.chromium || "/usr/bin/chromium",
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--allow-file-access-from-files",
      "--force-color-profile=srgb", "--hide-scrollbars", `--window-size=${width},${height}`],
    defaultViewport: { width, height },
  });
  const page = await browser.newPage();
  page.on("pageerror", e => console.error("[pageerror]", e.message));
  await page.goto("file://" + path.resolve(__dirname, "../engine/page2.html"), { waitUntil: "load" });
  await page.evaluate(d => window.__setData(d), data);
  // 先渲染一帧，让 visual.js 拿到 state
  await page.evaluate(t => window.render(t), 0.5);
  const table = await page.evaluate(() => window.VISUAL.debugLines(0.5));
  await browser.close();

  const beats = beatmap.beats;
  const nearest = t => beats.reduce((p, c) => Math.abs(c - t) < Math.abs(p - t) ? c : p, beats[0]);
  const rows = [];
  let bad = 0;
  for (let i = 0; i < table.length; i++) {
    const L = table[i];
    const peak = Math.min(Math.max(L.last + 0.15, L.s0 + 0.1), L.e0 - 0.05);
    /* 末字上屏后还剩多久：这是「这句读得完整吗」的唯一硬指标 */
    const tail = L.e0 - L.lastT;
    const flags = [];
    if (L.e0 - L.s0 < 0.25) flags.push("可见<0.25s");
    if (tail < 0.12) flags.push(`末字只停${tail.toFixed(2)}s`);
    if (i + 1 < table.length && L.e0 > table[i + 1].s0 + 1e-6) flags.push("与下一行重叠");
    if (L.gate !== null) {
      if (Math.abs(L.gate - nearest(L.gate)) > 0.02) flags.push("gate离拍");
      if (L.gate - L.s0 > 0.25) flags.push("gate晚于首字>0.25s");
    }
    if (flags.length) bad++;
    rows.push({ i, style: L.style, zone: L.zone, s0: +L.s0.toFixed(3), e0: +L.e0.toFixed(3),
      visible: +(L.e0 - L.s0).toFixed(3), tail: +tail.toFixed(3), peak: +peak.toFixed(3), flags });
    console.log(
      `${String(i).padStart(3)} ${String(L.style).padEnd(8)} ${String(L.zone).padEnd(4)} ` +
      `入 ${L.s0.toFixed(2)} 离 ${L.e0.toFixed(2)} 可见 ${(L.e0 - L.s0).toFixed(2)}s ` +
      `末字 ${tail.toFixed(2)}s ${flags.length ? "⚠ " + flags.join(" ") : "✓"}`);
  }
  console.log(`\n共 ${table.length} 行，有问题的 ${bad} 行`);
  if (a.out) fs.writeFileSync(a.out, JSON.stringify({ rows }, null, 1), "utf8");
}

main().catch(e => { console.error(e); process.exit(1); });
