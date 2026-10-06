/* ============================================================================
 * 视觉层 · 对齐 Figma《Escape Velocity — Motion Layers · FF5FAF×FFAF00》
 * 权威稿：figma fileKey Hx5JzusWsIdBdtzCm0oOm4 · page 0:1「01 · 设计规范（中文）」
 *   chrome 解剖 2:2 / 图例 2:483 · 文字动画 3:2 · 渲染总则 3:112 · 材质 22:2
 *   原子件 4:2 4:15 4:25 4:52 4:106 4:121 4:147 5:2 5:84 5:99 5:120 5:141
 *         5:163 5:183 5:231 5:248 5:298 5:323 5:334 5:347 5:354
 * 2026-10-01 导演原则：旧视觉方案（陶橙 #E8632A / 84px 下划线字幕 / mono data 卡 /
 *   文字层第二遍强半调）整份作废，一切以 Figma 稿为准。
 * 几何、字级、字距、色值逐节点取自上述 Figma 节点，不是估算。
 * 层级：底图/视频 → 印刷 pass（引擎负责，全片只此一处）→【本层：chrome → 意义层 → 歌词】
 * ==========================================================================*/
(function () {
  "use strict";
  const W = 1920, H = 1080;

  /* ---------- 色彩（Figma 1:2） ---------- */
  const C = {
    ink: "#0B0D10", panel: "#14181B", tile: "#1A1C20", line: "#3B4046",
    sub: "#8A9199", paper: "#F5F5F2", accent: "#FF5FAF", amber: "#FFAF00",
    navy: "#121A26", term: "#0D1219", paperCard: "#EEECE3",
  };

  /* ---------- 材质：毛玻璃（Figma 22:2） ---------- */
  const MAT = {
    panel: { bg: C.panel, a: 0.62, blur: 16 },
    tile: { bg: C.tile, a: 0.68, blur: 14 },
    navy: { bg: C.navy, a: 0.72, blur: 20 },
    term: { bg: C.term, a: 0.75, blur: 18 },
    paper: { bg: C.paperCard, a: 0.88, blur: 8 },
  };

  /* ---------- 字体栈（Figma 1:32；本机以 CJK 版与 Nerd Font 版等价替代） ---------- */
  const F = {
    sans: '"Noto Sans CJK SC","Noto Sans SC",sans-serif',
    mono: '"JetBrainsMono NF","JetBrains Mono",monospace',
    serif: '"Noto Serif CJK SC","Noto Serif SC",serif',
  };

  let mainCv = null;
  const blurCache = new Map();

  /* ---------- 基础工具 ---------- */
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const easeOutCubic = p => 1 - Math.pow(1 - p, 3);
  function hash(n) {
    const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
    return s - Math.floor(s);
  }
  /* ---------- 节拍时钟：一切入场 / 落定都落在拍上（Figma 3:112-02、3:2） ---------- */
  function beatClock(st) {
    const beats = st.beats || [], t = st.t;
    let lo = 0, hi = beats.length - 1, idx = -1;
    while (lo <= hi) {
      const m = (lo + hi) >> 1;
      if (beats[m] <= t) { idx = m; lo = m + 1; } else hi = m - 1;
    }
    const dpb = st.downbeatEvery || 4;
    const len = st.beatLen || 0.455;
    const start = idx >= 0 ? beats[idx] : t;
    const since = t - start;
    const isDown = idx >= 0 && idx % dpb === 0;
    const lastDownIdx = idx - (((idx % dpb) + dpb) % dpb);
    return {
      idx: idx,
      since: since,
      phase: len > 0 ? clamp(since / len, 0, 1) : 0,
      pulse: since >= 0 && since < 0.6 ? Math.exp(-since * 8) : 0,
      down: isDown && since < 0.4 ? Math.exp(-since * 10) : 0,
      isDown: isDown,
      nextBeat: (idx + 1 < beats.length) ? beats[idx + 1] : t,
      /* 最近一个重拍（每 dpb 拍一次）——换值/翻牌的落点都锁它 */
      lastDown: lastDownIdx >= 0 ? beats[lastDownIdx] : start,
      lastDownIdx: lastDownIdx,
      len: len,
      barPos: idx < 0 ? 0 : idx % dpb,
    };
  }
  /* 音频包络查值：视觉层的「亮 / 动量」必须是音频的纯函数，不是随机数 */
  function envAt(env, t) {
    if (!env || !env.env || !env.env.length) return 0.35;
    return env.env[clamp(Math.floor(t / env.dt), 0, env.env.length - 1)];
  }
  /* 换值模式：把「大数字 / 倒计时牌」绑到真实的时间量上，值一变就翻牌 */
  function valueAt(V, st, kind) {
    const v = V || {};
    const dpb = st.downbeatEvery || 4;
    if (kind === "bars") {
      const beats = st.beats || [];
      let n = 0;
      for (let i = 0; i < beats.length; i++) {
        if (beats[i] >= st.t && i % dpb === 0) n++;
      }
      return { s: String(n).padStart(2, "0"), sPrev: String(n + 1).padStart(2, "0"), prog: (st.t - st.ck.lastDown) / (3 / 24) };
    }
    const end = v.songEnd || 200.3;
    if (kind === "seconds") {
      const n = Math.max(0, Math.ceil(end - st.t));
      return { s: String(n).padStart(2, "0"), sPrev: String(n + 1).padStart(2, "0"), prog: (st.t - Math.floor(st.t)) / (3 / 24) };
    }
    return null;
  }
  /* 翻牌：3 帧 = 上瓣落下 / 中缝 / 下瓣落定，linear——机械件不做弹性（Figma 3:2）
   * prog <= 0 = 这一面还没翻到（不画字，o.show 可显式要求显示）；prog >= 1 = 已落定（字居中）。
   * ⚠️ 2026-10-01 修：旧版 p=0 也把字画出来且落位偏下（mid±h/4），后果有两个——
   *   ① `flap.word` 会提前半秒露面（违反 3:2 红线「永不提前」）；② 落定的字永远偏下半格。 */
  function flapFace(c, x, y, w, h, ch, prog, o) {
    o = o || {};
    const p = clamp(prog, 0, 1);
    const mid = y + h / 2;
    c.fillStyle = o.bg || C.tile;
    c.fillRect(x, y, w, h);
    const flipping = p > 0 && p < 1;
    /* 翻面过程中的侧光：牌面瞬间变亮，落定即灭（机械件的一帧痕迹） */
    if (flipping) {
      c.globalAlpha = 0.5 * Math.sin(p * Math.PI);
      c.fillStyle = C.paper;
      c.fillRect(x, y, w, h);
      c.globalAlpha = 1;
    }
    const shown = o.show === undefined ? p > 0 : !!o.show;
    if (ch && shown) {
      const k = p < 0.5 ? 1 - p * 2 : (p - 0.5) * 2;
      /* 上半程：新字从上瓣落到中缝；下半程：在中缝原地显影——落定位置永远是牌心 */
      const yy = (flipping && p < 0.5) ? mid - (h / 4) * k : mid;
      const sc = (flipping && p >= 0.5) ? Math.max(0.4, k) : 1;
      c.save();
      c.beginPath(); c.rect(x, y, w, h); c.clip();
      c.globalAlpha = (flipping && p >= 0.5) ? k : 1;
      c.fillStyle = o.fg || C.paper;
      font(c, (o.size || 20) * sc, o.weight || "bold", o.family || F.sans, 0);
      c.textAlign = "center";
      c.textBaseline = "middle";
      c.fillText(ch, x + w / 2, yy);
      c.globalAlpha = 1;
      c.restore();
      if ("letterSpacing" in c) c.letterSpacing = "0px";
    }
    if (flipping) {
      c.fillStyle = C.ink;
      c.fillRect(x, mid - 1, w, 2);
    }
  }
  /* 文字机械滚动：旧值向上退出、新值自下落入，linear，落在拍上 */
  function rollText(c, oldS, newS, x, top, boxH, prog, o) {
    const p = clamp(prog, 0, 1);
    c.save();
    c.beginPath(); c.rect(x - 2, top - 4, 900, boxH + 8); c.clip();
    if (p < 1) txt(c, oldS, x, top - boxH * p, Object.assign({}, o, { alpha: 1 - p }));
    txt(c, newS, x, top + boxH * (1 - p), o);
    c.restore();
  }
  /* 行的逐行入场：第 i 行落在 entry 之后的第 i 拍上（Figma 各卡「动画」注记） */
  let ALPHA_CTX = 1;
  function withAlpha(a, fn) {
    const prev = ALPHA_CTX;
    ALPHA_CTX = prev * clamp(a, 0, 1);
    fn();
    ALPHA_CTX = prev;
  }
  function font(c, size, weight, family, tracking) {
    const w = weight === "light" ? 300 : weight === "medium" ? 500
      : weight === "bold" ? 700 : weight === "black" ? 900 : 400;
    c.font = w + " " + size + "px " + family;
    if ("letterSpacing" in c) c.letterSpacing = (tracking || 0) + "px";
  }
  /* 文本：x 为左边界（align=right 时为右边界），top 为 Figma 文本框顶端 */
  function txt(c, s, x, top, o) {
    o = o || {};
    const size = o.size || 12, family = o.family || F.sans;
    font(c, size, o.weight, family, o.tracking);
    c.textBaseline = "alphabetic";
    c.textAlign = o.align === "right" ? "right" : o.align === "center" ? "center" : "left";
    c.globalAlpha = (o.alpha === undefined ? 1 : o.alpha) * ALPHA_CTX;
    c.fillStyle = o.color || C.paper;
    const base = top + (o.baselineOffset === undefined ? size * 0.88 : o.baselineOffset);
    c.fillText(s, x, base);
    c.globalAlpha = 1;
    if ("letterSpacing" in c) c.letterSpacing = "0px";
    return c.measureText(s).width;
  }
  function hair(c, x, y, w, h, col) {
    c.globalAlpha = ALPHA_CTX;
    c.fillStyle = col || C.line;
    c.fillRect(x, y, w, h === undefined ? 1 : h);
    c.globalAlpha = 1;
  }
  /* 毛玻璃卡：先对底图区域离屏 blur，再叠半透明色 + 1px 细线（Figma 22:2 的 canvas 备选） */
  function frost(c, x, y, w, h, m) {
    m = m || MAT.panel;
    const pad = Math.ceil(m.blur * 2);
    const key = m.bg + m.blur;
    let bc = blurCache.get(key);
    if (!bc) { bc = document.createElement("canvas"); blurCache.set(key, bc); }
    if (bc.width < w + 2 * pad || bc.height < h + 2 * pad) {
      bc.width = Math.max(bc.width, w + 2 * pad);
      bc.height = Math.max(bc.height, h + 2 * pad);
    }
    const bx = bc.getContext("2d");
    bx.setTransform(1, 0, 0, 1, 0, 0);
    bx.clearRect(0, 0, bc.width, bc.height);
    if (mainCv) {
      bx.filter = "blur(" + m.blur + "px) saturate(1.1)";
      bx.drawImage(mainCv, x - pad, y - pad, w + 2 * pad, h + 2 * pad, 0, 0, w + 2 * pad, h + 2 * pad);
      bx.filter = "none";
    }
    c.save();
    c.beginPath(); c.rect(x, y, w, h); c.clip();
    c.drawImage(bc, x - pad, y - pad);
    c.globalAlpha = m.a;
    c.fillStyle = m.bg;
    c.fillRect(x, y, w, h);
    c.globalAlpha = 1;
    c.strokeStyle = C.line;
    c.lineWidth = 1;
    c.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
    c.restore();
  }
  /* 条码：确定性宽窄条 */
  function barcode(c, x, y, w, h, seed) {
    let cx = x, i = 0;
    c.fillStyle = C.ink;
    while (cx < x + w - 1) {
      const bw = 1 + Math.floor(hash(seed + i) * 3);
      c.fillRect(cx, y, bw, h);
      cx += bw + 1 + Math.floor(hash(seed + i + 0.5) * 3);
      i++;
    }
  }
  /* ---------- 波形：56 柱，柱宽 2，间距 3.4，底边 y=110 ---------- */
  function waveform(c, t, env) {
    const N = 56, x0 = 1653.6, step = 3.4, base = 110, hMin = 4.7, hMax = 30;
    for (let i = 0; i < N; i++) {
      let lv;
      if (env && env.env && env.env.length) {
        const idx = clamp(Math.floor((t - (N - 1 - i) * 0.07) / env.dt), 0, env.env.length - 1);
        lv = env.env[idx];
      } else lv = 0.2 + 0.8 * hash(Math.floor(t * 30) * 0.37 + i * 3.7);
      const h = hMin + (hMax - hMin) * lv;
      c.globalAlpha = 0.55 + 0.45 * lv;
      c.fillStyle = C.sub;
      c.fillRect(x0 + i * step, base - h, 2, h);
    }
    c.globalAlpha = 1;
  }
  function timecode(t) {
    const f = Math.floor((t - Math.floor(t)) * 24);
    const s = Math.floor(t);
    return [Math.floor(s / 60), s % 60, f].map(v => String(v).padStart(2, "0")).join(":");
  }
  /* ticker：匀速左滚 1 字 / 1/8 拍，永不停 */
  function ticker(c, st) {
    const items = st.visual.ticker;
    if (!items || !items.length) return;
    const s = items.join("  *  ") + "  *  ";
    font(c, 12, "normal", F.sans, 1);
    const w = c.measureText(s).width;
    const beat = st.beatLen || 0.455;
    const speed = (w / s.length) * (8 / beat);
    const off = (st.t * speed) % w;
    c.globalAlpha = 1;
    c.fillStyle = C.sub;
    c.textAlign = "left";
    c.textBaseline = "alphabetic";
    for (let x = 40 - off; x < W; x += w) c.fillText(s, x, 1042 + 12 * 0.88);
    if ("letterSpacing" in c) c.letterSpacing = "0px";
  }
  /* ---------- Chrome 常驻层（Figma 2:2 + 2:483；图例编号圆点不属于画面，不绘制） ---------- */
  function chrome(c, st) {
    const V = st.visual;
    const shotIdx = st.shotIndex;
    const ck = st.ck;
    const FLIP = 3 / 24;                                   // 翻转 3 帧（Figma 3:2）
    const changeBeat = st.nextBeatAfter(st.shot.t0);       // 本镜第一个拍：所有换值都在这里落定
    const chProg = clamp((st.t - changeBeat) / FLIP, 0, 1);
    /* 1 对位标记 +：四角，18px 十字，次级灰，距边 24px */
    c.fillStyle = C.sub;
    [[25, 25], [1896, 25], [25, 1057], [1896, 1057]].forEach(function (p) {
      c.fillRect(p[0] - 9, p[1] - 1, 18, 2);
      c.fillRect(p[0] - 1, p[1] - 9, 2, 18);
    });
    /* 2 造型计数器：左上 (76,55) 13px Medium 字距 2
     * 换 Look 时机械滚动一次（linear），落在本镜第一个拍上 */
    const LK = V.look || { total: 11, template: "造型 {n} / {t}" };
    const nShot = Math.max(1, st.shotCount);
    const own = (st.shot && st.shot.lookNo !== undefined) ? st.shot.lookNo : null;
    const lookAt = k => {
      /* 有真号就报真号（例如「镜次 52 / 55」），没有才按镜头比例摊 */
      if (own !== null && k === shotIdx) return own;
      if (own !== null && k === shotIdx - 1) return own - 1;
      return Math.min(LK.total, 1 + Math.floor(Math.max(0, k) * LK.total / nShot));
    };
    const pad2 = v => String(v).padStart(2, "0");
    const lookS = k => (LK.template || "{n} / {t}").replace("{n}", pad2(lookAt(k))).replace("{t}", pad2(LK.total));
    const lookOpt = { size: 13, weight: "medium", tracking: 2 };
    if (lookAt(shotIdx) !== lookAt(shotIdx - 1) && chProg < 1) {
      rollText(c, lookS(shotIdx - 1), lookS(shotIdx), 76, 55, 16, chProg, lookOpt);
    } else {
      txt(c, lookS(shotIdx), 76, 55, lookOpt);
    }
    /* 2b 章节标签：真实章节名（Intro / Verse / Chorus / Bridge / Outro），
     * 换章节时跟着造型计数一起滚一次——读数不是装饰，是这首歌的结构。 */
    const secS = (st.shot && st.shot.section) ? String(st.shot.section).toUpperCase() : "";
    if (secS) txt(c, secS, 76, 78, { size: 9, family: F.mono, color: C.sub, tracking: 3 });
    /* 3 标题块 + 波形：右上右对齐至 1844，13px Medium 字距 4 */
    if (V.title) txt(c, V.title, 1844, 55, { size: 13, weight: "medium", tracking: 4, align: "right" });
    waveform(c, st.t, st.envelope);
    /* 4 迷你倒计时牌：数字牌 (1470,118)(1488,118) 16×22，亮粉 17px mono bold */
    const cd = Object.assign({}, V.countdown || {}, (st.shot && st.shot.countdown) || {});
    let hasCd = cd.digits !== undefined && cd.digits !== null && String(cd.digits) !== "";
    let d = "", dPrev = "", cdProg = chProg;
    if (cd.mode === "bars" || cd.mode === "seconds") {
      /* 真实倒计时：值在每个重拍（bars）/ 每个整秒（seconds）变一次，变的那一刻翻牌 */
      const vv = valueAt(V, st, cd.mode);
      hasCd = true; d = vv.s; dPrev = vv.sPrev; cdProg = clamp(vv.prog, 0, 1);
    } else {
      const dv = Number(String(cd.digits === undefined ? "" : cd.digits).replace(/[^0-9-]/g, ""));
      d = hasCd ? String(isNaN(dv) ? cd.digits : dv).padStart(2, "0").slice(-2) : "";
      dPrev = hasCd ? String(isNaN(dv) ? cd.digits : dv + 1).padStart(2, "0").slice(-2) : "";
    }
    [0, 1].forEach(function (i) {
      flapFace(c, 1470 + i * 18, 118, 16, 22, hasCd ? d[i] : null, cdProg, {
        bg: C.tile, fg: C.accent, size: 17, family: F.mono, show: hasCd,
      });
      if (cdProg < 1 && dPrev[i] !== d[i]) {
        /* 旧字退出瞬间（替换字符已在 flapFace 内完成） */
      }
    });
    txt(c, cd.line1 || "", 1514, 119, { size: 13, weight: "bold", tracking: 3 });
    txt(c, cd.line2 || "", 1514, 136, { size: 13, weight: "bold", tracking: 3 });
    txt(c, cd.note || "", 1470, 164, { size: 9, color: C.sub, tracking: 3 });
    /* 5 左侧标尺：x=30 纵轴 y200..960，每 20px 刻度，每 5 格出编号
     * 时间轴模式：刻度号 = 该高度的真实歌曲秒数（后三位），游标 = 当前播放位置——
     * 于是游标是连续下行的（不是跳格），每拍在游标上闪一次。 */
    c.fillStyle = C.sub;
    c.fillRect(30, 200, 1, 760);
    const TL = V.ruler && V.ruler.mode === "timeline"
      ? { t0: V.ruler.t0, t1: V.ruler.t1 } : null;
    const tAtY = y => TL.t0 + (y - 200) / 760 * (TL.t1 - TL.t0);
    const yAtT = tt => 200 + (tt - TL.t0) / (TL.t1 - TL.t0) * 760;
    for (let k = 0; k <= 38; k++) {
      const y = 200 + k * 20;
      if (y > 960) break;
      if (k % 5 === 0) {
        c.fillRect(20, y, 10, 1);
        const lab = TL ? String(Math.floor(tAtY(y))).slice(-3)
          : String(V.rulerFrom + shotIdx + k / 5).padStart(3, "0");
        txt(c, lab, 38, y - 5, { size: 9, family: F.mono, color: C.sub, tracking: 1 });
      } else c.fillRect(25, y, 5, 1);
    }
    const headY = TL ? clamp(yAtT(st.t), 200, 960)
      : 200 + (Math.max(0, ck.idx) % 38) * 20;
    c.fillStyle = C.paper;
    c.globalAlpha = 0.45 + 0.55 * ck.pulse;
    c.fillRect(20, headY, 12, 2);
    if (ck.pulse > 0.02) {                       // 拍点：游标上闪一道次级刻痕
      c.globalAlpha = ck.pulse * 0.9;
      c.fillRect(32, headY - 4, 5, 1);
      c.fillRect(32, headY + 4, 5, 1);
    }
    c.globalAlpha = 1;
    /* 6 翻牌长条：细线 (76,788)/(76,874)，52 格 26×62 y=800，大数字 40px mono bold 亮粉
     * 换值 → 逐牌 30ms 级联翻面（从左向右扫过）；归零 → 整排翻成终场文字 */
    hair(c, 76, 788, 1768, 1, C.line);
    hair(c, 76, 874, 1768, 1, C.line);
    const flap = Object.assign({}, V.flap || {}, (st.shot && st.shot.flap) || {});
    const NCELL = 52, CW = 26, CH = 62, CX = 210, CY = 800, CGAP = 30;
    /* 整排横扫用 3/4 拍跑完（52 格）；linear，不做弹性（Figma 3:2 机械件口径） */
    const stagger = (ck.len * 0.75) / NCELL;
    const cells = [];
    for (let i = 0; i < NCELL; i++) {
      cells.push({ p: clamp((st.t - (changeBeat + i * stagger)) / FLIP, 0, 1) });
    }
    if (flap.word) {
      /* 归零 → 整排翻成终场文字；字牌居中，其余格仍画成待命格（否则长条会缺一块） */
      const chars = flap.word.split("");
      const start = Math.max(0, Math.round((NCELL - chars.length) / 2));
      const at = flap.wordAt === undefined ? changeBeat : flap.wordAt;
      chars.forEach(function (ch, j) {
        const i = start + j;
        if (i < 0 || i >= NCELL) return;
        const at0 = at + j * 0.03;
        cells[i] = {
          p: clamp((st.t - at0) / FLIP, 0, 1),
          ch: ch, show: st.t >= at0,
          acc: flap.accent && flap.accent.indexOf(j) >= 0,
        };
      });
    }
    cells.forEach(function (cl, i) {
      flapFace(c, CX + i * CGAP, CY, CW, CH, cl.ch || null, cl.p,
        (cl.ch && cl.show) ? { bg: C.paper, fg: cl.acc ? C.accent : C.ink, size: 20, show: true } : { bg: C.tile });
    });
    /* 灯墙：52 格 = 52 盏灯。每格亮度取自「它自己那一刻」的真实音频包络，
     * 于是整排是一条随时间横移的灯浪——唱到哪亮到哪；每个重拍整排再点一次火。
     * （Figma 3:112-02：动效由音轨驱动，不写死关键帧。） */
    if (flap.live) {
      const lag = flap.lag === undefined ? 0.012 : flap.lag;
      const igniteAt = flap.igniteAt === undefined ? Math.max(st.shot.t0, ck.lastDown) : flap.igniteAt;
      for (let i = 0; i < NCELL; i++) {
        const lit = clamp((st.t - igniteAt - i * stagger) / (ck.len * 0.5), 0, 1);
        if (lit <= 0) continue;
        /* 最左格 = 当下，往右依次是更早的音；于是灯浪自左向右推出去 */
        const lv = envAt(st.envelope, st.t - i * lag);
        if (lv < 0.1) continue;
        const r = 2.6 + 3.8 * clamp((lv - 0.1) / 0.9, 0, 1);
        c.globalAlpha = lit * (0.3 + 0.7 * lv);
        c.fillStyle = C.accent;
        c.beginPath(); c.arc(CX + i * CGAP + CW / 2, CY + CH / 2, r, 0, Math.PI * 2); c.fill();
      }
      c.globalAlpha = 1;
    }
    let hasFlap = flap.value !== undefined && flap.value !== null && String(flap.value) !== "";
    let vCur = "", vPrev = "", flProg = chProg;
    if (flap.mode === "seconds" || flap.mode === "bars") {
      const vv = valueAt(V, st, flap.mode);
      hasFlap = true; vCur = vv.s; vPrev = vv.sPrev; flProg = clamp(vv.prog, 0, 1);
    } else if (hasFlap) {
      vCur = String(flap.value).padStart(2, "0");
      vPrev = String(Number(flap.value) + 1).padStart(2, "0");
    }
    if (hasFlap) {
      const numOpt = { size: 40, weight: "bold", family: F.mono, color: C.accent, baselineOffset: 41 };
      if (vCur !== vPrev && flProg < 1) rollText(c, vPrev, vCur, 76, 810, 53, flProg, numOpt);
      else txt(c, vCur, 76, 810, numOpt);
    }
    if (flap.unit) txt(c, flap.unit, 76, 856, { size: 9, color: C.sub, tracking: 2 });
    /* 8 时间码：右下右对齐至 1844，13px mono 字距 2 */
    txt(c, timecode(st.t), 1844, 998, { size: 13, family: F.mono, color: C.sub, tracking: 2, align: "right" });
    /* 9 底部 ticker：细线 y=1024，正文 (40,1042) 12px Regular 字距 1
     * + 一条极淡的下沉渐变：只为让滚字在亮画面（红光墙）上仍可读，不参与印刷 pass */
    const sg = c.createLinearGradient(0, 872, 0, H);
    sg.addColorStop(0, "rgba(11,13,16,0)");
    sg.addColorStop(0.55, "rgba(11,13,16,0.4)");
    sg.addColorStop(1, "rgba(11,13,16,0.66)");
    c.fillStyle = sg;
    c.fillRect(0, 872, W, H - 872);
    hair(c, 0, 1024, 1920, 1, C.line);
    ticker(c, st);
  }
  /* ---------- 文字动画四模式（Figma 3:2） ---------- */
  /* 字幕 SUBTITLE 兜底档：下三分之一 · 一行一句 · 逐词入场
   * （opacity 0→1 + y +8→0，1/16 拍，ease-out）。没给行表时走这条老路。 */
  function subtitlePlain(c, st) {
    const beat = st.beatLen || 0.455;
    const win = beat / 16;
    /* 驻留到下一句首词；无后续时硬切落在拍上（Figma 3:2「离场 硬切·落在节拍上」） */
    const segs = st.segments;
    const rows = segs.filter(function (s, i) {
      const next = segs[i + 1];
      const cut = (next && next.start - s.end < 1.5) ? next.start : st.nextBeatAfter(s.end);
      return st.t >= s.start - 0.25 && st.t < cut;
    });
    const base = 940;
    rows.forEach(function (seg, row) {
      const words = seg.words;
      if (!words.length) return;
      font(c, 28, "normal", F.sans, 1);
      const gap = 12;
      const ws = words.map(w => c.measureText(w.word).width);
      const total = ws.reduce((a, b) => a + b, 0) + gap * (words.length - 1);
      let x = (W - total) / 2;
      const y = base - row * 48;
      words.forEach(function (w, i) {
        if (st.t >= w.start) {
          const e = easeOutCubic(clamp((st.t - w.start) / win, 0, 1));
          c.globalAlpha = e;
          font(c, 28, "normal", F.sans, 1);
          c.textAlign = "left";
          c.textBaseline = "alphabetic";
          c.fillStyle = C.paper;
          c.fillText(w.word, x, y + 8 * (1 - e));
          c.globalAlpha = 1;
        }
        x += ws[i] + gap;
      });
    });
    if ("letterSpacing" in c) c.letterSpacing = "0px";
  }
  /* ==========================================================================
   * 情绪字幕 v2（2026-10-01）：字幕是设计件，不是说明条。
   * 稿子自己就给了三件"被设计的歌词"：原子件 20 划改字（5:347）· 原子件 21 回声堆叠（5:354）
   * · 3:2 的四档声部。这里把它扩成 5 种按情绪选用的字幕，由行表
   *   visual.lyrics.lines[].mode 指定：
   *   measure 量尺字幕 · 叙事陈述 —— 句下压一条「该句自己的拍网格」，每拍一道刻度，
   *                                    走到哪亮到哪，右侧标该句拍数（像仪器在跟你核对）
   *   punch   重音字幕 · 金句落点 —— 句眼放大 1.35× 上亮粉，重拍硬切 + 一帧 104%→100% 落定
   *   whisper 低语字幕 · 收尾松弛 —— 26px 次级灰、字距 +3、不做任何装饰
   *   strike  划改字幕 · 否定替换 —— 旧词划 2px 亮粉线（落在词尾音节），新词亮粉
   *   stack   回声字幕 · 重复尾音 —— 同词逐层衰减 100/65/40/22，末层亮粉
   * 三条纪律（Figma 3:2 红线）：**不抢拍**（never early，可延迟不可提前）· 离场硬切落拍 ·
   * 每个字落在它被唱出来的那一刻（逐字时刻由行表给出，下限受镜头入口拍约束）。
   * 单主角纪律：一屏只有一个主角——本镜已有 masthead / 封面行时，字幕退成低语档。
   * ======================================================================== */
  function lyricLines(st) {
    const cfg = st.visual && st.visual.lyrics;
    return (cfg && cfg.lines && cfg.lines.length) ? cfg.lines : null;
  }
  /* 一行的逐字时刻：行表给全就用行表；没给按行区间均分 */
  function charTimes(L) {
    const chars = L.text.split("");
    if (L.at && L.at.length === chars.length) return L.at.slice();
    const a = (L.start === undefined) ? (L.at && L.at[0]) || 0 : L.start;
    const b = (L.end === undefined) ? a + 1 : L.end;
    return chars.map(function (_, i) { return a + (b - a) * i / chars.length; });
  }
  /* 一行字幕落座：逐字入场（opacity 0→1 + y +8→0，1/16 拍 ease-out） */
  function lyricGlyphs(c, st, L, o) {
    const beat = st.beatLen || 0.455, win = beat / 16;
    const chars = L.text.split(""), at = charTimes(L);
    const i0 = (o.hit && o.hit.length) ? o.hit[0] : -1;
    const i1 = (o.hit && o.hit.length) ? o.hit[1] : -1;
    let x = o.x, lineW = 0;
    const pos = [];
    for (let i = 0; i < chars.length; i++) {
      const big = i >= i0 && i < i1;
      const sz = big ? o.size * 1.35 : o.size;
      font(c, sz, big ? "bold" : o.weight || "normal", F.sans, o.tracking);
      const w = c.measureText(chars[i]).width + o.tracking;
      pos.push({ x: x, w: w, sz: sz, big: big });
      x += w;
    }
    lineW = x - o.x;
    for (let i = 0; i < chars.length; i++) {
      if (st.t < at[i]) continue;
      const p = pos[i], dt = st.t - at[i];
      const ez = easeOutCubic(clamp(dt / win, 0, 1));
      /* 句眼 = 重拍硬切；1 帧 104%→100% 落定（稿子巨字同款） */
      const k = (p.big && dt < 1 / 24) ? 1.04 - 0.04 * (dt / (1 / 24)) : 1;
      font(c, p.sz * k, p.big ? "bold" : o.weight || "normal", F.sans, o.tracking);
      c.textAlign = "left";
      c.textBaseline = "alphabetic";
      c.globalAlpha = ez;
      c.fillStyle = p.big ? C.accent : o.color;
      c.fillText(chars[i], p.x, o.base + 8 * (1 - ez));
      c.globalAlpha = 1;
    }
    if ("letterSpacing" in c) c.letterSpacing = "0px";
    return { pos: pos, w: lineW, at: at };
  }
  function drawLyricLine(c, st, L, forceMode) {
    const beat = st.beatLen || 0.455;
    const mode = forceMode || L.mode || "measure";
    const whisper = mode === "whisper";
    const size = whisper ? 26 : 30;
    const x0 = (st.visual.lyricX === undefined) ? 120 : st.visual.lyricX;
    const top = (st.visual.lyricY === undefined) ? 916 : st.visual.lyricY;
    const base = top + size * 0.88;
    const barY = top + size + 34;
    const opt = {
      x: x0, base: base, size: size,
      color: whisper ? C.sub : C.paper,
      tracking: whisper ? 3 : 1,
      weight: "normal",
      hit: (mode === "punch" && L.hit) ? L.hit : null,
    };
    if (mode === "stack") {
      /* 回声字幕：同词逐层衰减，每层 = 一个 1/4 音符，末层亮粉 */
      const n = L.repeat || 4, t0 = charTimes(L)[0];
      const sz = size - 4, step = sz * 1.35;
      for (let i = 0; i < n; i++) {
        const at = t0 + i * beat / 4;
        if (st.t < at) continue;
        const e = easeOutCubic(clamp((st.t - at) / (beat / 8), 0, 1));
        txt(c, L.text, x0, top + i * step, {
          size: sz, tracking: 1, alpha: ([1, 0.65, 0.4, 0.22][i] || 0.2) * e,
          color: i === n - 1 ? C.accent : C.paper,
        });
      }
      return;
    }
    if (mode === "strike") {
      /* 划改字幕：旧词划亮粉删除线（落点在词尾音节），新词亮粉 */
      let px = x0;
      (L.parts || []).forEach(function (pt, i) {
        const sz = size, w = (function () {
          font(c, sz, pt.old ? "normal" : "bold", F.sans, 1);
          return c.measureText(pt.t).width;
        })();
        const at = pt.at !== undefined ? pt.at : charTimes(L)[0] + i * beat;
        const e = easeOutCubic(clamp((st.t - at) / (beat / 16), 0, 1));
        if (st.t >= at) {
          txt(c, pt.t, px, top, {
            size: sz, tracking: 1, alpha: e,
            weight: pt.old ? "normal" : "bold",
            color: pt.old ? C.paper : C.accent,
          });
          if (pt.old) {
            const sweep = clamp((st.t - at - (beat / 8)) / (beat / 8), 0, 1);
            if (sweep > 0) { c.fillStyle = C.accent; c.fillRect(px, base + 8, w * sweep, 2); }
          }
        }
        px += w + 12;
      });
      return;
    }
    const g = lyricGlyphs(c, st, L, opt);
    if (mode === "measure") {
      /* 量尺字幕：句下压一条该句自己的拍网格 */
      const t0 = g.at[0], t1 = (L.end === undefined) ? t0 + beat * 4 : L.end;
      const u = clamp((st.t - t0) / Math.max(0.05, t1 - t0), 0, 1);
      c.fillStyle = C.line; c.fillRect(x0, barY, g.w, 1);
      c.fillStyle = C.accent; c.globalAlpha = 0.85;
      c.fillRect(x0, barY - 1, g.w * u, 2);
      c.globalAlpha = 1;
      for (let b = Math.ceil(t0 / beat) * beat; b < t1 - 1e-6; b += beat) {
        const bx = x0 + g.w * (b - t0) / (t1 - t0);
        c.fillStyle = b <= st.t ? C.paper : C.line;
        c.fillRect(bx, barY - 5, 1, 5);
      }
      MIC(c, Math.round((t1 - t0) / beat) + " 拍", x0 + g.w + 12, barY - 9,
        { size: 9, family: F.mono });
    } else if (mode === "punch" && opt.hit) {
      /* 重音字幕：句眼下一条亮粉底线，重拍起从左到右长出来 */
      let hx = g.pos[opt.hit[0]].x, hw = 0;
      for (let i = opt.hit[0]; i < opt.hit[1]; i++) hw += g.pos[i].w;
      const gp = clamp((st.t - g.at[opt.hit[0]]) / (beat * 0.25), 0, 1);
      c.fillStyle = C.accent;
      c.fillRect(hx, barY, hw * gp, 2);
      c.fillStyle = C.line;
      c.fillRect(hx, barY, hw, 1);
    }
  }
  /* 字幕调度：找到「现在该显示哪一句」，按它的情绪档渲染 */
  function subtitle(c, st) {
    const lines = lyricLines(st);
    if (!lines) return subtitlePlain(c, st);
    /* 单主角纪律：本镜已是巨字 / 封面行时，字幕退成低语档；否则用行表指定的档 */
    const force = st.shot.masthead ? "whisper" : null;
    for (let i = 0; i < lines.length; i++) {
      const L = lines[i];
      if (L.text === undefined || L.text === "") continue;
      const at = charTimes(L);
      const t0 = at[0];
      const next = lines[i + 1];
      /* 驻留到下一句首字；没有下一句就驻留到行尾；离场硬切（落拍） */
      const cut = next ? Math.max(charTimes(next)[0], next.gate || 0)
        : st.nextBeatAfter(L.end === undefined ? t0 + 1 : L.end);
      if (st.t < t0 || st.t >= cut) continue;
      drawLyricLine(c, st, L, force);
      return;
    }
  }
  /* 封面行 COVERLINE：48–96px Bold 字距 +2，进留白区，镜始后最近拍点入场。
   * 多行时逐行入场，入场时刻可写成真实人声落点（shot.coverlineAt）——
   * 于是字是「被唱出来」的，不是被定时器放出来的。显影用横向擦除（机械件不做淡入）。 */
  function coverline(c, st) {
    const s = st.shot;
    if (!s.coverline) return;
    const lines = Array.isArray(s.coverline) ? s.coverline : [s.coverline];
    const entry = st.nextBeatAfter(s.t0);
    const size = s.coverlineSize || 72;
    const lh = size * 1.32, top = H * 0.34;
    c.textAlign = "left";
    c.textBaseline = "alphabetic";
    for (let i = 0; i < lines.length; i++) {
      const at = (s.coverlineAt && s.coverlineAt[i] !== undefined)
        ? s.coverlineAt[i] : entry + i * (st.beatLen || 0.455);
      const p = (st.t - at) / (6 / 24);
      if (p <= 0) continue;
      const e = easeOutCubic(clamp(p, 0, 1));
      font(c, size, "bold", F.sans, 2);
      const w = c.measureText(lines[i]).width;
      const x = st.visual.coverlineSide === "right" ? W - 120 - w : 120;
      c.save();
      c.beginPath(); c.rect(x - 2, top + i * lh - size, w * e + 3, size * 2); c.clip();
      c.globalAlpha = clamp(p * 2.4, 0, 1);
      c.fillStyle = C.paper;
      c.fillText(lines[i], x, top + i * lh + 10 * (1 - e));
      c.restore();
      c.globalAlpha = 1;
    }
    if ("letterSpacing" in c) c.letterSpacing = "0px";
  }
  /* 巨字 MASTHEAD：整屏一词，120–200px Light，重拍硬切 */
  function masthead(c, st) {
    const s = st.shot;
    if (!s.masthead) return;
    if (st.t < st.nextBeatAfter(s.t0)) return;
    const num = /^[0-9+%.,\-]+$/.test(s.masthead);
    /* 重拍硬切 + 1 帧 104%→100% 落定（Figma 3:2） */
    const since = st.t - st.nextBeatAfter(s.t0);
    const k = since < 1 / 24 ? 1.04 - 0.04 * (since / (1 / 24)) : 1;
    font(c, 180 * k, "light", num ? F.mono : F.sans, 0);
    c.fillStyle = C.paper;
    c.textAlign = "center";
    c.textBaseline = "alphabetic";
    c.fillText(s.masthead, W / 2, H * 0.58);
    if ("letterSpacing" in c) c.letterSpacing = "0px";
  }
  /* 报幕 CALLER：Noto Serif SC 30–44px 字距 +2 */
  function caller(c, st) {
    if (!st.shot.caller) return;
    txt(c, st.shot.caller, 120, H * 0.72, { size: 40, family: F.serif, tracking: 2 });
  }
  /* 频闪微字 MASS：drop 段按 1/8 拍频闪 */
  function mass(c, st) {
    const list = st.shot.mass;
    if (!list || !list.length) return;
    const beat = st.beatLen || 0.455;
    const k = Math.floor(st.t / (beat / 8));
    for (let i = 0; i < 9; i++) {
      const x = 140 + hash(k * 3.1 + i) * 1560;
      const y = 180 + hash(k * 7.7 + i * 2.3) * 700;
      c.globalAlpha = 0.35 + 0.65 * hash(k * 11 + i * 5);
      txt(c, list[(k * 7 + i * 13) % list.length], x, y, { size: 9 + Math.floor(hash(i + k) * 5), color: C.sub, tracking: 2 });
    }
    c.globalAlpha = 1;
  }
  /* ==========================================================================
   * 歌词层 LYRIC ENGINE（2026-10-01 替换 v1 的「底部一行白字淡入」）
   *
   * 普通字幕是「一行白字，淡入淡出」。本层按**章节情绪**换排印处理：
   *   announce 念白(Intro/Outro) → 群公告条：等宽字 + 逐字打字机 + REC 闪点
   *   rant     主歌 1/2           → 左右对句 + 卡拉OK逐字点亮 + 节拍游标
   *   hype     副歌              → 「示例」印章 + 记号笔高亮（大字，chrome 让位）
   *   savage   主歌 3（最凶一段） → riso 套印错位 + 重拍抖动 + 关键词砸框
   *   quiet    Bridge（走心）     → 衬线体居中 + 下一句提前显影，不戴任何装饰
   *   praise   主歌 4（表扬段）   → 居中 + 琥珀色 + 当前词组暖光
   *
   * 时间来自 song/analysis/lines.json（tools/make_lines.py 产出的**逐字级**时间），
   * 所以字是"唱到哪亮到哪"，不是按定时器闪。
   * ========================================================================== */
  const EMO = ["示例"];
  const HOOK = "示例";
  const _mwCache = new Map();
  function measure(c, s, size, weight, family, tracking) {
    const key = size + "|" + (weight || "normal") + "|" + (family || F.sans) + "|" + (tracking || 0) + "|" + s;
    let w = _mwCache.get(key);
    if (w === undefined) { font(c, size, weight, family, tracking); w = c.measureText(s).width; _mwCache.set(key, w); }
    return w;
  }
  /* 一行歌词在某时刻的状态：逐字 past / cur / future */
  function lineState(st) {
    const ls = st.lyricLines;
    if (!ls || !ls.length) return null;
    const t = st.t, LEAD = 0.15, HOLD = 1.2;
    let idx = -1, line = null;
    for (let i = 0; i < ls.length; i++) {
      const a = ls[i].t0 - LEAD;
      const b = Math.min(ls[i].t1 + HOLD, ls[i + 1] ? ls[i + 1].t0 : 1e9);
      if (t >= a && t < b) { idx = i; line = ls[i]; break; }
    }
    if (!line) return null;
    const chars = line.chars || [];
    const n = chars.length;
    let curIdx = -1;
    for (let k = 0; k < n; k++) if (t >= chars[k].t && curIdx < 0) curIdx = k;
    const prog = n ? clamp((t - chars[0].t) / Math.max(0.001, chars[n - 1].e - chars[0].t), 0, 1) : 0;
    const dim = line.mood === "hype" ? 1 : (line.mood === "announce" ? 0 : 0.55);
    return { i: idx, line: line, next: ls[idx + 1] || null, curIdx: curIdx, prog: prog, dim: dim };
  }
  /* 逐字上色：past 实心 / future 次级 / 当前字强调色。返回每个字的位置。 */
  function drawChars(c, st, chars, x, base, o) {
    const size = o.size, weight = o.weight, family = o.family, tracking = o.tracking || 0;
    const out = [];
    let cx = x;
    for (let k = 0; k < chars.length; k++) {
      const ch = chars[k];
      const w = measure(c, ch.c, size, weight, family, tracking);
      const past = st.t >= ch.e, cur = st.t >= ch.t && !past;
      font(c, size, weight, family, tracking);
      c.textAlign = "left";
      c.textBaseline = "alphabetic";
      if (o.marker) {
        if (past || cur) {
          c.fillStyle = o.marker;
          c.globalAlpha = ALPHA_CTX * (past ? 0.9 : 0.55 + 0.45 * o.pulse);
          c.fillRect(cx - 2, base - size * 0.92, w + 4, size * 1.16);
        }
        c.fillStyle = past || cur ? C.ink : C.paper;
        c.globalAlpha = ALPHA_CTX * (past || cur ? 1 : 0.8);
      } else {
        if (o.skipFuture && !past && !cur) { cx += w + tracking; out.push({ x: cx - w - tracking, w: w, ch: ch, past: past, cur: cur }); continue; }
        c.fillStyle = cur ? (o.curColor || C.accent) : (past ? (o.pastColor || C.paper) : (o.futureColor || C.sub));
        c.globalAlpha = ALPHA_CTX * (past || cur ? 1 : (o.futureAlpha === undefined ? 0.72 : o.futureAlpha));
        if (o.glow && cur) { c.shadowColor = o.curColor || C.accent; c.shadowBlur = o.glow; }
      }
      c.fillText(ch.c, cx, base);
      c.shadowBlur = 0;
      c.globalAlpha = 1;
      out.push({ x: cx, w: w, ch: ch, past: past, cur: cur });
      cx += w + tracking;
    }
    return { cells: out, width: cx - x - tracking };
  }
  const _scrim = (c, top, bottom, a) => {
    const g = c.createLinearGradient(0, top, 0, bottom);
    g.addColorStop(0, "rgba(11,13,16,0)");
    g.addColorStop(0.5, "rgba(11,13,16," + (a * 0.55).toFixed(3) + ")");
    g.addColorStop(1, "rgba(11,13,16," + a.toFixed(3) + ")");
    c.fillStyle = g;
    c.fillRect(0, top, W, bottom - top);
  };
  const NORM_RE = /[\s\u3000·、，。！？；：""''「」（）()\[\]…—\-]+/g;
  const nlen = s => s.replace(NORM_RE, "").length;
  /* 把一行切成若干显示段，并**按位置**切出每段的逐字时间。
   * 不能按"字符是否出现过"来 filter——"示例"这种重复字会串位。 */
  function sliceByParts(chars, parts) {
    const out = [];
    let i = 0;
    parts.forEach(function (p) {
      const n = nlen(p);
      out.push({ text: p, chars: chars.slice(i, i + n) });
      i += n;
    });
    const last = out[out.length - 1];
    if (last && i < chars.length) last.chars = chars.slice(chars.length - nlen(last.text));
    return out;
  }
  /* 一行按空格对折成上下/左右两半（副歌/主歌的对句结构就是这么写的） */
  function halfParts(text) {
    const parts = text.trim().split(/\s+/);
    if (parts.length < 2) return [text];
    const mid = Math.ceil(parts.length / 2);
    const a = parts.slice(0, mid).join("  "), b = parts.slice(mid).join("  ");
    return [a, b];
  }
  /* 找不到 lines.json 时的兜底：退回 v1 的段落样式（保证永远有字幕） */
  function fallbackSubtitle(c, st) { return subtitle(c, st); }
  /* ---------- ① announce：群公告条 ---------- */
  function drawAnnounce(c, st, S) {
    const line = S.line, y0 = 916, y1 = 988, x0 = 120, x1 = 1800;
    c.fillStyle = C.ink; c.globalAlpha = 0.76; c.fillRect(x0, y0, x1 - x0, y1 - y0); c.globalAlpha = 1;
    hair(c, x0, y0, x1 - x0, 1, C.line);
    hair(c, x0, y1, x1 - x0, 1, C.line);
    /* 左：REC 闪点 + 「群公告」标签 */
    const blink = Math.floor(st.t / ((st.beatLen || 0.455) / 2)) % 2 === 0;
    c.fillStyle = C.accent;
    c.globalAlpha = blink ? 0.95 : 0.18;
    c.beginPath(); c.arc(146, 952, 4.5, 0, Math.PI * 2); c.fill();
    c.globalAlpha = 1;
    txt(c, "群公告", 160, 936, { size: 13, weight: "bold", family: F.mono, color: C.accent, tracking: 3 });
    txt(c, "GROUP NOTICE", 160, 958, { size: 8, family: F.mono, color: C.sub, tracking: 2 });
    hair(c, 268, y0 + 16, 1, y1 - y0 - 32, C.line);
    /* 正文：等宽 + 逐字打字机（每个字按它自己的发声时刻出现） */
    const size = 27, base = 966, family = F.mono, tracking = 3;
    let cx = 296, shown = -1;
    for (let k = 0; k < line.chars.length; k++) {
      const ch = line.chars[k];
      if (st.t < ch.t) break;
      const w = measure(c, ch.c, size, "normal", family, tracking);
      font(c, size, "normal", family, tracking);
      c.textAlign = "left"; c.textBaseline = "alphabetic";
      c.fillStyle = C.paper;
      c.globalAlpha = ALPHA_CTX * clamp((st.t - ch.t) / (2 / 24), 0, 1);
      c.fillText(ch.c, cx, base);
      c.globalAlpha = 1;
      if (st.t < ch.e) {
        c.fillStyle = C.accent;
        c.globalAlpha = ALPHA_CTX * 0.9;
        c.fillRect(cx - 1, base + 5, w + 2, 2);
        c.globalAlpha = 1;
      }
      cx += w + tracking; shown = k;
    }
    /* 光标方块：一直闪，像真的在收字 */
    if (shown < line.chars.length - 1) {
      c.fillStyle = C.accent;
      c.globalAlpha = ALPHA_CTX * (blink ? 0.85 : 0.15);
      c.fillRect(cx + 2, base - size * 0.82, size * 0.55, size * 0.98);
      c.globalAlpha = 1;
    }
    /* 右：真实信号读数（行号 / 总行数） */
    const total = (st.lyricLines || []).length;
    txt(c, String(S.i + 1).padStart(2, "0") + " / " + String(total).padStart(2, "0"),
      x1 - 24, 936, { size: 13, family: F.mono, color: C.sub, tracking: 2, align: "right" });
    txt(c, "SIGNAL  ▮▮▮▯", x1 - 24, 958, { size: 8, family: F.mono, color: C.sub, tracking: 2, align: "right" });
  }
  /* ---------- ② rant：左右对句 + 逐字点亮 ---------- */
  function drawRant(c, st, S, o) {
    const line = S.line, em = o.emph !== false;
    const size = o.size || 46, base = 948, tracking = 2, weight = o.weight || "bold";
    const e = easeOutCubic(clamp((st.t - (line.t0 - 0.15)) / ((st.beatLen || 0.455) / 8), 0, 1));
    const parts = o.split === false ? [line.text] : halfParts(line.text);
    const slices = sliceByParts(line.chars, parts);
    c.globalAlpha = ALPHA_CTX * e;
    const dy = 14 * (1 - e);
    /* 左游标：拍点上闪 */
    const pulse = st.ck ? st.ck.pulse : 0;
    c.fillStyle = o.curColor || C.accent;
    c.globalAlpha = ALPHA_CTX * (0.5 + 0.5 * pulse);
    c.fillRect(132, base - size * 0.86 + dy, 4, size * 1.02);
    c.globalAlpha = 1;
    /* 主文本：按半句左右分置（左半左对齐 152，右半右对齐 1780），逐字点亮 */
    const draw = (sl, x, align) => {
      const wAll = measure(c, sl.text, size, weight, F.sans, tracking);
      const x0 = align === "right" ? x - wAll : x;
      return drawChars(c, st, sl.chars, x0, base + dy, {
        size: size, weight: weight, family: F.sans, tracking: tracking,
        curColor: o.curColor || C.accent, futureAlpha: 0.68,
      });
    };
    if (slices.length > 1) { draw(slices[0], 152, "left"); draw(slices[1], 1780, "right"); }
    else draw(slices[0], 152, "left");
    c.globalAlpha = 1;
    /* 进行度细线：唱到哪儿，线到哪儿 */
    const y = base + 20 + dy;
    hair(c, 152, y, 1628, 1, C.line);
    c.fillStyle = o.curColor || C.accent;
    c.globalAlpha = ALPHA_CTX * 0.9;
    c.fillRect(152, y, 1628 * S.prog, 1.5);
    c.globalAlpha = 1;
  }
  /* ---------- ③ hype：印章 + 记号笔 ---------- */
  function drawHype(c, st, S) {
    const line = S.line;
    let size = 68, hookSize = 56;
    const base = 938, tracking = 1, hookTracking = 3, boxPad = 30, boxH = 94, gap = 30;
    const e = easeOutCubic(clamp((st.t - (line.t0 - 0.15)) / (2 / 24), 0, 1));
    const dy = 18 * (1 - e);
    const parts = line.text.trim().split(/\s+/);
    const slices = sliceByParts(line.chars, parts);
    /* 先量宽度，超宽就整体缩字号（不缩放坐标，字形才不会被拉变形） */
    const widths = () => slices.map(function (sl) {
      return sl.text === HOOK
        ? measure(c, sl.text, hookSize, "black", F.sans, hookTracking) + boxPad
        : measure(c, sl.text, size, "bold", F.sans, tracking);
    });
    let ws = widths();
    let total = ws.reduce((a, b) => a + b, 0) + gap * (slices.length - 1);
    if (total > 1740) {
      const k = 1740 / total;
      size *= k; hookSize *= k;
      ws = widths();
      total = ws.reduce((a, b) => a + b, 0) + gap * (slices.length - 1);
    }
    let x = (W - total) / 2;
    c.globalAlpha = ALPHA_CTX;
    slices.forEach(function (sl, ti) {
      const tk = sl.text, tkChars = sl.chars;
      const tkStart = tkChars.length ? tkChars[0].t : line.t0;
      if (tk === HOOK) {
        /* 印章：从第一个字起 2 帧内从 1.14 砸到 1.0，落定后带一点机械余震 */
        const p = clamp((st.t - tkStart) / (2 / 24), 0, 1);
        const beat = clamp((st.t - tkStart) / 0.12, 0, 1);
        const sc = (1 + 0.14 * (1 - easeOutCubic(p))) * (0.985 + 0.03 * (1 - beat) * Math.cos(st.t * 60));
        const textW = measure(c, tk, hookSize, "black", F.sans, hookTracking);
        const bw = textW + boxPad, bh = boxH;
        c.save();
        c.translate(x + bw / 2, base - boxH * 0.42 + dy);
        c.rotate(-0.105);
        c.scale(sc, sc);
        c.fillStyle = C.accent; c.globalAlpha = ALPHA_CTX * 0.94;
        c.fillRect(-bw / 2, -bh / 2, bw, bh);
        /* 网点：印章的 riso 底纹，确定性排布 */
        c.fillStyle = C.ink; c.globalAlpha = ALPHA_CTX * 0.16;
        for (let yy = -bh / 2 + 5; yy < bh / 2 - 2; yy += 7)
          for (let xx = -bw / 2 + 5; xx < bw / 2 - 2; xx += 7) c.fillRect(xx, yy, 2, 2);
        c.globalAlpha = ALPHA_CTX;
        c.strokeStyle = C.ink; c.lineWidth = 3;
        c.strokeRect(-bw / 2, -bh / 2, bw, bh);
        /* 字画在同一个旋转/缩放坐标系里，章和字才是一体的 */
        drawChars(c, st, tkChars, -textW / 2, hookSize * 0.35, {
          size: hookSize, weight: "black", family: F.sans, tracking: hookTracking,
          curColor: C.ink, pastColor: C.ink, futureColor: C.ink, futureAlpha: 0.42,
        });
        c.restore();
        c.globalAlpha = ALPHA_CTX;
      } else {
        drawChars(c, st, tkChars, x, base + dy, {
          size: size, weight: "bold", family: F.sans, tracking: tracking,
          marker: C.accent, curColor: C.paper, futureAlpha: 0.86, pulse: 1,
        });
      }
      x += ws[ti] + gap;
    });
    c.globalAlpha = 1;
  }
  /* ---------- ④ savage：套印错位 + 重拍抖动 ---------- */
  function drawSavage(c, st, S) {
    const line = S.line, size = 52, base = 946, tracking = 1;
    const e = easeOutCubic(clamp((st.t - (line.t0 - 0.15)) / (1 / 24), 0, 1));
    /* 重拍抖动：确定性（由节拍序号取 hash），不是随机数 */
    const bi = st.ck ? st.ck.idx : 0;
    const since = st.ck ? st.ck.since : 1;
    const jit = since < 0.08 ? (hash(bi * 1.7) - 0.5) * 4 : 0;
    const x0 = 152 + jit, dy = 16 * (1 - e);
    const wAll = measure(c, line.text, size, "black", F.sans, tracking);
    /* riso 套印：品红 / 琥珀两层错开 3px，用 screen 叠（亮部相加、暗部不吃底），
     * 再压一层实色正文——边缘漏出彩边，是"印刷没套准"，不是发光特效。 */
    c.save();
    c.globalCompositeOperation = "screen";
    [[-3, C.accent, 0.55], [3, C.amber, 0.5]].forEach(function (L) {
      drawChars(c, st, line.chars, x0 + L[0], base + dy, {
        size: size, weight: "black", family: F.sans, tracking: tracking,
        curColor: L[1], pastColor: L[1], futureColor: L[1], futureAlpha: L[2],
        skipFuture: true,
      });
    });
    c.restore();
    drawChars(c, st, line.chars, x0, base + dy, {
      size: size, weight: "black", family: F.sans, tracking: tracking,
      curColor: C.accent, futureAlpha: 0.62,
    });
    c.globalAlpha = 1;
    /* 关键词砸框：命中 EMO 的词，唱到它的瞬间落一个方框 */
    EMO.forEach(function (kw) {
      const at = line.text.indexOf(kw);
      if (at < 0) return;
      const pre = normalize_s(line.text.slice(0, at));
      const n = normalize_s(kw).length;
      const hit = line.chars[pre.length];
      if (!hit || st.t < hit.t) return;
      const p = clamp((st.t - hit.t) / (3 / 24), 0, 1);
      const xa = x0 + measure(c, normalize_s(line.text.slice(0, at)), size, "black", F.sans, tracking) + tracking * pre.length;
      const wa = measure(c, normalize_s(kw), size, "black", F.sans, tracking) + tracking * (n - 1);
      c.strokeStyle = C.accent; c.lineWidth = 2;
      c.globalAlpha = ALPHA_CTX * (0.9 - 0.5 * (1 - p));
      c.strokeRect(xa - 6 - 40 * (1 - p), base + dy - size * 0.86 - 6, wa + 12 + 80 * (1 - p), size * 1.06 + 12);
      c.globalAlpha = 1;
    });
    void wAll;
  }
  const normalize_s = s => s.replace(/\s+/g, "");
  /* ---------- ⑤ quiet：衬线体，只留呼吸 ---------- */
  function drawQuiet(c, st, S) {
    const line = S.line;
    const p = clamp((st.t - (line.t0 - 0.15)) / 0.5, 0, 1);
    const e = easeOutCubic(p);
    c.globalAlpha = ALPHA_CTX * e;
    const base = 934, dy = 10 * (1 - e);
    const size = 44, tracking = 5;
    drawChars(c, st, line.chars, (W - measure(c, line.text, size, "normal", F.serif, tracking)) / 2, base + dy, {
      size: size, weight: "normal", family: F.serif, tracking: tracking,
      curColor: C.paper, pastColor: C.paper, futureColor: C.sub, futureAlpha: 0.5,
    });
    /* 下一句提前显影：只给这一种情绪（沉思感来自"看得见下一句"） */
    if (S.next && S.next.mood === "quiet") {
      const np = clamp((st.t - (S.next.t0 - 1.15)) / 0.6, 0, 1);
      if (np > 0) {
        const nsize = 24;
        c.globalAlpha = ALPHA_CTX * 0.34 * np;
        font(c, nsize, "normal", F.serif, 3);
        c.textAlign = "center"; c.textBaseline = "alphabetic";
        c.fillStyle = C.sub;
        c.fillText(S.next.text, W / 2, 996);
        c.globalAlpha = 1;
      }
    }
    c.globalAlpha = 1;
  }
  /* ---------- ⑥ praise：居中琥珀色 + 暖光 ---------- */
  function drawPraise(c, st, S) {
    const line = S.line, size = 48, tracking = 2;
    const e = easeOutCubic(clamp((st.t - (line.t0 - 0.15)) / ((st.beatLen || 0.455) / 8), 0, 1));
    const dy = 12 * (1 - e);
    const wAll = measure(c, line.text, size, "bold", F.sans, tracking);
    const x0 = Math.max(140, (W - wAll) / 2);
    c.globalAlpha = ALPHA_CTX * e;
    drawChars(c, st, line.chars, x0, 942 + dy, {
      size: size, weight: "bold", family: F.sans, tracking: tracking,
      curColor: C.amber, futureAlpha: 0.7, glow: 16,
    });
    /* 暖线跟着唱走：praise 段唯一的装饰，长度就是进度 */
    hair(c, x0, 962 + dy, wAll, 1, C.line);
    c.fillStyle = C.amber;
    c.globalAlpha = ALPHA_CTX * 0.95;
    c.fillRect(x0, 961 + dy, wAll * S.prog, 3);
    c.globalAlpha = 1;
  }
  /* ==========================================================================
   * 情绪字幕 v3（2026-10-01）—— 字幕先要被设计成「一件东西」，而不是一条说明。
   *
   * v1 是「底部一行白字淡入」；v2 按情绪换排印，但绝大多数档位仍然落在下三分之一
   * 同一条横带上——观众读到的还是「字幕」。v3 的口径：
   *   **先问「这句话在物理世界里是什么东西」，再把它画成那个东西。**
   *
   *   宣言 placard  → 一块印出来的宣言牌。字随人声「上墨」：唱到的字是实心纸白，
   *                   还没唱到的是网点印版（半调是这套稿子的印刷母语），
   *                   强调词亮粉，且唱到它的那一刻从词首向词尾擦出一条亮粉底线。
   *   计数 tally    → 一块翻牌计数器。数字按真实拍点跳，落点 = 人声唱到那个数
   *                   （「刷到九十九加」→ 00…99 在「加」上落定，+ 随即盖章）。
   *   报幕 caller   → Figma 1:32 的第三个声部：衬线、字距 +2、面无表情、句号收尾。
   *                   硬切（0 帧渐变），一句一行，句号是全片唯一的强调色。
   *   （划改 strike / 回声 echo / 量尺 measure / 重音 punch / 低语 whisper 沿用 v2，
   *     它们是稿子 5:347 / 5:354 / 3:2 的原生字处理。）
   *
   * 落位纪律：v3 的字幕搬进画面**留白区**（左侧空街 / 右上留白），不再与翻牌长条、
   * ticker、意义层卡片抢下三分之一；一屏只有一个主角。
   * 落点纪律（Figma 3:2）：逐字上墨照人声；换值落拍；离场硬切；永不提前。
   * ======================================================================== */
  const _WSP = /[\s\u3000]+/g;
  function lstrip(s) { return String(s === undefined || s === null ? "" : s).replace(_WSP, ""); }
  /* 一行 → 逐字 [{c,t,e}]
   * 优先级：chars[]（lines.json 的真·逐字时间）> at[]（行表手填）> 按行区间均分 */
  function toChars(L) {
    const text = lstrip(L.text);
    const cs = text.split("");
    if (L.chars && L.chars.length) {
      const src = L.chars.filter(function (k) { return lstrip(k.c).length > 0; });
      if (src.length === cs.length) {
        return cs.map(function (c, i) {
          const k = src[i];
          return { c: c, t: k.t, e: (k.e === undefined ? k.t + 0.2 : k.e) };
        });
      }
      if (src.length > 1) {   // 版本对不上：只取首尾，中间按字数摊——不硬凑
        const a = src[0].t, b = src[src.length - 1].e === undefined ? src[src.length - 1].t : src[src.length - 1].e;
        return cs.map(function (c, i) {
          return { c: c, t: a + (b - a) * i / cs.length, e: a + (b - a) * (i + 1) / cs.length };
        });
      }
    }
    if (L.at && L.at.length === cs.length) {
      const at = L.at;
      return cs.map(function (c, i) {
        return {
          c: c, t: at[i],
          e: (i + 1 < at.length) ? at[i + 1] : (L.end === undefined ? at[i] + 0.25 : L.end),
        };
      });
    }
    const a = L.start !== undefined ? L.start : (L.t0 !== undefined ? L.t0 : 0);
    const b = L.end !== undefined ? L.end : (L.t1 !== undefined ? L.t1 : a + 1);
    return cs.map(function (c, i) {
      return { c: c, t: a + (b - a) * i / cs.length, e: a + (b - a) * (i + 1) / cs.length };
    });
  }
  /* 行表 → 计划（每行的逐字时间 + 下一行的起点就是本行的离场点） */
  function planLines(st) {
    const cfg = st.visual && st.visual.lyrics;
    const src = (cfg && cfg.lines && cfg.lines.length) ? cfg.lines : st.lyricLines;
    if (!src || !src.length) return null;
    const out = [];
    for (let i = 0; i < src.length; i++) {
      const L = src[i], text = lstrip(L.text);
      if (!text) continue;
      out.push({
        L: L, text: text, chars: toChars(L),
        style: L.style || null, mood: L.mood || null, next: null,
      });
    }
    if (!out.length) return null;
    for (let i = 0; i < out.length; i++) out[i].next = out[i + 1] || null;
    return out;
  }
  function lineEnd(P, st) {
    if (P.L.cutAt !== undefined) return P.L.cutAt;   // 显式离场点（仍应落在拍上）
    if (P.next) return P.next.chars[0].t;
    const L = P.L, last = P.chars[P.chars.length - 1];
    const hold = (st.visual && st.visual.lyricHold !== undefined) ? st.visual.lyricHold : 1.0;
    const end = (L.end === undefined) ? last.e : Math.max(L.end, last.e);
    return end + hold;
  }
  /* 当前该显示哪一行（离场 = 下一行第一个字的那一刻，硬切，落拍） */
  function activeLine(st, plan) {
    for (let i = 0; i < plan.length; i++) {
      const a = plan[i].chars[0].t;
      if (st.t < a) continue;
      if (st.t < lineEnd(plan[i], st)) return { i: i, n: plan.length, line: plan[i], t0: a };
    }
    return null;
  }
  /* 分行：rows 显式给 > 原文按空格对折 > 整句一行 */
  function rowsSplit(P) {
    const L = P.L;
    let rows = (L.rows && L.rows.length) ? L.rows.map(lstrip)
      : String(L.text || "").split(/\s+/).map(lstrip).filter(Boolean);
    if (rows.length < 2) return [{ text: P.text, chars: P.chars }];
    if (rows.join("").length !== P.text.length) return [{ text: P.text, chars: P.chars }];
    let ci = 0;
    return rows.map(function (r) {
      const a = P.chars.slice(ci, ci + r.length); ci += r.length;
      return { text: r, chars: a };
    });
  }
  /* 半调网点图案：这套稿子的印刷母语（图例 2:483 第 7 项）。
   * 用来画「还没上墨的印版」——不是把字调淡，是换一种材质。 */
  const _dotCache = new Map();
  function dotPat(c, color, step, r) {
    const key = color + "|" + step + "|" + r;
    let p = _dotCache.get(key);
    if (p) return p;
    const cv = document.createElement("canvas");
    cv.width = step; cv.height = step;
    const g = cv.getContext("2d");
    g.fillStyle = color;
    g.beginPath(); g.arc(step / 2 + 0.5, step / 2 + 0.5, r, 0, Math.PI * 2); g.fill();
    p = c.createPattern(cv, "repeat");
    _dotCache.set(key, p);
    return p;
  }
  /* 强调词在整句里的字区间（按显示文本定位，不按「字是否出现过」） */
  function markRanges(P) {
    const marks = P.L.marks || [];
    const out = [];
    marks.forEach(function (m) {
      const s = lstrip(m);
      if (!s) return;
      const at = P.text.indexOf(s);
      if (at < 0) return;
      out.push([at, at + s.length, P.chars[at]]);
    });
    return out;
  }
  /* ==========================================================================
   * v4 · 全片编排（2026-10-01）—— 从「一行字幕」升级成「一件东西 + 一个落位」
   *
   * 底片 = 200.3s 完整剪辑（out/base-noJS-v2.mp4），22 个章节：
   * Intro 2 行 / 主歌 24 行 / 副歌 24 行 / savage 8 行 / Bridge 4 行 / Outro 2 行。
   * 64 行全走同一档位必然读成「字幕」。所以：
   *   ① 每一行在编排表里自己声明 style（这句话在物理世界里是什么东西）
   *      和 zone（它落在画面哪个留白区）；
   *   ② 装置按物理属性动：印章会砸、翻牌会翻、账本会累加、量尺会走格、
   *      终端会打字、划改会划掉、名单会一个个落座；
   *   ③ 入场一律落拍（1/8 拍 = 3 帧 linear 滑入，机械件不做弹性）；
   *      逐字上墨一律照人声（Figma 3:2 红线「永不提前」）；离场一律硬切；
   *   ④ 落位随镜头走——同一句话不再永远赖在下三分之一那一条横带上。
   * ======================================================================== */

  /* 落位区：chrome 已占四角 / 左标尺 x<50 / 翻牌长条 y788-874 / ticker y>1024。
   * 可读带 = y ∈ [170, 780]，这九个矩形就是本片的版面格。 */
  const ZONES = {
    TL: { x: 120, y: 196, w: 810, h: 210, align: "left" },
    TC: { x: 555, y: 186, w: 810, h: 210, align: "center" },
    TR: { x: 990, y: 196, w: 810, h: 210, align: "right" },
    ML: { x: 120, y: 420, w: 810, h: 210, align: "left" },
    MC: { x: 555, y: 410, w: 810, h: 220, align: "center" },
    MR: { x: 990, y: 420, w: 810, h: 210, align: "right" },
    LL: { x: 120, y: 546, w: 820, h: 200, align: "left" },
    LR: { x: 980, y: 546, w: 820, h: 200, align: "right" },
    WIDE: { x: 150, y: 292, w: 1620, h: 180, align: "left" },
  };
  function zoneRect(L) { return ZONES[L.zone] || ZONES.ML; }
  /* 落位区内水平锚点：块宽 w 时它的左边界 */
  function anchorX(Z, w) {
    if (Z.align === "right") return Z.x + Z.w - w;
    if (Z.align === "center") return Z.x + (Z.w - w) / 2;
    return Z.x;
  }
  /* 入场相位：1/8 拍 = 3 帧，linear（Figma 3:2「机械件不做弹性」）。
   * 方向由落位区决定——左侧的字从左进来、右侧的从右进来，于是同一句话挪到
   * 画面另一侧时是「走过去」的，不是瞬移。 */
  function zoneEnter(st, Z, gate) {
    const p = clamp((st.t - gate) / (3 / 24), 0, 1);
    return {
      p: p,
      dx: Z.align === "right" ? 34 * (1 - p) : Z.align === "center" ? 0 : -34 * (1 - p),
      dy: Z.align === "center" ? -14 * (1 - p) : 0,
    };
  }
  function gateAt(P, st) {
    const g = P.L && P.L.gate;
    return (g === undefined) ? (P.chars[0] ? P.chars[0].t : st.t) : g;
  }
  /* 显示串逐字符排布：空格不占时间槽（人声里没有空格），只占宽度。
   * cells[i] = { c, x, w, slot }，slot = lines.json 那个字的 {t,e}。 */
  function layoutRow(c, shown, chars, size, weight, family, tracking) {
    const cells = [];
    let x = 0, i = 0;
    for (let k = 0; k < shown.length; k++) {
      const dc = shown[k];
      const w = measure(c, dc, size, weight, family, tracking);
      if (/\s/.test(dc)) { cells.push({ c: dc, x: x, w: w, slot: null }); x += w + tracking; continue; }
      cells.push({ c: dc, x: x, w: w, slot: chars[i] || null, i: i });
      i++;
      x += w + tracking;
    }
    return { cells: cells, width: Math.max(0, x - tracking), used: i };
  }
  function rowWidth(cells) {
    let w = 0;
    cells.forEach(function (g) { w = Math.max(w, g.x + g.w); });
    return w;
  }
  /* 逐字上墨：past 实心 / cur 强调色 / future 印版网点（不是「调淡」，是换材质）。 */
  function paintRow(c, cells, size, weight, family, st, o) {
    o = o || {};
    const dot = o.ghost === false ? null : dotPat(c, C.sub, 5, 1.7);
    const marks = o.marks || [];
    font(c, size, weight, family, 0);
    c.textAlign = "left";
    c.textBaseline = "alphabetic";
    cells.forEach(function (g) {
      if (g.slot === null) return;
      const ch = g.slot;
      const past = st.t >= ch.e, cur = st.t >= ch.t && !past;
      const isM = marks.some(function (m) { return g.i >= m[0] && g.i < m[1]; });
      if (isM) {
        c.globalAlpha = (past || cur) ? 1 : (o.ghostAlpha === undefined ? 0.34 : o.ghostAlpha);
        c.fillStyle = C.accent;
      } else if (past) {
        c.globalAlpha = 1; c.fillStyle = o.past || C.paper;
      } else if (cur) {
        c.globalAlpha = 1; c.fillStyle = o.cur || C.accent;
      } else {
        if (!dot) return;
        c.globalAlpha = o.ghostAlpha === undefined ? 0.34 : o.ghostAlpha;
        c.fillStyle = dot;
      }
      c.fillText(g.c, g.x, 0);
      c.globalAlpha = 1;
    });
    if ("letterSpacing" in c) c.letterSpacing = "0px";
  }
  /* 板面：底片很亮时（蓝天的 s050 一类）才铺一条软沉降带，
   * 目的是「字能读」而不是「给字加底板」——暗镜一律不铺，保持干净渲染。 */
  function softBand(c, Z, a) {
    const g = c.createLinearGradient(0, Z.y - 26, 0, Z.y + Z.h + 26);
    g.addColorStop(0, "rgba(11,13,16,0)");
    g.addColorStop(0.32, "rgba(11,13,16," + (a * 0.92).toFixed(3) + ")");
    g.addColorStop(0.68, "rgba(11,13,16," + (a * 0.92).toFixed(3) + ")");
    g.addColorStop(1, "rgba(11,13,16,0)");
    c.fillStyle = g;
    c.fillRect(Z.x - 60, Z.y - 26, Z.w + 120, Z.h + 52);
  }
  function needBand(st) { return ((st.shot && st.shot.lum) || 0.1) >= 0.28; }
  /* 一行拆成显示行（显式 rows 优先），并按位置把 P.chars 切片 */
  function rowsOf(P, rows) {
    if (!rows || rows.length < 2) return [{ text: P.text, chars: P.chars }];
    if (nlen(rows.join("")) !== P.text.length) return [{ text: P.text, chars: P.chars }];
    let ci = 0;
    return rows.map(function (r) {
      const n = nlen(r);
      const a = P.chars.slice(ci, ci + n); ci += n;
      return { text: r, chars: a };
    });
  }
  /* 整块（多行）排版：先量再定字号，超宽就整块缩，字号不缩放坐标 */
  function blockRows(c, rows, maxW, maxSize, weight, family, tracking) {
    let size = maxSize;
    for (let k = 0; k < 2; k++) {
      let over = 0;
      rows.forEach(function (r) {
        over = Math.max(over, layoutRow(c, r.text, r.chars, size, weight, family, tracking).width);
      });
      if (over <= maxW || size <= 13) break;
      size *= maxW / over;
    }
    const laid = rows.map(function (r) {
      return layoutRow(c, r.text, r.chars, size, weight, family, tracking);
    });
    const w = Math.max.apply(null, laid.map(function (l) { return l.width; }));
    return { size: size, laid: laid, w: w };
  }
  /* 本行的发声进度（第一个字到最后一个字） */
  function progOf(st, P) {
    const a = P.chars[0] ? P.chars[0].t : st.t;
    const b = P.chars[P.chars.length - 1] ? P.chars[P.chars.length - 1].e : a + 1;
    return clamp((st.t - a) / Math.max(0.001, b - a), 0, 1);
  }
  /* 画一整块（多行）到落位区，返回每行的 x/base 以便叠加装置 */
  function paintBlock(c, st, Z, B, o) {
    const lh = o.lh === undefined ? B.size * 1.30 : o.lh;
    const blockH = lh * (B.laid.length - 1) + B.size * 1.10;
    const top = Z.y + (Z.h - blockH) / 2;
    const out = [];
    B.laid.forEach(function (l, ri) {
      const x0 = anchorX(Z, l.width) + o.dx;
      const base = top + B.size * 0.86 + ri * lh + o.dy;
      c.save();
      c.translate(x0, base);
      paintRow(c, l.cells, B.size, o.weight || "bold", o.family || F.sans, st, o);
      c.restore();
      out.push({ x: x0, base: base, width: l.width, cells: l.cells });
    });
    return { lines: out, top: top, blockH: blockH, lh: lh };
  }
  /* 高亮块（底色 + 墨字）——印章 / 重击版共用的一张「版」 */
  /* ---------- 章节事件：换章节的那一拍，画面横着撕开一道线 ---------- */
  function sectionEvent(c, st) {
    const s = st.shot, all = st.shots;
    if (!s || !s.section || !all) return;
    const prev = all[st.shotIndex - 1];
    if (prev && prev.section === s.section) return;     // 只在真的换章节时发生
    const at = st.entryBeat === undefined ? st.nextBeatAfter(s.t0) : st.entryBeat;
    const dt = st.t - at;
    if (dt < 0 || dt > 0.34) return;
    const p = easeOutCubic(clamp(dt / 0.16, 0, 1));
    const w = W * p, y = 172;
    c.fillStyle = C.accent;
    c.fillRect((W - w) / 2, y, w, 2);
    if (dt > 0.16) {
      c.globalAlpha = (1 - clamp((dt - 0.16) / 0.18, 0, 1)) * 0.9;
      txt(c, String(s.section).toUpperCase() + " · 章节", 76, y - 32,
        { size: 11, family: F.mono, color: C.accent, tracking: 5 });
      c.globalAlpha = 1;
    }
  }
  function plate(c, x, y, w, h, bg, rot) {
    c.save();
    c.translate(x + w / 2, y + h / 2);
    if (rot) c.rotate(rot);
    c.fillStyle = bg;
    c.fillRect(-w / 2, -h / 2, w, h);
    c.restore();
  }
  /* ---------- ① 宣言牌 PLACARD ---------- */
  function mdPlacard(c, st, P, A) {
    const L = P.L, Z = zoneRect(L);
    const marks = markRanges(P);
    const y0 = L.y === undefined ? Z.y : L.y;
    const tracking = L.tracking === undefined ? 1 : L.tracking;
    const RS = rowsSplit(P);
    const maxW = L.maxW || Z.w;
    let size = L.size || 72;
    let wid = RS.map(function (r) { return measure(c, r.text, size, "black", F.sans, tracking); });
    const w0 = Math.max.apply(null, wid);
    if (w0 > maxW) {
      size *= maxW / w0;
      wid = RS.map(function (r) { return measure(c, r.text, size, "black", F.sans, tracking); });
    }
    const wMax = Math.max.apply(null, wid);
    /* 落位区决定水平锚点：右半边的宣言牌要右对齐，否则牌框会飘在画面中间 */
    const x0 = L.x === undefined ? anchorX(Z, wMax) : L.x;
    const lh = size * 1.30;
    const top = y0;
    const blockH = lh * (RS.length - 1) + size * 1.30;
    /* 重拍冲击：整块推近 1.02，一帧内回落（印刷品被按在桌上的一下） */
    const punch = 1 + 0.02 * (st.ck ? st.ck.down : 0);
    const cxc = x0 + wMax / 2, cyc = top + blockH / 2;
    /* 牌框：1px 细线（上下） + 左上角对位十字（印刷对位记号，本身不动） */
    hair(c, x0 - 26, top - 20, wMax + 52, 1, C.line);
    hair(c, x0 - 26, top + blockH + 18, wMax + 52, 1, C.line);
    c.fillStyle = C.sub;
    c.fillRect(x0 - 35, top - 21, 18, 1);
    c.fillRect(x0 - 27, top - 29, 1, 18);
    if (L.label) txt(c, L.label, x0 - 26, top - 56, { size: 9, family: F.mono, color: C.sub, tracking: 3 });
    if (L.foot) txt(c, L.foot, x0 + wMax + 26, top - 56, { size: 9, family: F.mono, color: C.sub, tracking: 3, align: "right" });
    /* 逐字上墨：唱到的字实心，未唱到的字是网点印版 */
    const dot = L.ghost === false ? null : dotPat(c, C.sub, 5, 1.7);
    const GP = [];
    let gi = 0;
    if (punch !== 1) { c.save(); c.translate(cxc, cyc); c.scale(punch, punch); c.translate(-cxc, -cyc); }
    RS.forEach(function (r, ri) {
      const base = top + size * 1.02 + ri * lh;
      let px = x0;
      for (let i = 0; i < r.chars.length; i++) {
        const ch = r.chars[i];
        const w = measure(c, ch.c, size, "black", F.sans, tracking);
        GP[gi + i] = { x: px, w: w, base: base };
        const sung = st.t >= ch.t;
        const dt = st.t - ch.t;
        const press = (dt >= 0 && dt < 2 / 24) ? (1 - dt / (2 / 24)) : 0;
        font(c, size, "black", F.sans, tracking);
        c.textAlign = "left";
        c.textBaseline = "alphabetic";
        if (sung) {
          const isM = marks.some(function (m) { return gi + i >= m[0] && gi + i < m[1]; });
          c.globalAlpha = 1;
          c.fillStyle = isM ? C.accent : C.paper;
          c.fillText(ch.c, px, base - 3 * press);
        } else if (dot) {
          c.globalAlpha = 0.32;
          c.fillStyle = dot;
          c.fillText(ch.c, px, base);
          c.globalAlpha = 1;
        }
        px += w + tracking;
      }
      gi += r.chars.length;
    });
    if (punch !== 1) c.restore();
    if ("letterSpacing" in c) c.letterSpacing = "0px";
    /* 强调词底线：跟着上墨走——擦到哪个字，线就长到哪个字（每字 4 帧，机械擦除，不做淡入） */
    marks.forEach(function (m) {
      const a = GP[m[0]], b = GP[m[1] - 1];
      if (!a || !b || !m[2]) return;
      let endX = a.x;
      for (let i = m[0]; i < m[1]; i++) {
        const g = GP[i], ch = P.chars[i];
        if (!g || !ch || st.t < ch.t) continue;
        endX = Math.max(endX, g.x + g.w * clamp((st.t - ch.t) / (4 / 24), 0, 1));
      }
      if (endX <= a.x) return;
      c.globalAlpha = 1;
      c.fillStyle = C.accent;
      c.fillRect(a.x, a.base + 9, endX - a.x, 3);
    });
  }
  /* ---------- ② 计数牌 TALLY ---------- */
  function mdTally(c, st, P, A) {
    const L = P.L, Z = zoneRect(L);
    const x0 = L.x === undefined ? Z.x : L.x;
    const y0 = L.y === undefined ? Z.y : L.y;
    const nd = L.digits || 2;
    const steps = (L.steps || []).slice().sort(function (a, b) { return a.t - b.t; });
    const VMAX = L.value === undefined ? 99 : L.value;
    const pe = easeOutCubic(clamp((st.t - A.t0) / ((st.ck ? st.ck.len : 0.455) * 0.25), 0, 1));
    const dy = 22 * (1 - pe);
    /* 当前值：按拍跳，不是匀速滚——值一变就翻牌（3 帧，linear） */
    let v = 0, vProg = 1;
    for (let i = 0; i < steps.length; i++) {
      if (st.t >= steps[i].t) { v = steps[i].v; vProg = clamp((st.t - steps[i].t) / (3 / 24), 0, 1); }
    }
    const CW = 104, CH = 134, GAP = 14;
    const bodyX = x0, bodyY = y0 + 44 + dy;
    /* 前导词：逐字上墨（唱到才出现，硬切；不提前）。
     * 标点 / 分隔符（·、｜）不占时间槽——它由字形自己认领，不是按字数硬配。 */
    const leadRaw = String(L.lead === undefined ? "" : L.lead);
    if (leadRaw) {
      let px = x0, gi = 0;
      const lr = [];
      let gate = -1;
      for (let i = 0; i < leadRaw.length; i++) {
        const dc = leadRaw[i];
        if (/\s/.test(dc)) continue;
        const slot = P.chars[gi];
        const mine = !!(slot && slot.c === dc);
        /* 装饰性标点（· ｜）跟着前一个字一起上墨，不抢在它前面出现 */
        lr.push({ c: dc, x: px, w: measure(c, dc, 26, "medium", F.sans, 1),
          mine: mine, t: mine ? slot.t : gate });
        if (mine) { gi++; gate = slot.t; }
        px += lr[lr.length - 1].w + 1;
      }
      lr.forEach(function (g) {
        if (st.t < g.t) return;
        c.globalAlpha = 1;
        c.fillStyle = g.mine ? C.paper : C.sub;
        font(c, 26, "medium", F.sans, 1);
        c.textAlign = "left"; c.textBaseline = "alphabetic";
        c.fillText(g.c, g.x, y0 + dy + 26 * 0.88);
      });
      if ("letterSpacing" in c) c.letterSpacing = "0px";
      hair(c, x0, y0 + 36 + dy, Math.max(120, px - x0 - 1), 1, C.line);
    }
    /* 数字牌：亮粉等宽数字，值变的那一刻翻面 */
    const ds = String(v).padStart(nd, "0");
    for (let i = 0; i < nd; i++) {
      flapFace(c, bodyX + i * (CW + GAP), bodyY, CW, CH, ds[i], vProg, {
        bg: C.tile, fg: C.accent, size: 76, family: F.mono, show: true,
      });
    }
    /* 「加」= 亮粉实底章节牌，落在人声「加」上（本句唯一的强调色） */
    if (L.plus) {
      const at = L.plusAt === undefined ? A.t0 : L.plusAt;
      const px = bodyX + nd * (CW + GAP);
      const p = clamp((st.t - at) / (3 / 24), 0, 1);
      if (p <= 0) {
        c.fillStyle = C.tile; c.fillRect(px, bodyY, CW, CH);
        c.strokeStyle = C.line; c.lineWidth = 1;
        c.strokeRect(px + 0.5, bodyY + 0.5, CW - 1, CH - 1);
      } else {
        const k = 1 + 0.14 * (1 - easeOutCubic(p));
        c.save();
        c.translate(px + CW / 2, bodyY + CH / 2); c.scale(k, k);
        c.fillStyle = C.accent; c.fillRect(-CW / 2, -CH / 2, CW, CH);
        c.fillStyle = C.ink;
        font(c, 70, "bold", F.mono, 0);
        c.textAlign = "center"; c.textBaseline = "middle";
        c.fillText("+", 0, 2);
        c.restore();
        if ("letterSpacing" in c) c.letterSpacing = "0px";
      }
    }
    /* 读数：速率 / 单位 / 未读——每个数字都必须真实 */
    const side = L.side || [];
    side.forEach(function (s, i) {
      txt(c, s, bodyX, bodyY + CH + 30 + i * 19, { size: 9, family: F.mono, color: C.sub, tracking: 2 });
    });
    if (L.unit) txt(c, L.unit, bodyX + (L.plus ? (nd + 1) : nd) * (CW + GAP) - GAP, bodyY + CH + 30,
      { size: 9, family: F.mono, color: C.accent, tracking: 2, align: "right" });
    void VMAX;
  }
  /* ---------- ③ 报幕 CALLER ---------- */
  function mdCaller(c, st, P, A) {
    const L = P.L, Z = zoneRect(L);
    const size = L.size || 40, tracking = L.tracking === undefined ? 2 : L.tracking;
    const y0 = L.y === undefined ? Z.y + 26 : L.y;
    const lh = size * 1.42;
    /* 报幕用行表（L.rows）原文——标点由下面单独认领，所以这里不去标点 */
    const parts = (L.rows && L.rows.length ? L.rows
      : (L.clauses && L.clauses.length ? L.clauses : [L.text])).map(String);
    /* 节目单式的外框：上下各一条细线；宽度按最长那句量，再按落位区对齐 */
    let maxW = 0;
    parts.forEach(function (raw) {
      const m = raw.match(/^([\s\S]*?)([。，、！？；：…—]*)$/);
      maxW = Math.max(maxW, measure(c, m[1], size, "normal", F.serif, tracking)
        + (m[2] ? measure(c, m[2], size, "normal", F.serif, tracking) : 0));
    });
    const boxW = Math.max(maxW, 360);
    const bx0 = L.x === undefined ? anchorX(Z, boxW) : L.x;
    const top = y0 - size * 0.66, bot = y0 + (parts.length - 1) * lh + size * 1.02;
    hair(c, bx0 - 26, top, boxW + 52, 1, C.line);
    hair(c, bx0 - 26, bot, boxW + 52, 1, C.line);
    if (L.label) txt(c, L.label, bx0 - 26, top - 28, { size: 9, family: F.mono, color: C.sub, tracking: 3 });
    let gi = 0;
    parts.forEach(function (raw, i) {
      const m = raw.match(/^([\s\S]*?)([。，、！？；：…—]*)$/);
      const body = lstrip(m[1]), punct = m[2] || "";
      const chars = P.chars.slice(gi, gi + body.length); gi += body.length;
      if (!chars.length) return;
      const at0 = chars[0].t;
      if (st.t < at0) return;                       // 硬切：0 帧渐变，面无表情
      const dt = st.t - at0;
      const k = dt < 1 / 24 ? 1.02 - 0.02 * (dt / (1 / 24)) : 1;
      const wB = measure(c, body, size, "normal", F.serif, tracking);
      const wP = punct ? measure(c, punct, size, "normal", F.serif, tracking) : 0;
      const sx = (Z.align === "left") ? bx0 : bx0 + (boxW - wB - wP);
      const by = y0 + i * lh;
      c.save();
      c.translate(sx + (wB + wP) / 2, by); c.scale(k, k); c.translate(-(sx + (wB + wP) / 2), -by);
      font(c, size, "normal", F.serif, tracking);
      c.textAlign = "left"; c.textBaseline = "alphabetic";
      c.fillStyle = C.paper;
      c.fillText(body, sx, by + size * 0.88);
      if (punct) { c.fillStyle = C.accent; c.fillText(punct, sx + wB, by + size * 0.88); }
      c.restore();
      if ("letterSpacing" in c) c.letterSpacing = "0px";
      /* 报幕刻线：这一句已经报到了（左端一枚亮粉短刻） */
      c.globalAlpha = 1;
      c.fillStyle = C.accent;
      c.fillRect(bx0 - 42, by + size * 0.44, 12, 2);
    });
    /* 走心段给「留盏灯」留一盏真灯（琥珀是稿子里的待命色，只在这里用） */
    if (L.lamp) {
      c.fillStyle = C.amber;
      c.globalAlpha = 0.35 + 0.65 * (st.ck ? st.ck.pulse : 0);
      c.beginPath(); c.arc(bx0 + boxW + 46, top + 18, 5, 0, Math.PI * 2); c.fill();
      c.globalAlpha = 0.18;
      c.beginPath(); c.arc(bx0 + boxW + 46, top + 18, 13, 0, Math.PI * 2); c.fill();
      c.globalAlpha = 1;
    }
  }
  /* ---------- ④ 卡拉OK长条 CUE：半句对折 + 逐字点亮 + 进度线 ---------- */
  function mdCue(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    const rows = rowsOf(P, L.rows || halfParts(P.text));
    if (needBand(st)) softBand(c, Z, 0.5);
    const B = blockRows(c, rows, Z.w, L.size || 68, "bold", F.sans, 1);
    const marks = markRanges(P);
    /* 拍点游标：落位区外侧一枚亮粉竖刻，跟着拍呼吸 */
    const pl = st.ck ? st.ck.pulse : 0;
    const bx = anchorX(Z, B.w) + E.dx;
    c.globalAlpha = 0.45 + 0.55 * pl;
    c.fillStyle = C.accent;
    c.fillRect(Z.align === "right" ? bx + B.w + 22 : bx - 26,
      Z.y + (Z.h - B.size * 1.6) / 2, 4, B.size * 1.5);
    c.globalAlpha = 1;
    const PB = paintBlock(c, st, Z, B, { dx: E.dx, dy: E.dy, weight: "bold",
      cur: C.accent, past: C.paper, ghostAlpha: 0.42, marks: marks });
    /* 进度线：唱到哪儿，线到哪儿（本装置的仪表，不是装饰） */
    const y = PB.top + PB.blockH + 16;
    hair(c, bx, y, B.w, 1, C.line);
    c.fillStyle = C.accent;
    c.fillRect(bx, y - 1, B.w * progOf(st, P), 2.5);
  }
  /* ---------- ⑤ 终端打印 TAPE：等宽 + 打字机 + 光标 + 行号 ---------- */
  function mdTape(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    const rows = rowsOf(P, L.rows || P.text.split(/\s+/));
    if (needBand(st)) softBand(c, Z, 0.55);
    const size = L.size || 30, tracking = 2, weight = "normal";
    const lh = size * 1.66;
    const blockH = lh * (rows.length - 1) + size * 1.4;
    const top = Z.y + (Z.h - blockH) / 2;
    const bw = Math.min(Z.w, 560);
    const hx = anchorX(Z, bw) + E.dx;
    txt(c, ">", hx, top - 18 + E.dy, { size: 13, family: F.mono, color: C.accent, tracking: 1 });
    if (L.note) txt(c, L.note, hx + bw, top - 18 + E.dy,
      { size: 9, family: F.mono, color: C.sub, tracking: 3, align: "right" });
    hair(c, hx, top - 6 + E.dy, bw, 1, C.line);
    /* 正文：一个字一个字被敲出来（终端里没有「尚未发生的字」） */
    const blink = Math.floor(st.t / ((st.beatLen || 0.418) / 2)) % 2 === 0;
    let curX = 0, curY = 0, awaiting = -1;
    rows.forEach(function (r, ri) {
      const cells = layoutRow(c, r.text, r.chars, size, weight, F.mono, tracking).cells;
      const w = rowWidth(cells);
      const x0 = anchorX(Z, bw) + 46 + E.dx;
      const base = top + size * 1.0 + ri * lh + E.dy;
      txt(c, String(ri + 1).padStart(2, "0"), x0 - 46, base,
        { size: 11, family: F.mono, color: C.sub, tracking: 1 });
      void w;
      cells.forEach(function (g) {
        if (g.slot === null) return;
        const dt = st.t - g.slot.t;
        if (dt <= 0) {
          if (awaiting < 0) { awaiting = g.slot.t; curX = x0 + g.x; curY = base; }
          return;
        }
        font(c, size, weight, F.mono, 0);
        c.textAlign = "left"; c.textBaseline = "alphabetic";
        c.globalAlpha = clamp(dt / (2 / 24), 0, 1);
        c.fillStyle = C.paper;
        c.fillText(g.c, x0 + g.x, base);
        c.globalAlpha = 1;
        if (st.t < g.slot.e) {                    // 正在发声：字下一条亮粉线
          c.fillStyle = C.accent;
          c.fillRect(x0 + g.x, base + 5, g.w, 2);
        }
      });
    });
    if ("letterSpacing" in c) c.letterSpacing = "0px";
    if (awaiting > 0) {                            // 光标停在下一个待打的字上
      c.fillStyle = C.accent;
      c.globalAlpha = blink ? 0.9 : 0.15;
      c.fillRect(curX, curY - size * 0.82, size * 0.5, size * 0.98);
      c.globalAlpha = 1;
    }
  }
  /* ---------- ⑥ 账本 LEDGER：原句等宽上墨 + 虚线引出 + 合计落定 ---------- */
  function mdLedger(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    if (needBand(st)) softBand(c, Z, 0.55);
    const size = L.size || 28, tracking = 2;
    const cells = layoutRow(c, P.text, P.chars, size, "normal", F.mono, tracking).cells;
    const w = Math.max(rowWidth(cells), 560);
    const x0 = anchorX(Z, w) + E.dx;
    const base = Z.y + 42 + E.dy;
    txt(c, "账单 / BALANCE", x0, Z.y - 6 + E.dy, { size: 9, family: F.mono, color: C.sub, tracking: 3 });
    c.save(); c.translate(x0, base);
    /* 未唱到的字是「印版草样」：0.3 在夜戏上等于看不见，抬到 0.5 才读得出这是一张账单 */
    paintRow(c, cells, size, "normal", F.mono, st, { cur: C.accent, past: C.paper, ghostAlpha: 0.5 });
    c.restore();
    hair(c, x0, base + 12, w, 1, C.line);
    for (let x = x0; x < x0 + w - 4; x += 11) {    // 虚线引出：像真的账单
      c.fillStyle = C.line; c.fillRect(x, base + 40, 5, 1);
    }
    const last = P.chars[P.chars.length - 1];
    const at = L.valueAt === undefined ? (last ? last.e : gate) : L.valueAt;
    const k = clamp((st.t - at) / (3 / 24), 0, 1);
    if (k > 0) {
      const vs = String(L.value === undefined ? "" : L.value), us = String(L.unit === undefined ? "" : L.unit);
      const vSize = 76, wv = measure(c, vs, vSize, "bold", F.mono, 0)
        + (us ? measure(c, us, 30, "normal", F.mono, 2) + 8 : 0);
      const vx = x0 + w - wv, vy = base + 122 - 20 * (1 - k);
      c.globalAlpha = k;
      c.fillStyle = C.accent;
      c.fillRect(x0 + w - wv * k, base + 116, wv * k, 3);   // 合计线跟着数字长出来
      txt(c, vs, vx, vy, { size: vSize, weight: "bold", family: F.mono, color: C.paper });
      if (us) txt(c, us, vx + measure(c, vs, vSize, "bold", F.mono, 0) + 8, vy + 44,
        { size: 30, family: F.mono, color: C.accent, tracking: 2 });
      c.globalAlpha = 1;
      if (L.label) txt(c, L.label, x0, base + 156, { size: 10, family: F.mono, color: C.sub, tracking: 2 });
    }
  }
  /* ---------- ⑦ 划改 STRIKE：全句先印好，唱到关键词时被划掉 ---------- */
  function mdStrike(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    const rows = rowsOf(P, L.rows || halfParts(P.text));
    if (needBand(st)) softBand(c, Z, 0.5);
    const B = blockRows(c, rows, Z.w, L.size || 56, "bold", F.sans, 1);
    const kw = lstrip(L.strikeAt || "");
    const at = kw ? P.text.indexOf(kw) : -1;
    const hc = at >= 0 ? P.chars[at] : null;
    /* 命中那一刻整块抖一下（确定性，不是随机数） */
    const jit = (hc && st.t >= hc.t && st.t < hc.t + 2 / 24)
      ? (hash(Math.floor(hc.t * 97) + 3) - 0.5) * 5 : 0;
    const PB = paintBlock(c, st, Z, B, { dx: E.dx + jit, dy: E.dy, weight: "bold",
      cur: C.accent, past: C.paper, ghostAlpha: 0.4 });
    if (at < 0 || !hc || st.t < hc.t) return;
    const p = clamp((st.t - hc.t) / (3 / 24), 0, 1);
    let gi = 0;
    PB.lines.forEach(function (L2) {
      let xa = null, xb = null;
      L2.cells.forEach(function (g) {
        if (g.slot === null) return;
        const idx = gi + g.i;
        if (idx >= at && idx < at + kw.length) {
          xa = (xa === null) ? g.x : Math.min(xa, g.x);
          xb = Math.max(xb === null ? -1e9 : xb, g.x + g.w);
        }
      });
      if (xa !== null) {                          // 斜着擦过去——手写划改不是尺子画的
        c.save();
        c.translate(L2.x + xa, L2.base - B.size * 0.30);
        c.rotate(-0.035);
        c.fillStyle = C.accent;
        c.fillRect(0, 0, (xb - xa) * p, 7);
        c.restore();
      }
      gi += L2.cells.filter(function (g) { return g.slot !== null; }).length;
    });
  }
  /* ---------- ⑧ 重击 PUNCH：全句小字在，关键词被一块亮粉版砸出来 ---------- */
  function mdPunch(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    const rows = rowsOf(P, L.rows || halfParts(P.text));
    if (needBand(st)) softBand(c, Z, 0.5);
    const B = blockRows(c, rows, Z.w, L.size || 46, "bold", F.sans, 1);
    const kw = lstrip(L.hit || "");
    const at = kw ? P.text.indexOf(kw) : -1;
    const hc = at >= 0 ? P.chars[at] : null;
    const hp = hc ? clamp((st.t - hc.t) / (3 / 24), 0, 1) : 0;
    const PB = paintBlock(c, st, Z, B, { dx: E.dx, dy: E.dy, weight: "bold",
      cur: C.accent, past: C.paper, ghostAlpha: 0.4 });
    if (at < 0 || hp <= 0) return;
    /* 找关键词在排版里的横区间（它可能落在任意一行） */
    let gi = 0, hit = null;
    PB.lines.forEach(function (L2) {
      let xa = null, xb = null;
      L2.cells.forEach(function (g) {
        if (g.slot === null) return;
        const idx = gi + g.i;
        if (idx >= at && idx < at + kw.length) {
          xa = (xa === null) ? g.x : Math.min(xa, g.x);
          xb = Math.max(xb === null ? -1e9 : xb, g.x + g.w);
        }
      });
      if (xa !== null && !hit) hit = { xa: xa, xb: xb, x: L2.x, base: L2.base, cells: L2.cells, gi0: gi };
      gi += L2.cells.filter(function (g) { return g.slot !== null; }).length;
    });
    if (!hit) return;
    const k = 1 + 0.10 * (1 - easeOutCubic(hp));    // 2 帧从 1.10 落到 1.0（砸，不是弹）
    const bw = (hit.xb - hit.xa) + 24, bh = B.size * 1.20;
    c.save();
    c.translate(hit.x + hit.xa + (hit.xb - hit.xa) / 2, hit.base - B.size * 0.32);
    c.scale(k, k);
    c.fillStyle = C.accent;
    c.fillRect(-bw / 2, -bh / 2, bw, bh);
    c.restore();
    if (hp < 1 / 24) {
      c.globalAlpha = 0.26 * (1 - hp * 24);
      c.fillStyle = C.paper;
      c.fillRect(Z.x, PB.top - 8, Z.w, PB.blockH + 16);
      c.globalAlpha = 1;
    }
    c.save();
    c.translate(hit.x, hit.base);
    font(c, B.size, "bold", F.sans, 1);
    c.textAlign = "left"; c.textBaseline = "alphabetic";
    c.fillStyle = C.ink;
    hit.cells.forEach(function (g) {
      if (g.slot === null) return;
      const abs = hit.gi0 + g.i;
      if (abs >= at && abs < at + kw.length) c.fillText(g.c, g.x, 0);
    });
    c.restore();
    if ("letterSpacing" in c) c.letterSpacing = "0px";
  }
  /* ---------- ⑨ 印章堆 HOOK：副歌签名装置（有几个「示例」就盖几个章） ---------- */
  function mdHook(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    if (needBand(st)) softBand(c, Z, 0.42);
    const toks = rowsOf(P, P.text.split(/\s+/).filter(Boolean));
    /* 先量：每个 token 的宽度（印章 = 大字 + 内边距；其余 = 常规粗体） */
    const K = { stamp: 60, text: 50, pad: 34, gap: 30 };
    const isStamp = function (t) { return t === HOOK; };
    const widthOf = function (t, s) {
      return isStamp(t) ? measure(c, t, s, "black", F.sans, 3) + K.pad : measure(c, t, s, "bold", F.sans, 1);
    };
    let sum = 0;
    toks.forEach(function (r) { sum += widthOf(r.text, isStamp(r.text) ? K.stamp : K.text) + K.gap; });
    sum -= K.gap;
    const scale = sum > Z.w ? Z.w / sum : 1;
    const stampS = K.stamp * scale, textS = K.text * scale, gap = K.gap * scale, pad = K.pad * scale;
    sum *= 1;
    let x = anchorX(Z, sum) + E.dx;
    const cy = Z.y + Z.h / 2 + E.dy;
    toks.forEach(function (r, ti) {
      const t0 = r.chars[0] ? r.chars[0].t : gate;
      if (st.t < t0) { x += widthOf(r.text, isStamp(r.text) ? stampS : textS) + gap; return; }
      const dt = st.t - t0;
      if (isStamp(r.text)) {
        /* 印章：从 1.14 砸到 1.0（2 帧），落定后带一点机械余震 */
        const p = clamp(dt / (2 / 24), 0, 1);
        const k = 1 + 0.14 * (1 - easeOutCubic(p)) * (0.98 + 0.04 * Math.cos(st.t * 60));
        const w = measure(c, r.text, stampS, "black", F.sans, 3) + pad, h = stampS * 1.62;
        c.save();
        c.translate(x + w / 2, cy);
        c.rotate(ti % 2 ? 0.052 : -0.062);
        c.scale(k, k);
        c.fillStyle = C.accent; c.globalAlpha = 0.96;
        c.fillRect(-w / 2, -h / 2, w, h);
        c.fillStyle = C.ink; c.globalAlpha = 0.15;      // 印章的 riso 底纹
        for (let yy = -h / 2 + 5; yy < h / 2 - 2; yy += 7)
          for (let xx = -w / 2 + 5; xx < w / 2 - 2; xx += 7) c.fillRect(xx, yy, 2, 2);
        c.globalAlpha = 1;
        c.strokeStyle = C.ink; c.lineWidth = 3;
        c.strokeRect(-w / 2, -h / 2, w, h);
        c.save(); c.translate(-measure(c, r.text, stampS, "black", F.sans, 3) / 2, stampS * 0.36);
        paintRow(c, layoutRow(c, r.text, r.chars, stampS, "black", F.sans, 3).cells,
          stampS, "black", F.sans, st, { cur: C.ink, past: C.ink, ghost: false });
        c.restore();
        c.restore();
        if ("letterSpacing" in c) c.letterSpacing = "0px";
        x += w + gap;
      } else {
        const cells = layoutRow(c, r.text, r.chars, textS, "bold", F.sans, 1).cells;
        const w = rowWidth(cells);
        const base = cy + textS * 0.36;
        c.save(); c.translate(x, base);
        paintRow(c, cells, textS, "bold", F.sans, st, { cur: C.accent, past: C.paper, ghostAlpha: 0.42 });
        c.restore();
        /* 底线跟着人声走：擦到哪个字，线就长到哪个字 */
        let endX = x;
        cells.forEach(function (g) {
          if (g.slot === null || st.t < g.slot.t) return;
          endX = Math.max(endX, x + g.x + g.w * clamp((st.t - g.slot.t) / (4 / 24), 0, 1));
        });
        if (endX > x) { c.fillStyle = C.accent; c.fillRect(x, base + 10, endX - x, 4); }
        x += w + gap;
      }
    });
  }
  /* ---------- ⑩ 堆叠 STACK：一句拆成几块牌子，按拍一块块落进来 ---------- */
  function mdStack(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    const rows = rowsOf(P, L.rows || P.text.split(/\s+/));
    if (needBand(st)) softBand(c, Z, 0.5);
    const size = L.size || 38, rh = size * 1.86, gap = 8;
    const blockH = rows.length * rh + (rows.length - 1) * gap;
    const top = Z.y + (Z.h - blockH) / 2;
    let wid = 0;
    const laid = rows.map(function (r) {
      const l = layoutRow(c, r.text, r.chars, size, "bold", F.sans, 1);
      wid = Math.max(wid, l.width);
      return l;
    });
    const bw = Math.min(Z.w, wid + 96);
    const x0 = anchorX(Z, bw) + E.dx;
    laid.forEach(function (l, ri) {
      const t0 = rows[ri].chars[0] ? rows[ri].chars[0].t : gate;
      const p = clamp((st.t - t0) / (3 / 24), 0, 1);
      if (p <= 0) return;
      const y = top + ri * (rh + gap) + E.dy - 18 * (1 - p);
      c.globalAlpha = p;
      c.fillStyle = C.tile; c.fillRect(x0, y, bw, rh);
      c.strokeStyle = C.line; c.lineWidth = 1; c.strokeRect(x0 + 0.5, y + 0.5, bw - 1, rh - 1);
      c.fillStyle = C.accent; c.fillRect(x0, y, 5, rh);      // 左端亮粉书脊
      txt(c, String(ri + 1).padStart(2, "0"), x0 + 18, y + rh * 0.66,
        { size: 11, family: F.mono, color: C.sub, tracking: 1 });
      c.globalAlpha = 1;
      c.save(); c.translate(x0 + 60, y + size * 1.16);
      paintRow(c, l.cells, size, "bold", F.sans, st, { cur: C.accent, past: C.paper, ghostAlpha: 0.4 });
      c.restore();
    });
  }
  /* ---------- ⑪ 对峙 VERSUS：左右两个词各自推入，中间一刀切下来 ---------- */
  function mdVersus(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st);
    const box = { x: 150, y: Z.y - 40, w: 1620, h: Math.max(Z.h + 80, 260), align: "left" };
    if (needBand(st)) softBand(c, box, 0.5);
    const lw = lstrip(L.left || ""), rw = lstrip(L.right || "");
    const size = L.size || 62, mid = box.x + box.w / 2, cy = box.y + 66;
    const li = P.text.indexOf(lw), ri = P.text.indexOf(rw);
    const lt = li >= 0 ? P.chars[li].t : gate, rt = ri >= 0 ? P.chars[ri].t : gate;
    const lp = clamp((st.t - lt) / (3 / 24), 0, 1), rp = clamp((st.t - rt) / (3 / 24), 0, 1);
    /* 中缝：3 帧自上而下切下来 */
    const dp = clamp((st.t - Math.min(lt, rt)) / (3 / 24), 0, 1);
    c.fillStyle = C.accent;
    c.fillRect(mid - 1, box.y, 2, box.h * dp);
    if (dp > 0) {
      c.fillStyle = C.accent;
      c.fillRect(mid - 6, box.y + box.h * dp - 2, 12, 4);
    }
    if (lp > 0) {                              // 左词从左边推进来（3 帧，linear）
      const wl = measure(c, lw, size, "black", F.sans, 2);
      txt(c, lw, mid - 60 - wl - 40 * (1 - lp), cy,
        { size: size, weight: "black", family: F.sans, color: C.paper, tracking: 2 });
    }
    if (rp > 0) txt(c, rw, mid + 60 + 40 * (1 - rp), cy,
      { size: size, weight: "black", family: F.sans, color: C.paper, tracking: 2 });
    /* 尾句：小字居中，仍然照人声逐字上墨 */
    if (L.tail) {
      const ti = P.text.indexOf(L.tail);
      const tc = ti >= 0 ? P.chars.slice(ti, ti + lstrip(L.tail).length) : [];
      const ts = 26;
      const l = layoutRow(c, L.tail, tc, ts, "normal", F.sans, 4);
      const x = box.x + (box.w - l.width) / 2;
      c.save(); c.translate(x, box.y + box.h - 34);
      paintRow(c, l.cells, ts, "normal", F.sans, st, { cur: C.accent, past: C.sub, ghostAlpha: 0.25 });
      c.restore();
    }
  }
  /* ---------- ⑫ 量尺 MEASURE：一个真实数值 + 一条走格子的标尺 ---------- */
  function mdMeasure(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    if (needBand(st)) softBand(c, Z, 0.55);
    const size = L.size || 26, tracking = 2;
    const cells = layoutRow(c, P.text, P.chars, size, "normal", F.mono, tracking).cells;
    const w = Math.max(rowWidth(cells), 620);
    const x0 = anchorX(Z, w) + E.dx;
    const base = Z.y + 30 + E.dy;
    txt(c, L.label || "MEASURE", x0, Z.y - 10 + E.dy, { size: 10, family: F.mono, color: C.sub, tracking: 3 });
    c.save(); c.translate(x0, base);
    paintRow(c, cells, size, "normal", F.mono, st, { cur: C.accent, past: C.paper, ghostAlpha: 0.3 });
    c.restore();
    /* 数值读数：人声唱到最后那个字时落下 */
    const last = P.chars[P.chars.length - 1];
    const at = L.valueAt === undefined ? (last ? last.e : gate) : L.valueAt;
    const k = clamp((st.t - at) / (3 / 24), 0, 1);
    const vs = String(L.value === undefined ? "" : L.value);
    const us = String(L.unit === undefined ? "" : L.unit);
    const vSize = 92;
    const wv = measure(c, vs, vSize, "bold", F.mono, 0) + (us ? measure(c, us, 34, "normal", F.mono, 2) + 8 : 0);
    const y0v = base + 128 - 22 * (1 - k);
    if (k > 0) {
      c.globalAlpha = k;
      txt(c, vs, x0, y0v, { size: vSize, weight: "bold", family: F.mono, color: C.paper });
      if (us) txt(c, us, x0 + measure(c, vs, vSize, "bold", F.mono, 0) + 8, y0v - 8,
        { size: 34, family: F.mono, color: C.accent, tracking: 2 });
      c.globalAlpha = 1;
    }
    /* 标尺：20 格，亮粉填色 = 这一行的发声进度（这是真值，不是示意） */
    const ry = base + 152, seg = w / 20;
    hair(c, x0, ry, w, 1, C.line);
    for (let i = 0; i <= 20; i++) {
      const xx = x0 + i * seg;
      c.fillStyle = C.sub;
      c.fillRect(xx, ry - (i % 5 === 0 ? 10 : 5), 1, i % 5 === 0 ? 10 : 5);
    }
    c.fillStyle = C.accent;
    c.fillRect(x0, ry - 2, w * progOf(st, P), 4);
    void wv;
  }
  /* ---------- ⑬ 名单 ROSTER：几个名字按拍一个个落座 ---------- */
  function mdRoster(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    if (needBand(st)) softBand(c, Z, 0.5);
    const names = (L.names || []).slice(0, 4);
    const size = L.size || 34, pad = 30, gap = 18;
    const ws = names.map(function (n) { return measure(c, n, size, "bold", F.mono, 2) + pad; });
    const total = ws.reduce(function (a, b) { return a + b; }, 0) + gap * (names.length - 1);
    let x = anchorX(Z, total) + E.dx;
    const y = Z.y + 46, h = size * 1.9;
    let lastAt = gate;
    names.forEach(function (n, i) {
      const at = P.text.indexOf(n);
      const t0 = at >= 0 && P.chars[at] ? P.chars[at].t : gate + i * (st.beatLen || 0.418) * 0.5;
      lastAt = Math.max(lastAt, t0);
      const p = clamp((st.t - t0) / (3 / 24), 0, 1);
      if (p > 0) {
        const dy = -22 * (1 - p);
        c.globalAlpha = p;
        c.fillStyle = C.paper;
        c.fillRect(x, y + dy, ws[i], h);
        c.globalAlpha = 1;
        if (p >= 1) {
          font(c, size, "bold", F.mono, 2);
          c.fillStyle = C.ink;
          c.textAlign = "left"; c.textBaseline = "alphabetic";
          c.fillText(n, x + pad / 2, y + h * 0.68);
          if ("letterSpacing" in c) c.letterSpacing = "0px";
          c.fillStyle = C.accent;
          c.fillRect(x, y + h, ws[i], 3);          // 落座：牌子下压一条亮粉
        }
      } else {
        c.strokeStyle = C.line; c.lineWidth = 1;
        c.strokeRect(x + 0.5, y + 0.5, ws[i] - 1, h - 1);
      }
      x += ws[i] + gap;
    });
    /* 全员落座后才亮起的那条连接线（真实的先后顺序，不是一起淡入） */
    if (st.t >= lastAt + 3 / 24) {
      const cp = clamp((st.t - lastAt) / (st.beatLen || 0.418), 0, 1);
      const x0 = anchorX(Z, total) + E.dx;
      c.fillStyle = C.accent;
      c.fillRect(x0, y + h + 14, total * cp, 1.5);
    }
    /* 剩下的话仍然逐字上墨（人名已经在牌子上，正文只画剩下的） */
    const rest = names.reduce(function (t, n) { return t.replace(n, ""); }, P.text).replace(/\s+/g, " ").trim();
    if (rest) {
      const ts = 22;
      const l = layoutRow(c, rest, P.chars.slice(P.chars.length - lstrip(rest).length), ts, "normal", F.sans, 3);
      c.save(); c.translate(anchorX(Z, l.width) + E.dx, y + h + 60);
      paintRow(c, l.cells, ts, "normal", F.sans, st, { cur: C.accent, past: C.sub, ghostAlpha: 0.25 });
      c.restore();
    }
  }
  /* ---------- ⑭ 回声 ECHO：一个词在纵深里回响（Figma 5:354） ---------- */
  function mdEcho(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    const rows = rowsOf(P, L.rows || halfParts(P.text));
    if (needBand(st)) softBand(c, Z, 0.5);
    const B = blockRows(c, rows, Z.w, L.size || 52, "bold", F.sans, 1);
    paintBlock(c, st, Z, B, { dx: E.dx, dy: E.dy, weight: "bold",
      cur: C.accent, past: C.paper, ghostAlpha: 0.4 });
    const kw = lstrip(L.echoAt || "");
    if (!kw) return;
    const at = P.text.indexOf(kw);
    const hc = at >= 0 ? P.chars[at] : null;
    if (!hc) return;
    /* 3 层回声：每一层往后一拍才出现，越来越小越淡（纵深是时间堆出来的） */
    const beat = st.beatLen || 0.418, size = B.size * 1.06;
    for (let i = 1; i <= 3; i++) {
      const t0 = hc.t + i * beat * 0.5;
      if (st.t < t0) continue;
      const p = clamp((st.t - t0) / (3 / 24), 0, 1);
      const k = 1 - i * 0.16;
      const cells = layoutRow(c, kw, P.chars.slice(at, at + kw.length), size * k, "bold", F.sans, 1).cells;
      c.save();
      c.translate(Z.x + 40 + i * 46, Z.y + Z.h - 30 - i * 30);
      const aa = (p * (0.42 - i * 0.10)).toFixed(3);
      const col = "rgba(245,245,242," + aa + ")";
      paintRow(c, cells, size * k, "bold", F.sans, st, { cur: col, past: col, ghost: false });
      c.restore();
    }
  }
  /* ---------- ⑮ 低语 WHISPER：Bridge 专用，几乎不动的衬线体 ---------- */
  function mdWhisper(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st);
    if (needBand(st)) softBand(c, Z, 0.5);
    const size = L.size || 38, tracking = 6;
    const cells = layoutRow(c, P.text, P.chars, size, "normal", F.serif, tracking).cells;
    const w = rowWidth(cells);
    const x0 = anchorX(Z, w);
    const p = clamp((st.t - gate) / ((st.beatLen || 0.418) * 0.5), 0, 1);
    const e = easeOutCubic(p);
    c.globalAlpha = 0.92 * e;
    c.save(); c.translate(x0, Z.y + Z.h / 2 + 8 * (1 - e));
    paintRow(c, cells, size, "normal", F.serif, st, { cur: C.paper, past: C.paper, ghostAlpha: 0.22 });
    c.restore();
    /* 呼吸线：本档唯一的装饰，长度 = 人声进度 */
    const y = Z.y + Z.h / 2 + 34;
    hair(c, x0, y, w, 1, C.line);
    c.globalAlpha = 0.9;
    c.fillStyle = C.accent;
    c.fillRect(x0, y - 1, w * progOf(st, P), 2);
    c.globalAlpha = 1;
  }
  /* ---------- ⑯ 硬料 SAVAGE：套印错位 + 重拍抖动 + 关键词砸框 ---------- */
  function mdSavage(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    const rows = rowsOf(P, L.rows || halfParts(P.text));
    if (needBand(st)) softBand(c, Z, 0.55);
    const B = blockRows(c, rows, Z.w, L.size || 54, "black", F.sans, 1);
    const since = st.ck ? st.ck.since : 1;
    const jit = since < 0.08 ? (hash((st.ck ? st.ck.idx : 0) * 1.7) - 0.5) * 5 : 0;
    const PB = paintBlock(c, st, Z, B, { dx: E.dx + jit, dy: E.dy, weight: "black",
      cur: C.accent, past: C.paper, ghostAlpha: 0.4 });
    /* riso 套印：品红 / 琥珀两层错开 3px，用 screen 叠，再压一层实色正文 */
    c.save();
    c.globalCompositeOperation = "screen";
    [[-3, C.accent], [3, C.amber]].forEach(function (LN) {
      PB.lines.forEach(function (L2) {
        c.save(); c.translate(L2.x + LN[0], L2.base);
        paintRow(c, L2.cells, B.size, "black", F.sans, st, { cur: LN[1], past: LN[1], ghostAlpha: 0.3, ghost: false });
        c.restore();
      });
    });
    c.restore();
    /* 关键词砸框：命中词唱到的那一瞬，方框从外收拢进来 */
    const hits = L.hits || [];
    let gi = 0;
    const gidx = [];
    PB.lines.forEach(function (L2) {
      L2.cells.forEach(function (g) { if (g.slot) { g.gi = gi; gi++; } });
      gidx.push(L2);
    });
    hits.forEach(function (kw0) {
      const kw = lstrip(kw0), at = P.text.indexOf(kw);
      if (at < 0) return;
      const hc = P.chars[at];
      if (!hc || st.t < hc.t) return;
      const p = clamp((st.t - hc.t) / (3 / 24), 0, 1);
      gidx.forEach(function (L2) {
        let xa = null, xb = null;
        L2.cells.forEach(function (g) {
          if (!g.slot) return;
          if (g.gi >= at && g.gi < at + kw.length) {
            xa = (xa === null) ? g.x : Math.min(xa, g.x);
            xb = Math.max(xb === null ? -1e9 : xb, g.x + g.w);
          }
        });
        if (xa === null) return;
        const gx = 40 * (1 - p);
        c.strokeStyle = C.accent; c.lineWidth = 2;
        c.strokeRect(L2.x + xa - 6 - gx, L2.base - B.size * 0.86 - 6 - gx * 0.4,
          (xb - xa) + 12 + gx * 2, B.size * 1.06 + 12 + gx * 0.8);
      });
    });
  }
  /* ---------- ⑰ 题名 TITLE：片头那一下（0–2s 无人声） ---------- */
  function mdTitle(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st), E = zoneEnter(st, Z, gate);
    const size = L.size || 112, tracking = 6;
    const cells = layoutRow(c, P.text, P.chars, size, "black", F.sans, tracking).cells;
    const w = rowWidth(cells);
    const x0 = anchorX(Z, w);
    const p = clamp((st.t - gate) / (4 / 24), 0, 1);
    const e = easeOutCubic(p);
    const y = Z.y + Z.h / 2;
    if (L.kicker) txt(c, L.kicker, x0, y - size * 0.92, { size: 12, family: F.mono, color: C.sub, tracking: 6 });
    hair(c, x0 - 4, y - size * 0.62, w + 8, 1, C.line);
    c.save(); c.translate(x0, y + size * 0.34 + 22 * (1 - e));
    paintRow(c, cells, size, "black", F.sans, st, { cur: C.paper, past: C.paper, ghost: false });
    c.restore();
    c.fillStyle = C.accent;
    c.fillRect(x0, y + size * 0.52, (w + 8) * e, 5);        // 亮粉横线自左向右拉出来
    /* 右端对位数（真实值） */
    txt(c, "24 FPS · 1920×1080", x0 + w, y + size * 0.96, { size: 10, family: F.mono, color: C.sub, tracking: 3, align: "right" });
  }
  /* ---------- ⑱ 落版 ENDCARD：片尾收尾（193.1s 之后无人声） ---------- */
  function mdEndcard(c, st, P, A) {
    const L = P.L, Z = zoneRect(L), gate = gateAt(P, st);
    const V = st.visual || {};
    let x0 = Z.x + Z.w / 2;
    const p = clamp((st.t - gate) / (4 / 24), 0, 1);
    if (p <= 0) return;
    const e = easeOutCubic(p);
    c.globalAlpha = e;
    font(c, 64, "black", F.sans, 6);
    c.textAlign = "center"; c.textBaseline = "alphabetic";
    c.fillStyle = C.paper;
    c.fillText(P.text, x0, Z.y + 92 - 16 * (1 - e));
    if ("letterSpacing" in c) c.letterSpacing = "0px";
    c.fillStyle = C.accent;
    c.fillRect(x0 - 300 * e, Z.y + 112, 600 * e, 4);
    /* 下面的读数是一句一件，按拍依次落定（不是一起淡入） */
    const beat = st.beatLen || 0.418;
    const tk = (V.ticker || []).slice(0, 4);
    tk.forEach(function (s, i) {
      const at = gate + (i + 1) * beat * 0.75;
      const q = clamp((st.t - at) / (3 / 24), 0, 1);
      if (q <= 0) return;
      c.globalAlpha = q;
      c.fillStyle = i === 0 ? C.accent : C.sub;
      font(c, 13, i === 0 ? "bold" : "normal", F.mono, 4);
      c.textAlign = "center"; c.textBaseline = "alphabetic";
      c.fillText(s, x0, Z.y + 156 + i * 26);
      if ("letterSpacing" in c) c.letterSpacing = "0px";
    });
    c.globalAlpha = 1;
  }
  const LY3 = { placard: mdPlacard, tally: mdTally, caller: mdCaller,
    cue: mdCue, tape: mdTape, ledger: mdLedger, strike: mdStrike, punch: mdPunch,
    hook: mdHook, stack: mdStack, versus: mdVersus, measure: mdMeasure,
    roster: mdRoster, echo: mdEcho, whisper: mdWhisper, savage: mdSavage,
    title: mdTitle, endcard: mdEndcard };

  let _LAST_ST = null;                     // 诊断用：最近一帧的 state
  const LYRIC = {
    state: lineState,
    render: function (c, st) {
      /* v3：行表在 shots.json 的 visual.lyrics.lines（每行必须自己声明 style） */
      const plan = st.lyricPlan;
      if (plan && plan.length) {
        const A = activeLine(st, plan);
        if (!A) return;
        const fn = LY3[A.line.style];
        if (fn) return fn(c, st, A.line, A);
        /* 行表只为了让 v2 档位有逐字时间：这里把它当成"行级钩子"，转交 v2 */
        st.lyric = { i: A.i, line: { text: A.line.text, chars: A.line.chars,
          mood: A.line.style || A.line.mood || "rant", t0: A.t0,
          t1: A.line.chars[A.line.chars.length - 1].e }, next: null, curIdx: -1, prog: 0, dim: 0.55 };
      }
      if (!st.lyricLines || !st.lyricLines.length) return fallbackSubtitle(c, st);
      const S = st.lyric;
      if (!S) return;
      const mood = S.line.mood || "rant";
      /* 底板：大字段落（副歌/狠句/走心）让 chrome 退到背景里，
       * 主歌则保留翻牌长条可见——字幕不跟 HUD 打架，但也不把片子压平。 */
      if (S.line.zone) {
        /* v4 装置自带板面纪律（干净渲染；只有亮镜才铺一条软沉降带），
         * 这里不再加第二层情绪底板——否则 64 行又会被压回「一条横带」。 */
      } else if (mood === "hype" || mood === "savage") {
        c.fillStyle = C.ink; c.globalAlpha = 0.52;
        c.fillRect(0, 772, W, 1016 - 772); c.globalAlpha = 1;
        hair(c, 0, 772, W, 1, C.line);
      } else if (mood === "quiet") {
        c.fillStyle = C.ink; c.globalAlpha = 0.46;
        c.fillRect(0, 802, W, 1010 - 802); c.globalAlpha = 1;
        hair(c, 0, 802, W, 1, C.line);
      } else if (mood !== "announce") {
        _scrim(c, 872, 1016, 0.55);
      }
      if (mood === "announce") return drawAnnounce(c, st, S);
      if (mood === "hype") return drawHype(c, st, S);
      if (mood === "savage") return drawSavage(c, st, S);
      if (mood === "quiet") return drawQuiet(c, st, S);
      if (mood === "praise") return drawPraise(c, st, S);
      return drawRant(c, st, S, {});
    },
  };

  /* ---------- 意义层原子件（Figma 4:2 – 5:354 / 21 件） ---------- */
  function MIC(c, s, x, y, o) { return txt(c, s, x, y, Object.assign({ size: 11, color: C.sub, tracking: 1.5 }, o)); }
  function NUM(c, s, x, y, o) { return txt(c, s, x, y, Object.assign({ size: 32, family: F.mono, color: C.paper }, o)); }
  const ATOMS = {
    /* 1 CV 跟踪框 */
    tracking(c, st, b, sp) {
      const L = 34, t = 2;
      /* 标签入场 = 括号从外收拢，1/8 拍（Figma 3:2 装置行为） */
      const k = clamp((st.t - st.entryBeat) / (st.ck.len / 8), 0, 1);
      if (k <= 0) return;
      const e = easeOutCubic(k);
      const ex = b.w * 0.16 * (1 - e), ey = b.h * 0.16 * (1 - e);
      const bx = b.x - ex, by = b.y - ey, bw = b.w + 2 * ex, bh = b.h + 2 * ey;
      c.fillStyle = C.paper;
      [[bx, by, 1, 1], [bx + bw, by, -1, 1], [bx, by + bh, 1, -1], [bx + bw, by + bh, -1, -1]]
        .forEach(function (q) {
          const px = q[0], py = q[1], sx = q[2], sy = q[3];
          c.fillRect(sx > 0 ? px : px - L, py - (sy > 0 ? 0 : t), L, t);
          c.fillRect(px - (sx > 0 ? 0 : t), sy > 0 ? py : py - L, t, L);
        });
      const label = sp.label || "对象 · 描述";
      if (k < 0.6) return;
      font(c, 11, "bold", F.sans, 1.5);
      const lw = c.measureText(label).width;
      c.fillStyle = C.paper;
      c.fillRect(b.x, b.y - 44 + 22 * k, lw + 16, 20);
      txt(c, label, b.x + 8, b.y - 42 + 22 * k, { size: 11, weight: "bold", color: C.ink, tracking: 1.5 });
    },
    /* 2 CV 微标签 */
    microtags(c, st, b, sp) {
      (sp.items || []).forEach(function (it, i) {
        const x = b.x + (i % 2) * 180, y = b.y + Math.floor(i / 2) * 40;
        font(c, 11, "medium", F.sans, 1.5);
        const w = c.measureText(it.t).width + 16;
        c.fillStyle = it.acc ? C.accent : C.panel;
        c.fillRect(x, y, w, 20);
        c.strokeStyle = C.line; c.lineWidth = 1;
        c.strokeRect(x + 0.5, y + 0.5, w - 1, 19);
        txt(c, it.t, x + 8, y + 2, { size: 11, weight: "medium", color: it.acc ? C.ink : C.sub, tracking: 1.5 });
      });
    },
    /* 3 图表卡 */
    chart(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.panel);
      MIC(c, sp.title || "图 00 · 主题", b.x + 24, b.y + 20, { color: C.paper, size: 13 });
      MIC(c, sp.meta || "", b.x + b.w - 24, b.y + 20, { align: "right", size: 11 });
      MIC(c, sp.base || "", b.x + b.w - 24, b.y + 44, { align: "right", size: 9 });
      const vals = sp.values || [], n = vals.length;
      const plotY = b.y + b.h - 76, plotH = b.h - 140;
      hair(c, b.x + 24, plotY, b.w - 48, 1, C.line);
      for (let i = 0; i < n; i++) {
        const gap = (b.w - 48) / n;
        /* 柱一根一拍地长起来（1/2 拍错峰），末柱落定在重拍上 */
        const g = clamp((st.t - (st.entryBeat + i * st.ck.len / 2)) / (st.ck.len * 0.25), 0, 1);
        if (g <= 0) continue;
        const bh = Math.max(2, plotH * (vals[i] / (sp.max || 150))) * g;
        c.fillStyle = i === n - 1 ? C.accent : "#2E343A";
        c.fillRect(b.x + 30 + i * gap, plotY - bh, gap * 0.62, bh);
      }
      (sp.axis || []).forEach(function (a, i, arr) {
        MIC(c, String(a), b.x + 24 + i * ((b.w - 48) / (arr.length - 1)), plotY + 8,
          { size: 9, family: F.mono, tracking: 1 });
      });
      if (sp.note) MIC(c, sp.note, b.x + 24, plotY - 96, { size: 11 });
      if (sp.value) txt(c, sp.value, b.x + b.w - 24, plotY - 104,
        { size: 20, family: F.mono, color: C.accent, align: "right", alpha: 0.72 + 0.28 * st.ck.pulse });
    },
    /* 4 洗护标签卡 */
    carelabel(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.paper);
      MIC(c, sp.title || "洗护标签 01 · 纤维成分", b.x + 24, b.y + 22, { color: C.ink, size: 13 });
      MIC(c, sp.code || "", b.x + b.w - 24, b.y + 22, { color: C.ink, align: "right", size: 11 });
      (sp.rows || []).forEach(function (r, i) {
        const y = b.y + 74 + i * 78;
        txt(c, r.k, b.x + 24, y, { size: 26, weight: "medium", color: C.ink });
        if (r.v !== undefined && r.v !== "") {
          txt(c, r.v, b.x + 150, y - 8, { size: 40, weight: "bold", color: C.ink });
        }
        MIC(c, r.pct || "", b.x + b.w - 24, y, { color: C.ink, align: "right", size: 12, family: F.mono });
      });
      MIC(c, sp.note || "", b.x + 40, b.y + b.h - 44, { color: C.ink, size: 9 });
    },
    /* 5 结构卡 */
    struct(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.panel);
      MIC(c, sp.title || "图 11 · 结构", b.x + 24, b.y + 20, { color: C.paper, size: 13 });
      MIC(c, sp.tag || "", b.x + b.w - 24, b.y + 20, { align: "right", size: 11 });
      (sp.layers || []).forEach(function (l, i) {
        const y = b.y + 66 + i * 92, ox = i * 14;
        c.save();
        c.transform(1, 0, -0.22, 1, 0, 0);
        c.fillStyle = "rgba(138,145,153,0.16)";
        c.fillRect(b.x + 24 + ox, y, b.w - 120, 46);
        c.restore();
        c.strokeStyle = C.line; c.lineWidth = 1;
        c.strokeRect(b.x + 24 + ox, y, b.w - 120, 46);
        txt(c, l.k, b.x + 34 + ox, y + 10, { size: 13, color: C.paper });
        if (l.v !== undefined && l.v !== "") MIC(c, l.v, b.x + 34 + ox, y + 28, { size: 11 });
      });
      if (sp.note) MIC(c, sp.note, b.x + 24, b.y + b.h - 40, { size: 9 });
    },
    /* 6 翻牌板 · 终场 */
    flapboard(c, st, b, sp) {
      const chars = (sp.text || "").split("");
      const total = chars.length * 30 - 4;
      let x = b.x + Math.max(0, (b.w - total) / 2);
      chars.forEach(function (ch, i) {
        const acc = sp.accent && sp.accent.indexOf(i) >= 0;
        /* 逐牌级联（Figma 4:121：每牌 30ms）+ 1 帧翻面：
         * 牌先立起来（scaleY 0.12→1），字在牌立到位后才显影。 */
        const t0 = st.entryBeat + i * 0.03;
        const p = clamp((st.t - t0) / (2 / 24), 0, 1);
        if (p <= 0) { x += 30; return; }
        c.save();
        c.translate(x + 13, b.y + 31);
        c.scale(1, 0.12 + 0.88 * easeOutCubic(p));
        c.translate(-(x + 13), -(b.y + 31));
        c.fillStyle = C.paper;
        c.fillRect(x, b.y, 26, 62);
        txt(c, ch, x + 13, b.y + 18, { size: 20, weight: "bold", align: "center",
          color: acc ? C.accent : C.ink, baselineOffset: 21, alpha: p > 0.45 ? 1 : 0 });
        c.restore();
        x += 30;
      });
      if (sp.note) MIC(c, sp.note, b.x, b.y + 86, { size: 9 });
      if (sp.line) MIC(c, sp.line, b.x, b.y + 130, { size: 12, color: C.accent, family: F.mono });
    },
    /* 7 字体模式样张 */
    fontmode(c, st, b, sp) {
      MIC(c, "masthead", b.x, b.y, { size: 12, family: F.mono, color: C.accent });
      txt(c, sp.masthead || "示例", b.x, b.y + 24, { size: 96, weight: "light" });
      MIC(c, "subtitle", b.x + 420, b.y, { size: 12, family: F.mono, color: C.accent });
      txt(c, sp.subtitle || "示例", b.x + 420, b.y + 30, { size: 28, tracking: 1 });
      MIC(c, "serif-caller", b.x, b.y + 160, { size: 12, family: F.mono, color: C.accent });
      txt(c, sp.caller1 || "示例", b.x, b.y + 184, { size: 40, family: F.serif, tracking: 2 });
      txt(c, sp.caller2 || "示例", b.x, b.y + 238, { size: 40, family: F.serif, tracking: 2 });
    },
    /* 8 收据卡 */
    receipt(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.paper);
      c.fillStyle = C.paperCard;
      for (let x = b.x; x < b.x + b.w - 8; x += 16) {
        c.beginPath();
        c.moveTo(x, b.y + b.h);
        c.lineTo(x + 8, b.y + b.h + 12);
        c.lineTo(x + 16, b.y + b.h);
        c.fill();
      }
      MIC(c, sp.head || "", b.x + 26, b.y + 26, { color: C.ink, size: 13 });
      MIC(c, sp.no || "", b.x + b.w - 26, b.y + 26, { color: C.ink, align: "right", size: 12 });
      MIC(c, sp.sub || "", b.x + 26, b.y + 46, { color: C.ink, size: 9 });
      txt(c, sp.big || "", b.x + 26, b.y + 94, { size: 36, weight: "bold", color: C.ink });
      (sp.rows || []).forEach(function (r, i) {
        const y = b.y + 200 + i * 28;
        MIC(c, r.k, b.x + 26, y, { color: C.ink, size: 12 });
        if (r.v !== undefined && r.v !== "") {
          txt(c, r.v, b.x + b.w - 26, y - 4, { size: 14, family: F.mono, color: r.old ? C.accent : C.ink, align: "right" });
        }
        if (r.old) { c.fillStyle = C.accent; c.fillRect(b.x + 26, y + 3, 150, 2); }
      });
      if (sp.pct) {
        MIC(c, sp.pct.k, b.x + 26, b.y + b.h - 220, { color: C.ink, size: 12 });
        txt(c, sp.pct.v, b.x + b.w - 26, b.y + b.h - 226, { size: 16, family: F.mono, color: C.accent, align: "right" });
      }
      if (sp.foot) MIC(c, sp.foot, b.x + 26, b.y + b.h - 192, { color: C.ink, size: 11 });
      barcode(c, b.x + 26, b.y + b.h - 150, 180, 46, 7.3);
      MIC(c, sp.stamp || "", b.x + b.w - 120, b.y + b.h - 130, { color: C.ink, size: 11 });
    },
    /* 9 通知卡（唯一圆角卡） */
    toast(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.navy);
      c.fillStyle = C.navy;
      c.globalAlpha = 0.9;
      c.beginPath();
      c.roundRect(b.x, b.y, b.w, b.h, 14);
      c.fill();
      c.globalAlpha = 1;
      MIC(c, sp.head || "", b.x + 56, b.y + 34, { color: C.paper, size: 12 });
      MIC(c, sp.time || "", b.x + b.w - 40, b.y + 34, { color: C.paper, align: "right", size: 13 });
      c.fillStyle = C.accent;
      c.globalAlpha = 0.55 + 0.45 * st.ck.pulse;
      c.beginPath(); c.arc(b.x + 34, b.y + 40, 5 + 1.5 * st.ck.pulse, 0, Math.PI * 2); c.fill();
      c.globalAlpha = 1;
      /* 实时计数（群消息 99+）：值踩在拍上跳，跳到目标那拍才补上「+」——
       * 于是「刷到九十九加」是唱到哪、数到哪，而不是随便滚个数字。 */
      if (sp.count) {
        const c0 = sp.count, beats = st.beats || [], vals = c0.values || [];
        let k = 0, at = null;
        for (let i = 0; i < beats.length; i++) {
          if (beats[i] >= c0.t0 && beats[i] < st.t) { k++; at = beats[i]; }
        }
        if (k > 0) {
          const vNow = vals[Math.min(k - 1, vals.length - 1)];
          const vPrev = k >= 2 ? vals[Math.min(k - 2, vals.length - 1)] : 0;
          const plus = c0.plusAt !== undefined && st.t >= c0.plusAt;
          const sNow = String(vNow) + (plus ? "+" : "");
          const sPrev = String(vPrev) + (plus ? "+" : "");
          const numOpt = { size: 34, weight: "bold", family: F.mono, color: C.accent };
          const p = clamp((st.t - at) / (3 / 24), 0, 1);
          if (sNow !== sPrev && p < 1) rollText(c, sPrev, sNow, b.x + 56, b.y + 62, 44, p, numOpt);
          else txt(c, sNow, b.x + 56, b.y + 70, numOpt);
          if (sp.unit) {
            font(c, 34, "bold", F.mono, 0);
            MIC(c, sp.unit, b.x + 56 + c.measureText(sNow).width + 10, b.y + 78, { size: 14 });
          }
        }
      } else {
        txt(c, sp.title || "", b.x + 56, b.y + 68, { size: 30, weight: "medium", color: C.paper });
      }
      txt(c, sp.body || "", b.x + 56, b.y + 114, { size: 20, color: C.paper });
      (sp.rows || []).forEach(function (r, i) {
        MIC(c, r, b.x + 56, b.y + 210 + i * 26, { color: C.paper, size: 13 });
      });
    },
    /* 10 终端窗口（删除=亮粉删除线，新增=纸白；不用红绿） */
    terminal(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.term);
      hair(c, b.x, b.y + 56, b.w, 1, C.line);
      c.fillStyle = C.accent;
      c.beginPath(); c.arc(b.x + 24, b.y + 28, 6, 0, Math.PI * 2); c.fill();
      txt(c, sp.title || "Claude Code", b.x + 42, b.y + 20, { size: 16, color: C.paper });
      MIC(c, sp.path || "", b.x + 170, b.y + 22, { color: C.sub, size: 13, family: F.mono });
      MIC(c, sp.model || "", b.x + b.w - 24, b.y + 22, { color: C.sub, size: 13, family: F.mono, align: "right" });
      let y = b.y + 80;
      (sp.lines || []).forEach(function (l, i) {
        /* 逐字打出：第 i 行落后 i 拍，行内字符在一拍内打完 */
        const rp = st.rowP(i);
        if (rp <= 0) return;
        const full = l.t || "";
        const t = full.slice(0, Math.max(1, Math.ceil(full.length * Math.min(1, rp * 1.6))));
        const a = Math.min(1, rp * 3);
        if (l.kind === "del") {
          font(c, 15, "normal", F.mono, 1);
          const w = c.measureText(t).width;
          txt(c, t, b.x + 40, y, { size: 15, family: F.mono, color: C.paper, tracking: 1, alpha: 0.75 * a });
          /* 删除线在词尾音节处落下（rp 过半才划线） */
          c.globalAlpha = rp > 0.6 ? 1 : 0;
          c.fillStyle = C.accent;
          c.fillRect(b.x + 40, y + 14, w, 2);
          c.globalAlpha = 1;
          if ("letterSpacing" in c) c.letterSpacing = "0px";
        } else {
          txt(c, t, b.x + 40, y, {
            size: 15, family: F.mono, tracking: 1,
            color: l.kind === "add" ? C.paper : C.sub, alpha: a,
          });
        }
        y += 30;
      });
      hair(c, b.x, b.y + b.h - 60, b.w, 1, C.line);
      txt(c, ">", b.x + 40, b.y + b.h - 46, { size: 15, family: F.mono, color: C.sub });
      if (Math.floor(st.t * 2) % 2 === 0) {
        c.fillStyle = C.paper;
        c.fillRect(b.x + 62, b.y + b.h - 48, 8, 18);
      }
      MIC(c, sp.hint || "", b.x + b.w - 40, b.y + b.h - 46, { color: C.sub, size: 13, align: "right" });
    },
    /* 11 清单卡（逐行打勾，勾落 = 一拍） */
    checklist(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.paper);
      MIC(c, sp.title || "", b.x + 30, b.y + 34, { color: C.ink, size: 13 });
      MIC(c, sp.meta || "", b.x + b.w - 30, b.y + 34, { color: C.ink, size: 11, align: "right" });
      const k = st.beatsBetween(st.shot.t0, st.t);
      (sp.rows || []).forEach(function (r, i) {
        const y = b.y + 84 + i * 62;
        const p = st.rowP(i);
        if (p <= 0) return;
        withAlpha(Math.min(1, p * 2.5), function () {
          txt(c, r.k, b.x + 70, y, { size: 18, weight: "medium", color: C.ink, baselineOffset: 19 });
          /* 清单里不是每行都有「值」——空值不许打出 undefined（2026-10-02 实拍抓到） */
          if (r.v !== undefined && r.v !== "") {
            txt(c, r.v, b.x + b.w - 30, y, { size: 17, family: F.mono, color: r.acc ? C.accent : C.ink, align: "right", baselineOffset: 18 });
          }
        });
        /* 勾落 = 一拍：勾在本行落定后出现 */
        if (p > 0.5) txt(c, "✓", b.x + 30, y, { size: 20, weight: "bold", color: C.ink, baselineOffset: 20 });
      });
      if (sp.note) MIC(c, sp.note, b.x + 30, b.y + b.h - 40, { color: C.ink, size: 11 });
    },
    /* 12 弧形仪表 */
    gauge(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.panel);
      const cx = b.x + b.w / 2, cy = b.y + b.h - 90, r = 150;
      c.strokeStyle = C.line; c.lineWidth = 2;
      c.beginPath(); c.arc(cx, cy, r, Math.PI, 2 * Math.PI); c.stroke();
      c.strokeStyle = C.accent; c.lineWidth = 8;
      c.beginPath(); c.arc(cx, cy, r, Math.PI * 1.72, 2 * Math.PI); c.stroke();
      const p = clamp((st.t * 0.37) % 1, 0, 1);
      const pb = clamp((st.t - st.entryBeat) / st.ck.len * 0.16, 0, 1);
      const pn = clamp(pb + 0.06 * st.ck.pulse, 0, 1);
      c.strokeStyle = C.paper; c.lineWidth = 3;
      c.beginPath();
      c.moveTo(cx, cy);
      c.lineTo(cx + Math.cos(Math.PI + Math.PI * pn) * (r - 16), cy + Math.sin(Math.PI + Math.PI * pn) * (r - 16));
      c.stroke();
      MIC(c, "0", cx - r, cy - 16, { size: 9, family: F.mono });
      MIC(c, "100", cx + r - 22, cy - 16, { size: 9, family: F.mono });
      MIC(c, sp.unit || "", cx - 22, cy - 54, { size: 12 });
      txt(c, String(Math.round(pn * 100)).padStart(3, "0"), cx, cy + 34,
        { size: 52, family: F.mono, color: C.paper, align: "center", baselineOffset: 52 });
    },
    /* 13 开关组（toggle 是唯一圆角控件） */
    toggles(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.panel);
      txt(c, sp.title || "锁定模式", b.x + b.w / 2, b.y + 34, { size: 16, color: C.paper, align: "center" });
      const on = Math.floor(st.t / 0.25) % 2 === 0;
      c.fillStyle = on ? C.accent : C.line;
      c.beginPath(); c.roundRect(b.x + b.w / 2 + 30, b.y + 62, 44, 22, 11); c.fill();
      c.fillStyle = C.paper;
      c.beginPath(); c.arc(b.x + b.w / 2 + (on ? 64 : 40), b.y + 73, 8, 0, Math.PI * 2); c.fill();
      MIC(c, on ? "ON" : "OFF", b.x + b.w / 2 + 84, b.y + 68, { color: on ? C.accent : C.sub, size: 14, family: F.mono });
      (sp.rows || []).forEach(function (r, i) {
        const y = b.y + 140 + i * 44;
        txt(c, r.k, b.x + 30, y, { size: 14, color: C.paper });
        if (r.v !== undefined && r.v !== "") {
          txt(c, r.v, b.x + b.w - 30, y, { size: 15, family: F.mono, color: C.sub, align: "right" });
        }
      });
      (sp.notes || []).forEach(function (n, i) {
        MIC(c, n, b.x + 30, b.y + b.h - 66 + i * 24, { size: 12 });
      });
    },
    /* 14 等级阶梯卡（「你」的亮粉点逐层上移） */
    ladder(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.panel);
      MIC(c, sp.title || "", b.x + 26, b.y + 20, { color: C.paper, size: 13 });
      MIC(c, sp.tag || "", b.x + b.w - 26, b.y + 20, { align: "right", size: 13 });
      const rows = sp.rows || [];
      rows.forEach(function (r, i) {
        const y = b.y + 60 + i * 50;
        hair(c, b.x + 26, y, b.w - 52, 1, C.line);
        txt(c, r, b.x + 26, y + 8, { size: 14, color: C.paper });
      });
      const prog = clamp((st.t - st.shot.t0) / Math.max(0.1, st.shot.t1 - st.shot.t0), 0, 1);
      const yy = b.y + 60 + (rows.length - 1) * 50 * (1 - prog);
      c.fillStyle = C.accent;
      c.beginPath(); c.arc(b.x + 16, yy + 14, 5, 0, Math.PI * 2); c.fill();
      if (sp.dv) MIC(c, sp.dv, b.x + 190, b.y + 60, { size: 12 });
      if (sp.note) MIC(c, sp.note, b.x + 26, b.y + b.h - 36, { size: 11 });
    },
    /* 15 扫描仪卡 */
    scanner(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.panel);
      MIC(c, sp.title || "扫描仪 · 原型机", b.x + 26, b.y + 20, { color: C.paper, size: 13 });
      MIC(c, sp.meta || "", b.x + b.w - 26, b.y + 20, { align: "right", size: 11 });
      MIC(c, sp.sub || "", b.x + 26, b.y + 44, { size: 11 });
      const prog = clamp((st.t - st.shot.t0) / Math.max(0.1, st.shot.t1 - st.shot.t0), 0, 1);
      const total = sp.total || 120;
      MIC(c, "切片", b.x + 26, b.y + 96, { size: 12 });
      txt(c, String(Math.max(1, Math.round(prog * total))).padStart(3, "0"), b.x + 26, b.y + 112,
        { size: 40, family: F.mono, color: C.accent, baselineOffset: 42 });
      MIC(c, "/ " + total, b.x + 132, b.y + 138, { size: 16, family: F.mono });
      const cx = b.x + b.w - 120, cy = b.y + b.h / 2;
      for (let i = 0; i < 12; i++) {
        if (i / 12 > prog) break;
        c.strokeStyle = "rgba(245,245,242," + (0.15 + 0.05 * i).toFixed(2) + ")";
        c.lineWidth = 1;
        c.beginPath(); c.ellipse(cx, cy, 40 - i * 2.6, 84 - i * 5.6, 0, 0, Math.PI * 2); c.stroke();
      }
      txt(c, sp.status || "", b.x + 26, b.y + b.h - 100, { size: 13, color: C.paper });
      MIC(c, sp.plat || "", b.x + 26, b.y + b.h - 72, { size: 13, color: C.accent });
    },
    /* 16 标本卡 */
    specimen(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.paper);
      MIC(c, sp.title || "", b.x + 26, b.y + 24, { color: C.ink, size: 12, family: F.mono });
      MIC(c, sp.tag || "", b.x + b.w - 26, b.y + 24, { color: C.ink, align: "right", size: 12 });
      txt(c, sp.big || "", b.x + 26, b.y + 62, { size: 44, weight: "bold", color: C.ink });
      txt(c, sp.from || "", b.x + b.w - 150, b.y + 74, { size: 20, family: F.mono, color: C.ink, align: "right" });
      txt(c, sp.value || "", b.x + 26, b.y + 126, { size: 32, family: F.mono, color: C.accent });
      (sp.rows || []).forEach(function (r, i) {
        const y = b.y + 214 + i * 38;
        MIC(c, r.k, b.x + 26, y, { color: C.ink, size: 12 });
        if (r.v !== undefined && r.v !== "") MIC(c, r.v, b.x + b.w - 26, y, { color: C.ink, align: "right", size: 13 });
      });
    },
    /* 17 音频工程卡（波形按真实音频 + 回声衰减条） */
    mix(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.paper);
      MIC(c, sp.title || "图 10 · 音乐退场", b.x + 26, b.y + 20, { color: C.ink, size: 13 });
      MIC(c, sp.tag || "OUTRO", b.x + b.w - 26, b.y + 20, { color: C.ink, align: "right", size: 13 });
      MIC(c, "0 dB", b.x + 26, b.y + 52, { color: C.ink, size: 9, family: F.mono });
      MIC(c, "-12", b.x + 26, b.y + 108, { color: C.ink, size: 9, family: F.mono });
      hair(c, b.x + 70, b.y + 58, b.w - 96, 1, "rgba(11,13,16,0.25)");
      hair(c, b.x + 70, b.y + 114, b.w - 96, 1, "rgba(11,13,16,0.25)");
      const env = st.envelope;
      c.fillStyle = "rgba(11,13,16,0.72)";
      const span = Math.max(1, st.shot.t1 - st.shot.t0);
      for (let i = 0; i < 90; i++) {
        let lv = 0.4;
        if (env && env.env && env.env.length) {
          lv = env.env[clamp(Math.floor(((st.t - st.shot.t0) % span + i * 0.05) / env.dt), 0, env.env.length - 1)];
        } else lv = hash(i) * 0.7;
        c.fillRect(b.x + 70 + i * 5, b.y + 86 - lv * 28, 3, lv * 56);
      }
      (sp.marks || []).forEach(function (m, i) {
        txt(c, m, b.x + 190 + i * 180, b.y + 50, { size: 11, color: C.ink, family: F.mono });
      });
      if (sp.call) txt(c, sp.call, b.x + 160, b.y + 176, { size: 14, color: C.accent });
      (sp.taps || []).forEach(function (w, i) {
        c.globalAlpha = [1, 0.65, 0.4, 0.22][i] || 0.2;
        txt(c, w, b.x + 44 + i * 120, b.y + 340, {
          size: 16, family: F.mono,
          color: i === (sp.taps.length - 1) ? C.accent : C.ink,
        });
      });
      c.globalAlpha = 1;
      MIC(c, sp.note || "", b.x + 26, b.y + b.h - 40, { color: C.ink, size: 9 });
    },
    /* 18 引线标注 + 虚线轮廓 */
    leader(c, st, b, sp) {
      (sp.items || []).forEach(function (it) {
        const px = b.x + it.px, py = b.y + it.py;
        c.strokeStyle = C.paper; c.lineWidth = 1;
        c.beginPath();
        c.moveTo(px, py);
        c.lineTo(px + 60, py - 60);
        c.lineTo(px + 150, py - 60);
        c.stroke();
        c.fillStyle = C.paper;
        c.beginPath(); c.arc(px, py, 3, 0, Math.PI * 2); c.fill();
        MIC(c, it.t, px + 62, py - 90, { color: C.paper, size: 13 });
      });
      if (sp.dash) {
        c.setLineDash([2, 8]);
        c.strokeStyle = C.paper; c.lineWidth = 1;
        c.beginPath();
        c.ellipse(b.x + b.w / 2, b.y + b.h / 2, b.w * 0.22, b.h * 0.34, 0, 0, Math.PI * 2);
        c.stroke();
        c.setLineDash([]);
      }
    },
    /* 19 环形仪表（环从 0 扫到值，扫满 = 重拍） */
    donut(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.panel);
      const cx = b.x + 190, cy = b.y + b.h / 2, r = 110;
      c.strokeStyle = C.line; c.lineWidth = 26;
      c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.stroke();
      /* 环从 0 扫到值，扫满 = 重拍：一个环扫 4 拍 */
      const p = clamp((st.t - st.entryBeat) / (st.ck.len * 4), 0, 1);
      /* sp.value = 这张卡要表达的那个比例（0–1）：环扫到 value 就停，
       * 中心数字报的也是 value（否则"废片率 60%"会一路扫成 100%，数字就撒了谎）。 */
      const val = (sp.value === undefined ? 1 : sp.value);
      c.strokeStyle = C.paper; c.lineWidth = 26;
      c.beginPath(); c.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * p * val); c.stroke();
      txt(c, Math.round(p * val * 100) + "%", cx, cy - 22, { size: 26, family: F.mono, color: C.paper, align: "center", baselineOffset: 26 });
      (sp.legend || []).forEach(function (l, i) {
        const y = b.y + 90 + i * 90;
        txt(c, l.k, b.x + 340, y, { size: 18, color: C.paper });
        txt(c, l.v, b.x + 340, y + 32, { size: 14, family: F.mono, color: C.sub });
        c.fillStyle = C.line; c.fillRect(b.x + 340, y + 58, b.w - 380, 6);
        c.fillStyle = i === 0 ? C.paper : C.accent;
        c.fillRect(b.x + 340, y + 58, (b.w - 380) * l.p, 6);
      });
    },
    /* 20 删除线字处理（旧词划 2px 亮粉线，新词用强调色） */
    strike(c, st, b, sp) {
      const step = st.ck.len / 4;
      const parts = sp.parts || [];
      let x = b.x;
      parts.forEach(function (p, i) {
        const e = clamp((st.t - (st.entryBeat + i * step)) / (step * 0.6), 0, 1);
        font(c, 40, "bold", F.sans, 2);
        const w = c.measureText(p.t).width;
        if (e > 0) txt(c, p.t, x, b.y, {
          size: 40, weight: "bold", tracking: 2, alpha: Math.min(1, e * 2),
          color: p.old ? C.paper : C.accent,
        });
        if (p.old) {
          const sweep = clamp((st.t - (st.entryBeat + (i + 0.5) * step)) / (step * 0.8), 0, 1);
          if (sweep > 0) { c.fillStyle = C.accent; c.fillRect(x, b.y + 30, w * sweep, 2); }
        }
        x += w + 10;
      });
      const pn = clamp((st.t - (st.entryBeat + parts.length * step)) / (step * 0.6), 0, 1);
      if (pn > 0) withAlpha(pn, function () { MIC(c, sp.note || "", b.x, b.y + 80, { size: 12 }); });
    },
    /* 21 回声堆叠（每层 = 一个 1/4 音符，逐层降 opacity，末层强调色） */
    echo(c, st, b, sp) {
      const word = sp.word || "", n = sp.taps || 4, gap = sp.gap || 56;
      for (let i = 0; i < n; i++) {
        const p = clamp((st.t - (st.entryBeat + i * st.ck.len / 4)) / (st.ck.len / 8), 0, 1);
        if (p <= 0) continue;
        withAlpha(([1, 0.65, 0.4, 0.22][i] || 0.2) * Math.min(1, p * 2), function () {
          txt(c, word, b.x, b.y + i * gap, { size: 40, weight: "bold", color: i === n - 1 ? C.accent : C.paper });
          MIC(c, "TAP " + (i + 1) + " · " + (sp.db ? sp.db[i] : ""), b.x + 220, b.y + i * gap + 12,
            { size: 11, family: F.mono });
        });
      }
      c.globalAlpha = 1;
      const pn = clamp((st.t - (st.entryBeat + n * st.ck.len / 4)) / (st.ck.len / 8), 0, 1);
      if (pn > 0) withAlpha(pn, function () { MIC(c, sp.note || "", b.x, b.y + n * gap + 30, { size: 11 }); });
    },
    /* 旧 board 的 dataCard → Figma 面板卡样式（数值仍随拍跳动，每个数字必须真实） */
    stat(c, st, b, sp) {
      frost(c, b.x, b.y, b.w, b.h, MAT.panel);
      const K = Math.max(1, st.beatsBetween(st.shot.t0, st.shot.t1));
      const k = st.beatsBetween(st.shot.t0, st.t);
      const frac = clamp(k / K, 0, 1);
      MIC(c, sp.label || "", b.x + 26, b.y + 24, { color: C.paper, size: 13 });
      txt(c, Math.round(sp.start + (sp.end - sp.start) * frac).toLocaleString("en-US"), b.x + 26, b.y + 58,
        { size: 48, family: F.mono, color: C.accent, baselineOffset: 50 });
      hair(c, b.x + 26, b.y + b.h - 40, b.w - 52, 1, C.line);
      c.fillStyle = C.accent;
      c.fillRect(b.x + 26, b.y + b.h - 40, (b.w - 52) * (1 - frac), 1);
      MIC(c, "T0 " + sp.start + "  ->  T1 " + sp.end + "   beat " + k + "/" + K,
        b.x + 26, b.y + b.h - 28, { size: 11, family: F.mono });
    },
  };
  /* ---------- 视觉层入口（引擎每帧调用一次，位于印刷 pass 之后） ---------- */
  /* 关键帧查表（线性插值）：跟踪框跟着画面里的实体走时用 */
  function kfAt(kf, u) {
    if (u <= kf[0].t) return kf[0];
    const last = kf[kf.length - 1];
    if (u >= last.t) return last;
    let lo = 0, hi = kf.length - 1;
    while (hi - lo > 1) {
      const m = (lo + hi) >> 1;
      if (kf[m].t <= u) lo = m; else hi = m;
    }
    const a = kf[lo], b = kf[hi];
    const k = (u - a.t) / (b.t - a.t);
    return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k };
  }
  /* 意义层卡片：支持一镜多卡（cards[]）、显式进出时刻（enterAt/exitAt）、
   * 以及贴画面的跟踪框（kf 关键帧，走底图层同一套 cover-fit 变换） */
  function drawCard(c, st, spec) {
    if (!spec || !ATOMS[spec.atom]) return;
    const at = spec.enterAt === undefined ? st.entryBeat : spec.enterAt;
    if (st.t < at) return;
    if (spec.exitAt !== undefined && st.t >= spec.exitAt) return;
    const still = spec.noEnter === true;
    /* 入场相位按「这张卡自己的入场时刻」算：晚入场的卡也能有自己的落下与显影，
       而不是一律跟着镜头入口拍（多卡同镜时必须这样） */
    const pe = clamp((st.t - at) / (st.ck.len * 0.25), 0, 1);
    const rev = still ? 1
      : clamp((st.t - at) / (st.ck.len * (st.visual.revealBeats || 1)), 0, 1);
    let w = spec.w || 640, h = spec.h || 260, bx, by, drop = 0;
    if (spec.kf && spec.kf.length && st.xf) {
      const k = kfAt(spec.kf, st.t - (st.t0 || 0));
      const sc = st.xf.s;
      w = (spec.kw || 240) * sc;
      h = (spec.kh || 180) * sc;
      bx = k.x * sc + st.xf.ox - w / 2;
      by = k.y * sc + st.xf.oy - h / 2;
    } else {
      drop = still ? 0 : 28 * (1 - easeOutCubic(pe));
      bx = spec.x === undefined ? 64 : spec.x;
      by = (spec.y === undefined ? 776 - h : spec.y) - drop;
    }
    c.save();
    c.beginPath();
    c.rect(bx - 4, by - 4, w + 8, Math.max(2, h * Math.max(0.02, rev)) + 8 + drop);
    c.clip();
    /* 原子件自己的动效必须从**它自己的入场时刻**起算（2026-10-02）：
     * 表里的 chart / donut / strike / echo / gauge / checklist / terminal / stat / ladder
     * 都拿 st.entryBeat 当相位零点。若沿用它 = 镜头的入场拍，中段才落下的卡一出现就是终态
     * （环已经扫满、柱子全长好、字已经打完）——那样"多卡同镜"就全成了静物。
     * 这里临时把 entryBeat 换成这张卡自己的入场拍，画完还原。 */
    const savedEntryBeat = st.entryBeat;
    st.entryBeat = at;
    ATOMS[spec.atom](c, st, { x: bx, y: by, w: w, h: h }, spec);
    st.entryBeat = savedEntryBeat;
    c.restore();
  }
  function render(c, st) {
    if (st.visual && st.visual.accent) C.accent = st.visual.accent;   // 换章节强调色（默认亮粉 #FF5FAF）
    st.ck = beatClock(st);
    /* 歌词状态要在 chrome 之前算好：大字段落要让 chrome 让位（底板叠在 HUD 之上） */
    st.lyric = LYRIC.state(st);
    /* 字幕 v3 的行计划：shots.json 的 visual.lyrics.lines 优先，没有才退回 lines.json */
    st.lyricPlan = planLines(st);
    _LAST_ST = st;
    if (st.shot) {
      const entryBeat = st.nextBeatAfter(st.shot.t0);                 // 入场一律落在拍上
      st.entryBeat = entryBeat;
      st.enter = clamp((st.t - entryBeat) / (st.ck.len * 0.25), 0, 1);          // 1/4 拍滑入
      st.reveal = clamp((st.t - entryBeat) / (st.ck.len * (st.visual.revealBeats || 1)), 0, 1);
      st.rowP = function (i) {                                        // 第 i 行落后 i 拍
        return clamp((st.t - (entryBeat + i * st.ck.len)) / (st.ck.len * 0.5), 0, 1);
      };
    }
    chrome(c, st);
    sectionEvent(c, st);
    const s = st.shot;
    if (!s) return;
    /* 默认落在翻牌长条（y=788）之上，避免压住 chrome；board 可用 spec.x / spec.y 覆盖。
     * 整卡从上方落入（1/4 拍）+ 内容自顶向下的点阵式显影（1 拍），都与节拍对齐。 */
    const specs = s.cards || (s.card ? [s.card]
      : (s.dataCard ? [Object.assign({ atom: "stat" }, s.dataCard)] : []));
    specs.forEach(function (spec) { drawCard(c, st, spec); });
    if (s.captionMode === "coverline") coverline(c, st);
    else if (s.captionMode === "masthead") masthead(c, st);
    else if (s.captionMode === "caller") caller(c, st);
    else if (s.captionMode === "mass") mass(c, st);
    else if (s.captionMode === "subtitle-plain") subtitle(c, st);   // v1 老样式，保留作退路
    else LYRIC.render(c, st);                                        // 情绪化歌词层
  }
  window.VISUAL = {
    C: C, MAT: MAT, F: F, ATOMS: ATOMS, render: render,
    setup: function (cv) { mainCv = cv; },
    /* 只读诊断接口（不参与绘制）：给 tools/qc_lines_boxes.js 验
     * 「某个时刻到底是哪一行在屏上、它的入场/离场是不是自洽」。 */
    debugLines: function (t) {
      const st = _LAST_ST;
      if (!st || !st.lyricPlan) return null;
      const probe = Object.assign({}, st, { t: t });
      return st.lyricPlan.map(function (P, i) {
        const s0 = P.chars[0].t;
        const e0 = lineEnd(P, probe);
        return { i: i, style: P.style, zone: P.L.zone, text: P.text,
          s0: s0, e0: e0, last: P.chars[P.chars.length - 1].e,
          lastT: P.chars[P.chars.length - 1].t,
          gate: (P.L.gate === undefined ? null : P.L.gate),
          active: (t >= s0 && t < e0) };
      });
    },
  };
})();
