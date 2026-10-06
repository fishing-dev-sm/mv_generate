#!/usr/bin/env node
/* 引擎 v2：shot-list 驱动的四层渲染器（H3 视频 / coverline / data 卡 / 印刷颗粒）。
 * v1 (render.js) 保持不动；本文件管多镜头合成。
 *
 * 用法：
 *   node engine/render2.js --shots shots.json \
 *        --words song/analysis/words-fixed.json --beats song/analysis/beatmap.json \
 *        --out out/take10-frames/
 * 之后 ffmpeg 合成：
 *   ffmpeg -framerate 24 -i out/take10-frames/f%04d.png -i out/take-audio.m4a \
 *          -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest out/take-test-10s.mp4
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
  console.log(`用法: node engine/render2.js --shots shots.json --words words-fixed.json
       --beats beatmap.json --out out/frames/
选项:
  --shots    shot-list JSON（t0/t1/fps + shots[]，见 shots.json）
  --words    逐词时间 JSON（analyze_audio.py 产出）
  --beats    beatmap.json
  --out      帧输出目录
  --chromium chromium 路径（默认 /usr/bin/chromium）`);
}

async function main() {
  const a = parseArgs(process.argv);
  if (a.help || !a.shots || !a.words || !a.beats || !a.out) {
    usage();
    process.exit(a.help ? 0 : 1);
  }
  const outDir = a.out;
  fs.mkdirSync(outDir, { recursive: true });

  const shotsCfg = JSON.parse(fs.readFileSync(a.shots, "utf8"));
  const words = JSON.parse(fs.readFileSync(a.words, "utf8"));
  const beatmap = JSON.parse(fs.readFileSync(a.beats, "utf8"));

  const shotsRoot = path.dirname(path.resolve(a.shots));
  const t0 = shotsCfg.t0, t1 = shotsCfg.t1, fps = shotsCfg.fps || 24;
  const width = shotsCfg.width || 1920, height = shotsCfg.height || 1080;

  const shots = shotsCfg.shots.map(s => {
    const o = { ...s };
    if (shotsCfg.bg === "base") return o;      // 底片模式：帧由下面的 base 段统一供
    if (s.type === "plate") {
      o.plateUrl = "file://" + path.resolve(shotsRoot, s.plate);
    } else if (s.type === "video") {
      const dir = path.resolve(shotsRoot, s.frames);
      const files = fs.readdirSync(dir).filter(f => /\.(png|jpg)$/i.test(f)).sort();
      if (!files.length) throw new Error(`no frames in ${dir}`);
      o.frameUrls = files.map(f => "file://" + path.join(dir, f));
      if (s.timemap) {
        const tm = JSON.parse(fs.readFileSync(path.resolve(shotsRoot, s.timemap), "utf8"));
        o.timemapPairs = tm.pairs;   // [[ref_t, clip_t], ...]，优先于 frameOffset
      }
    }
    return o;
  });

  /* 「底片模式」：整片画面只用一条已经剪好的底片（默认 out/base-frames2）。
   * 逐镜仍然保留，但只用来定「入场拍 / 章节 / 卡片的进出时刻」——画面不再按镜取帧，
   * 于是视觉层与底片天然同轴，不需要任何 frameOffset 去追。 */
  let base = null;
  if (shotsCfg.bg === "base") {
    const dir = path.resolve(shotsRoot, shotsCfg.base || "out/base-frames2");
    const files = fs.readdirSync(dir).filter(f => /\.(png|jpg)$/i.test(f)).sort();
    if (!files.length) throw new Error(`底片帧目录为空: ${dir}`);
    const i0 = Math.max(0, Math.floor(t0 * fps) - 1);
    const i1 = Math.min(files.length - 1, Math.ceil(t1 * fps) + 1);
    const urls = [];
    for (let i = i0; i <= i1; i++) urls.push("file://" + path.join(dir, files[i]));
    base = { urls: urls, index0: i0, dir: dir, n: files.length };
    console.log(`[base] ${files.length} 帧可用，本窗载入 ${urls.length} 帧（f${i0}–f${i1}）`);
  }

  /* 视觉层配置（对齐 Figma《Escape Velocity — Motion Layers》，见 visual.js 头注） */
  const visualCfg = Object.assign({
    /* ⚠️ 标题块 / 倒计时牌 / 翻牌条 / ticker 是「换歌必须整表替换」的文案表。
     * 这里一律留空，绝不用别的片的示例文案顶替——空着是待填，写错是事故。 */
    title: "",
    look: { total: 11, template: "造型 {n} / {t}" },
    countdown: { digits: "", line1: "", line2: "", note: "" },
    flap: { value: "", unit: "" },
    rulerFrom: 0,
    coverlineSide: "left",
    ticker: [],
  }, shotsCfg.visual || {});
  if (!visualCfg.ticker.length) {
    // ticker 条目必须真实可查：未配置时只用本片自带的实测数据
    visualCfg.ticker = [
      (beatmap.bpm_from_beats ? beatmap.bpm_from_beats.toFixed(1) : "0") + " BPM",
      "时长 " + Math.round(t1) + " S",
      shots.length + " 镜",
    ];
  }
  /* 节拍长度（ticker 的位移速度锁 1 字 / 1/8 拍） */
  let beatLen = 0.455;
  if (beatmap.beats && beatmap.beats.length > 2) {
    const d = [];
    for (let i = 1; i < beatmap.beats.length; i++) d.push(beatmap.beats[i] - beatmap.beats[i - 1]);
    d.sort((x, y) => x - y);
    beatLen = d[Math.floor(d.length / 2)] || beatLen;
  }
  /* 音频包络：波形必须是音频的纯函数（analyze_audio 之外单独产出的 envelope） */
  let envelope = null;
  const envPath = a.envelope || path.resolve(shotsRoot, "song/analysis/wave-envelope.json");
  if (fs.existsSync(envPath)) envelope = JSON.parse(fs.readFileSync(envPath, "utf8"));

  /* 逐字歌词（tools/make_lines.py 产出）：歌词层靠它做"唱到哪亮到哪"。
   * 与 envelope 一样自动发现，缺省不传也能跑（歌词层会退回 v1 段落样式）。 */
  let lyricLines = null;
  const linesPath = a.lines || path.resolve(shotsRoot, "song/analysis/lines.json");
  if (fs.existsSync(linesPath)) lyricLines = JSON.parse(fs.readFileSync(linesPath, "utf8")).lines;

  const data = {
    config: {
      t0, t1, fps,
      accent: shotsCfg.accent || "#FF5FAF",
      bpm: beatmap.bpm_from_beats || beatmap.bpm_median || 0,
      beatLen,
      downbeatEvery: (shotsCfg.visual && shotsCfg.visual.downbeatEvery) || 4,
      halftone: shotsCfg.halftone || null,
      visual: visualCfg,
      envelope,
      lyricLines,
      shotCount: shots.length,
    },
    beats: beatmap.beats,
    shots,
    base: base ? { urls: base.urls, index0: base.index0 } : null,
    segments: words.segments.map(s => ({
      start: s.start, end: s.end,
      words: words.words.filter(w => w.start >= s.start - 1e-3 && w.end <= s.end + 1e-3),
    })),
  };

  const pageUrl = "file://" + path.resolve(__dirname, "page2.html");
  const browser = await puppeteer.launch({
    executablePath: a.chromium || "/usr/bin/chromium",
    headless: "new",
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--allow-file-access-from-files",
      "--force-color-profile=srgb",
      "--hide-scrollbars",
      `--window-size=${width},${height}`,
    ],
    defaultViewport: { width, height },
  });
  const page = await browser.newPage();
  page.on("pageerror", e => console.error("[pageerror]", e.message));
  await page.goto(pageUrl, { waitUntil: "load" });
  await page.evaluate(d => window.__setData(d), data);
  console.log(`[preload] ok: ${shots.length} shots, ` +
    `${base ? base.urls.length + " base frames" :
      shots.reduce((n, s) => n + (s.frameUrls ? s.frameUrls.length : 0), 0) + " video frames"}`);

  const nFrames = Math.round((t1 - t0) * fps);
  const tStart = Date.now();
  for (let f = 0; f < nFrames; f++) {
    const t = t0 + f / fps;
    await page.evaluate(tt => window.render(tt), t);
    const name = path.join(outDir, "f" + String(f).padStart(4, "0") + ".png");
    await page.screenshot({ path: name, clip: { x: 0, y: 0, width, height } });
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
