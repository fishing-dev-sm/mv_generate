#!/usr/bin/env python3
"""H3 sung clip 的非线性重定时：DTW 帧级对齐 clip 音轨 ↔ 参考人声切片。

背景：H3 音频参考生成的是自己的演绎，与参考人声可能是变速关系（内部节奏
漂移），恒定 frameOffset 只能对齐一个锚点。本工具用 DTW 生成
ref_t → clip_t 的时间映射表（timemap JSON），引擎按映射逐帧取 clip 帧，
实现逐词级口型对齐。

流程：
1. 两路音频 16kHz mono → 人声带限（300–3400Hz，躲开 EDM 低频节拍）
2. 特征：MFCC(13)+Δ，拼接 onset strength 通道，逐通道归一化
3. librosa.sequence.dtw 得规整路径 → 单调映射 ref_t → clip_t
4. 质检：单调性、路径偏差、用 wordsync 逐词表算重定时后残差
   （词对 dt 标准差应从数百 ms 降到 <60ms）

用法：
    venv/bin/python tools/retime_clip.py CLIP.mp4 REF.wav \
        --wordsync out/wordsync-xxx.json --out timemap/xxx.json [--plot xxx.png]
"""
import argparse
import json

import numpy as np

SR = 16000
HOP = 256          # 16ms / 帧
N_MFCC = 13


def load_bandlimited(path):
    import subprocess, tempfile, wave
    tf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tf.close()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path,
                    "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", tf.name],
                   check=True)
    w = wave.open(tf.name, "rb")
    n = w.getnframes()
    x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(float) / 32768
    subprocess.run(["rm", "-f", tf.name])
    from scipy.signal import butter, sosfiltfilt
    sos = butter(4, [300, 3400], btype="bandpass", fs=SR, output="sos")
    return sosfiltfilt(sos, x)


def features(x):
    import librosa
    mfcc = librosa.feature.mfcc(y=x.astype(np.float32), sr=SR, n_mfcc=N_MFCC,
                                hop_length=HOP, n_fft=1024)
    delta = librosa.feature.delta(mfcc)
    onset = librosa.onset.onset_strength(y=x.astype(np.float32), sr=SR,
                                         hop_length=HOP)
    onset = onset.reshape(1, -1)
    F = np.vstack([mfcc, delta, onset * 3.0])     # onset 加权
    F = (F - F.mean(axis=1, keepdims=True)) / (F.std(axis=1, keepdims=True) + 1e-8)
    return F


def build_timemap(wp, hop, sr, smooth_win=15):
    """wp: (n,2) DTW 路径 [X_idx(clip), Y_idx(ref)] → 单调 ref_t→clip_t 对。
    smooth_win: 对路径相对对角线的偏差做滑动平均（端点保持原值），
    去 DTW 抖动后重新单调化。"""
    clip_t = wp[:, 0] * hop / sr
    ref_t = wp[:, 1] * hop / sr
    # 均匀重采样路径到 ~10ms 密度，逐 ref_t 取平均 clip_t（去抖）
    grid = np.arange(ref_t.min(), ref_t.max() + 1e-9, 0.01)
    idx = np.searchsorted(ref_t, grid, side="right") - 1
    idx = np.clip(idx, 0, len(ref_t) - 1)
    ct = clip_t[idx]
    base = grid + (ct[0] - grid[0])
    dev = ct - base
    if smooth_win and smooth_win > 1:
        k = np.ones(smooth_win) / smooth_win
        dev_s = np.convolve(dev, k, mode="same")
        dev_s[:smooth_win] = dev[:smooth_win]
        dev_s[-smooth_win:] = dev[-smooth_win:]
    else:
        dev_s = dev
    ct = np.maximum.accumulate(base + dev_s)
    pairs = [[round(float(r), 4), round(float(c), 4)] for r, c in zip(grid, ct)]
    return pairs


