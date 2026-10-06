#!/usr/bin/env node
/* 单帧抽检：只渲染指定时刻的几帧，用来在整段 65s 渲染之前先看排版对不对。
 *
 * 用法：
 *   node tools/peek.js --shots shots-c15-test.json --times 184.6,187.2,190.0 --out /tmp/peek/
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
  if (!a.shots || !a.times || !a.out) {
    console.log("用法: node tools/peek.js --shots <shots.json> --times t0,t1,... --out <dir>/");
    process.exit(1);
  }
  const outDir = a.out;
  fs.mkdirSync(outDir, { recursive: true });

  const shotsCfg = JSON.parse(fs.readFileSync(a.shots, "utf8"));
  const words = JSON.parse(fs.readFileSync(a.words || "song/analysis/words-fixed.json", "utf8"));
  const beatmap = JSON.parse(fs.readFileSync(a.beats || "song/analysis/beatmap.json", "utf8"));
  const shotsRoot = path.dirname(path.resolve(a.shots));
  const width = shotsCfg.width || 1920, height = shotsCfg.height || 1080;

  const shots = shotsCfg.shots.map(s => {
    const o = { ...s };
    if (shotsCfg.bg === "base") return o;
    if (s.type === "plate") o.plateUrl = "file://" + path.resolve(shotsRoot, s.plate);
    else if (s.type === "video") {
      const dir = path.resolve(shotsRoot, s.frames);
      const files = fs.readdirSync(dir).filter(f => /\.(png|jpg)$/i.test(f)).sort();
      o.frameUrls = files.map(f => "file://" + path.join(dir, f));
    }
    return o;
  });

  let base = null;
  if (shotsCfg.bg === "base") {
    const dir = path.resolve(shotsRoot, shotsCfg.base || "out/base-frames2");
    const files = fs.readdirSync(dir).filter(f => /\.(png|jpg)$/i.test(f)).sort();
    const times = String(a.times).split(",").map(Number);
    const lo = Math.min.apply(null, times), hi = Math.max.apply(null, times);
    const i0 = Math.max(0, Math.floor(lo * (shotsCfg.fps || 24)) - 2);
    const i1 = Math.min(files.length - 1, Math.ceil(hi * (shotsCfg.fps || 24)) + 2);
    const urls = [];
    for (let i = i0; i <= i1; i++) urls.push("file://" + path.join(dir, files[i]));
    base = { urls: urls, index0: i0 };
  }

  let beatLen = 0.455;
  if (beatmap.beats && beatmap.beats.length > 2) {
    const d = [];
    for (let i = 1; i < beatmap.beats.length; i++) d.push(beatmap.beats[i] - beatmap.beats[i - 1]);
    d.sort((x, y) => x - y);
    beatLen = d[Math.floor(d.length / 2)] || beatLen;
  }
  const visualCfg = Object.assign({ title: "", ticker: [] }, shotsCfg.visual || {});
  const envPath = path.resolve(shotsRoot, "song/analysis/wave-envelope.json");
  const envelope = fs.existsSync(envPath) ? JSON.parse(fs.readFileSync(envPath, "utf8")) : null;
  const linesPath = path.resolve(shotsRoot, "song/analysis/lines.json");
  const lyricLines = fs.existsSync(linesPath) ? JSON.parse(fs.readFileSync(linesPath, "utf8")).lines : null;

  const data = {
    config: {
      t0: shotsCfg.t0, t1: shotsCfg.t1, fps: shotsCfg.fps || 24,
      accent: shotsCfg.accent || "#FF5FAF",
      bpm: beatmap.bpm_from_beats || beatmap.bpm_median || 0,
      beatLen,
      downbeatEvery: (shotsCfg.visual && shotsCfg.visual.downbeatEvery) || 4,
      halftone: shotsCfg.halftone || null,
      visual: visualCfg, envelope, lyricLines, shotCount: shots.length,
    },
    beats: beatmap.beats,
    shots,
    base: base,
    segments: words.segments.map(s => ({
      start: s.start, end: s.end,
      words: words.words.filter(w => w.start >= s.start - 1e-3 && w.end <= s.end + 1e-3),
    })),
  };

  const pageUrl = "file://" + path.resolve(__dirname, "..", "engine", "page2.html");
  const browser = await puppeteer.launch({
    executablePath: a.chromium || "/usr/bin/chromium",
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--allow-file-access-from-files",
      "--force-color-profile=srgb", "--hide-scrollbars", `--window-size=${width},${height}`],
    defaultViewport: { width, height },
  });
  const page = await browser.newPage();
  page.on("pageerror", e => console.error("[pageerror]", e.message));
  await page.goto(pageUrl, { waitUntil: "load" });
  await page.evaluate(d => window.__setData(d), data);
  const times = String(a.times).split(",").map(Number);
  for (const t of times) {
    await page.evaluate(tt => window.render(tt), t);
    const name = path.join(outDir, "t" + String(Math.round(t * 1000)).padStart(8, "0") + ".png");
    await page.screenshot({ path: name, clip: { x: 0, y: 0, width, height } });
    console.log("[peek]", t.toFixed(3), "->", name);
  }
  await browser.close();
}

main().catch(e => { console.error(e); process.exit(1); });
