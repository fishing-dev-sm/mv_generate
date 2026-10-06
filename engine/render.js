#!/usr/bin/env node
/* ⚠️ 已废弃（2026-10-01）：这是旧视觉方案的单图演示渲染器（陶橙 #E8632A 那一套）。
 * 生产一律用 `node engine/render2.js`（视觉层见 engine/visual.js，对齐 Figma 权威稿）。
 * 保留仅为历史参考，不要用它出片。 */
/* 轻量动效渲染器：headless Chromium + canvas，逐帧截图出 PNG 序列。
 *
 * 用法：
 *   node engine/render.js --words out/words.json --beats out/beatmap.json \
 *        --image assets/plate.png --t0 0 --t1 15 --fps 24 --out out/frames/
 *
 * 页面保持打开，每帧 evaluate render(t) 后 screenshot；每帧是时间的纯函数。
 * 之后用 ffmpeg 合成：
 *   ffmpeg -framerate 24 -i out/frames/f%04d.png -i out/window.wav \
 *          -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest out/demo.mp4
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

function usage() {
  console.log(`用法: node engine/render.js --words words.json --beats beatmap.json
       --image plate.png --t0 0 --t1 15 --fps 24 --out out/frames/
选项:
  --words    words.json（analyze_audio.py 产出）
  --beats    beatmap.json（analyze_audio.py 产出）
  --image    背景图（assets/plate.png）
  --t0/--t1  渲染时间窗（秒，相对窗口音频）
  --fps      帧率（默认 24）
  --out      帧输出目录
  --accent   强调色（默认 #E8632A）
  --chromium chromium 路径（默认 /usr/bin/chromium）`);
}

async function main() {
  const a = parseArgs(process.argv);
  if (a.help || !a.words || !a.beats || !a.image || !a.out) {
    usage();
    process.exit(a.help ? 0 : 1);
  }
  const t0 = parseFloat(a.t0 ?? "0");
  const t1 = parseFloat(a.t1 ?? "15");
  const fps = parseFloat(a.fps ?? "24");
  const outDir = a.out;
  fs.mkdirSync(outDir, { recursive: true });

  const words = JSON.parse(fs.readFileSync(a.words, "utf8"));
  const beatmap = JSON.parse(fs.readFileSync(a.beats, "utf8"));
  const data = {
    config: {
      t0, t1,
      accent: a.accent || "#E8632A",
      bpm: beatmap.bpm_from_beats || beatmap.bpm_median || 0,
    },
    beats: beatmap.beats,
    segments: words.segments.map(s => ({
      start: s.start, end: s.end,
      words: words.words.filter(w => w.start >= s.start - 1e-3 && w.end <= s.end + 1e-3),
    })),
  };
  const imgUrl = "file://" + path.resolve(a.image);
  const pageUrl = "file://" + path.resolve(__dirname, "page.html");

  const browser = await puppeteer.launch({
    executablePath: a.chromium || "/usr/bin/chromium",
    headless: "new",
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--allow-file-access-from-files",
      "--force-color-profile=srgb",
      "--hide-scrollbars",
      "--window-size=1920,1080",
    ],
    defaultViewport: { width: 1920, height: 1080 },
  });
  const page = await browser.newPage();
  await page.goto(pageUrl, { waitUntil: "load" });
  await page.evaluate(
    (d, url) => window.__setData(d, url), data, imgUrl);

  const nFrames = Math.round((t1 - t0) * fps);
  const tStart = Date.now();
  for (let f = 0; f < nFrames; f++) {
    const t = t0 + f / fps;
    await page.evaluate(tt => window.render(tt), t);
    const name = path.join(outDir, "f" + String(f).padStart(4, "0") + ".png");
    await page.screenshot({ path: name, clip: { x: 0, y: 0, width: 1920, height: 1080 } });
    if (f % 48 === 0 || f === nFrames - 1) {
      const el = (Date.now() - tStart) / 1000;
      console.log(`[render] ${f + 1}/${nFrames}  t=${t.toFixed(3)}s  ` +
        `(${((f + 1) / el).toFixed(1)} fps)`);
    }
  }
  await browser.close();
  const el = (Date.now() - tStart) / 1000;
  console.log(`[ok] ${nFrames} 帧 -> ${outDir}  用时 ${el.toFixed(1)}s ` +
    `(avg ${(nFrames / el).toFixed(1)} fps)`);
}

main().catch(e => { console.error(e); process.exit(1); });