def interp_map(pairs, x):
    rs = np.array([p[0] for p in pairs])
    cs = np.array([p[1] for p in pairs])
    return np.interp(x, rs, cs)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip")
    ap.add_argument("ref")
    ap.add_argument("--out", required=True, help="timemap JSON 输出")
    ap.add_argument("--wordsync", help="wordsync 报告 JSON（残差质检）")
    ap.add_argument("--shot-id", default="")
    ap.add_argument("--smooth", type=int, default=15, help="偏差滑动平均窗口（0.01s 单位）")
    ap.add_argument("--plot", help="路径偏差 PNG 输出（需 matplotlib，可选）")
    args = ap.parse_args()

    import librosa
    xc = load_bandlimited(args.clip)
    xr = load_bandlimited(args.ref)
    Fc, Fr = features(xc), features(xr)
    print(f"[feat] clip {Fc.shape} ref {Fr.shape}")
    D, wp = librosa.sequence.dtw(X=Fc, Y=Fr, metric="cosine")
    wp = wp[::-1]                       # 时间正序
    print(f"[dtw] path len={len(wp)} cost={float(D[-1, -1]):.2f}")

    pairs = build_timemap(wp, HOP, SR, args.smooth)

    # 质检 1：单调性
    cs = np.array([p[1] for p in pairs])
    rs = np.array([p[0] for p in pairs])
    mono = bool(np.all(np.diff(cs) >= -1e-9))
    print(f"[qc] pairs={len(pairs)} ref {rs[0]:.2f}..{rs[-1]:.2f}s "
          f"clip {cs[0]:.2f}..{cs[-1]:.2f}s monotone={mono}")

    # 质检 2：路径相对对角线的偏差
    dev = cs - (rs + (cs[0] - rs[0]))
    print(f"[qc] deviation from diagonal: mean={dev.mean():+.3f}s "
          f"min={dev.min():+.3f} max={dev.max():+.3f} std={dev.std():.3f}")

    # 质检 3：wordsync 词对残差（重定时前 vs 后）
    sync = None
    if args.wordsync:
        rep = json.load(open(args.wordsync))
        ps = [p for p in rep["pairs"] if abs(p.get("score", 0)) >= 1]
        if len(ps) >= 2:
            before = np.array([p["dt"] for p in ps])
            after = np.array([interp_map(pairs, p["ref_start"]) - p["clip_start"]
                              for p in ps])
            sync = {
                "n": len(ps),
                "before_dt": [round(float(x), 3) for x in before],
                "after_residual": [round(float(x), 3) for x in after],
                "before_std": round(float(before.std()), 3),
                "after_std": round(float(after.std()), 3),
                "after_abs_max": round(float(np.abs(after).max()), 3),
            }
            print(f"[qc] wordsync n={len(ps)}: dt std "
                  f"{before.std():.3f}s -> residual std {after.std():.3f}s "
                  f"(max |res| {np.abs(after).max():.3f}s)")

    out = {
        "shot_id": args.shot_id,
        "clip": args.clip,
        "ref": args.ref,
        "sr": SR, "hop": HOP,
        "monotone": mono,
        "pairs": pairs,
        "qc": {"dev_mean": round(float(dev.mean()), 4),
               "dev_std": round(float(dev.std()), 4),
               "wordsync": sync},
    }
    with open(args.out, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"[ok] timemap -> {args.out}")

    if args.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(2, 1, figsize=(10, 6))
            ax[0].plot(rs, cs, lw=1)
            ax[0].plot(rs, rs + (cs[0] - rs[0]), "--", c="gray", lw=0.8)
            ax[0].set_xlabel("ref_t (s)"); ax[0].set_ylabel("clip_t (s)")
            ax[0].set_title(f"timemap {args.shot_id}")
            ax[1].plot(rs, dev, lw=1)
            ax[1].axhline(0, c="gray", lw=0.8)
            ax[1].set_xlabel("ref_t (s)"); ax[1].set_ylabel("deviation (s)")
            fig.tight_layout()
            fig.savefig(args.plot, dpi=110)
            print(f"[ok] plot -> {args.plot}")
        except ImportError:
            print("[warn] matplotlib unavailable, skip plot")


if __name__ == "__main__":
    main()
