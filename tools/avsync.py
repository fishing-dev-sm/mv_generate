#!/usr/bin/env python3
"""口型漂移测量（A/V sync drift detector）。

输入「AI 视频 clip 的音轨」和「参考人声切片」，输出同步质量报告（JSON）：
- 先对两条音轨做全局对齐（全长包络 NCC -> global_lag）
- 再在滑动窗口（默认 250ms，hop 125ms）内做归一化互相关，得峰值与局部 lag
- 第一个相关度跌破阈值（默认 0.45）的覆盖窗口 = 漂移点

相关度基于振幅包络（hilbert 包络降采样到 1kHz），而不是原始波形：
原始波形对 ±几个样本的拉伸就失相关，无法定位漂移；包络 NCC 对口型
同步误差（几十毫秒量级）敏感且对微小变速稳健，是 lip-sync 测量的常用做法。

用法：
    avsync.py CLIP_AUDIO REF_AUDIO [--out report.json]
            [--window 0.25] [--hop 0.125] [--threshold 0.45] [--raw]

两条输入都经 ffmpeg 转 16kHz mono wav 后处理；只用 numpy/scipy。
--raw 可切回原始波形模式（仅适合验证完全同步的素材）。
"""
import argparse
import json
import subprocess
import tempfile

import numpy as np
from scipy.signal import fftconvolve, hilbert

SR = 16000
ENV_SR = 1000  # 包络采样率


def load_wav(path):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp = tf.name
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", path,
         "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", tmp],
        check=True)
    import wave
    with wave.open(tmp, "rb") as w:
        n = w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float64) / 32768.0
    subprocess.run(["rm", "-f", tmp])
    return data


def envelope(x):
    env = np.abs(hilbert(x))
    # 20ms 滑动平均低通，再降采样到 ENV_SR
    k = int(0.02 * SR)
    env = np.convolve(env, np.ones(k) / k, mode="same")
    dec = SR // ENV_SR
    return env[::dec]


def ncc_full(a, b, max_lag):
    """归一化互相关，lag ∈ [-max_lag, +max_lag]（单位：样本）。

    lag > 0 表示 b 相对 a 晚（b 需左移 lag 对齐 a）。返回 (peak, lag)。
    """
    a = a - a.mean()
    b = b - b.mean()
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm < 1e-9:
        return 0.0, 0
    corr = fftconvolve(a, b[::-1], mode="full") / norm
    center = len(b) - 1
    lo = max(0, center - max_lag)
    hi = min(len(corr), center + max_lag + 1)
    seg = corr[lo:hi]
    k = int(np.argmax(seg))
    return float(seg[k]), lo + k - center


def global_align(clip, ref, sr, anchor_s=3.0):
    """用前 anchor_s 秒做锚定对齐：返回 (lag_samples, peak)。

    漂移测量的前提假设是「开头对齐、后面漂」。全长 NCC 遇到匀速拉伸的
    素材会找到一个虚假的全局最优 lag，所以只用开头一段做锚定。
    lag > 0 = clip 内容相对 ref 晚出现。
    """
    n = int(min(anchor_s * sr, len(clip), len(ref)))
    max_lag = int(1.0 * sr)  # 锚定最多容忍 ±1s 的起始偏移
    peak, lag = ncc_full(clip[:n], ref[:n], min(max_lag, n - 1))
    return lag, peak


def analyze(clip, ref, window, hop, threshold, sr):
    nw = int(window * sr)
    nh = int(hop * sr)
    max_lag = int(0.05 * sr)  # 全局对齐后每窗最多再校 ±50ms
    g_lag, g_corr = global_align(clip, ref, sr)
    frames = []
    pos = 0
    while pos + nw <= len(clip):
        r0 = pos - g_lag
        covered = r0 >= 0 and r0 + nw <= len(ref)
        if not covered:
            frames.append({"t": round(pos / sr, 4), "corr": None,
                           "lag_ms": None, "covered": False})
        else:
            peak, lag = ncc_full(clip[pos:pos + nw], ref[r0:r0 + nw], max_lag)
            frames.append({"t": round(pos / sr, 4),
                           "corr": round(peak, 4),
                           "lag_ms": round(lag / sr * 1000.0, 2),
                           "covered": True})
        pos += nh

    drift_t = None
    for fr in frames:
        if fr["covered"] and fr["corr"] < threshold:
            drift_t = fr["t"]
            break
    cov = [f for f in frames if f["covered"]]
    corrs = np.array([f["corr"] for f in cov]) if cov else np.array([0.0])
    lags = np.array([abs(f["lag_ms"]) for f in cov])
    return {
        "summary": {
            "n_frames": len(frames),
            "n_covered": len(cov),
            "global_lag_ms": round(g_lag / sr * 1000.0, 2),
            "global_corr": round(g_corr, 4),
            "mean_corr": round(float(corrs.mean()), 4),
            "min_corr": round(float(corrs.min()), 4),
            "mean_abs_lag_ms": round(float(lags.mean()), 2) if len(lags) else None,
            "drift_point_s": drift_t,
            "in_sync": drift_t is None,
        },
        "frames": frames,
    }


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("clip", help="AI 视频 clip 的音轨（任意 ffmpeg 可读格式）")
    p.add_argument("ref", help="参考人声切片")
    p.add_argument("--out", help="报告输出 JSON 路径（默认只打印摘要）")
    p.add_argument("--window", type=float, default=0.25, help="滑窗秒数（默认 0.25）")
    p.add_argument("--hop", type=float, default=0.125, help="hop 秒数（默认 0.125）")
    p.add_argument("--threshold", type=float, default=0.45, help="漂移阈值（默认 0.45）")
    p.add_argument("--raw", action="store_true",
                   help="用原始波形做相关（默认用振幅包络）")
    args = p.parse_args()

    clip = load_wav(args.clip)
    ref = load_wav(args.ref)
    if args.raw:
        c_sig, r_sig, sr = clip, ref, SR
        mode = "raw-waveform"
    else:
        c_sig, r_sig, sr = envelope(clip), envelope(ref), ENV_SR
        mode = "envelope-1k"
    report = analyze(c_sig, r_sig, args.window, args.hop, args.threshold, sr)
    report["params"] = {"mode": mode, "window_ms": args.window * 1000,
                        "hop_ms": args.hop * 1000, "threshold": args.threshold}
    report["inputs"] = {"clip": args.clip, "ref": args.ref,
                        "clip_duration_s": round(len(clip) / SR, 3),
                        "ref_duration_s": round(len(ref) / SR, 3)}
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[ok] 报告 -> {args.out}")
    s = report["summary"]
    print(f"global_lag_ms={s['global_lag_ms']}  global_corr={s['global_corr']}  "
          f"mean_corr={s['mean_corr']}  min_corr={s['min_corr']}  "
          f"drift_point_s={s['drift_point_s']}  in_sync={s['in_sync']}")


if __name__ == "__main__":
    main()
