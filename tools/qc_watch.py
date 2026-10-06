#!/usr/bin/env python3
"""QC 管线驱动器：监视量产报告 → 逐段机检 → sung 重定时 → 全链衔接验收。

用法：
    venv/bin/python tools/qc_watch.py --segs c01,i01,c02,c03
    venv/bin/python tools/qc_watch.py --all
    venv/bin/python tools/qc_watch.py --segs c01 --no-wait
    venv/bin/python tools/qc_watch.py --segs i01 --recheck

信号：生成侧在 clips/final/segments-report.json 写 {sid: {gen_min, verdict:"pending_qc"}}。
本工具只读该报告；产物写进 clips/final/qc/ 与 clips/final/{sid}-frames/。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mass_produce as mp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINAL = os.path.join(ROOT, "clips", "final")
QC = os.path.join(FINAL, "qc")
REPORT = os.path.join(FINAL, "segments-report.json")
VERDICTS = os.path.join(QC, "verdicts.json")
QCMD = os.path.join(QC, "QC-REPORT.md")

SR = 16000


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def read_json(path, default=None):
    """容错读：生成侧 json.dump 非原子写，正好撞上会读到半截。"""
    for _ in range(5):
        try:
            return json.load(open(path))
        except FileNotFoundError:
            return default
        except Exception:
            time.sleep(0.5)
    return default


def ffprobe_dur(path):
    p = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", path])
    try:
        return round(float(p.stdout.strip()), 3)
    except Exception:
        return None


def load_segments():
    return json.load(open(os.path.join(ROOT, "segments.json")))["segments"]


def load_wordfix():
    return json.load(open(os.path.join(ROOT, "song/analysis/words-fixed.json")))


def seg_by_id(sid):
    return next(s for s in load_segments() if s["id"] == sid)


def lyrics_for(sid, wf):
    seg = seg_by_id(sid)
    return mp.lyrics_in_window(seg["window"][0], seg["window"][1], wf)


def expected_cuts(seg):
    """prompt 里真实存在的硬切点。code 镜（不在 SHOTS 表）不属 H3 责任。"""
    real = [s for s in seg["shots"] if s in mp.SHOTS]
    t0 = seg["window"][0]
    return [round(mp.BOARD_T0[s] - t0, 2) for s in real[1:]]


def sung_shots_of(seg):
    """§14 判据：段内演唱镜 = shots ∩ SING_SHOTS。

    段级 seg["sung"] 只标了 6 个独立演唱段，容器段里的演唱镜
    （s004/s006/s013/s015/s022/s024/s028/s035/s043/s044/s049/s052/s053/s054）
    会被漏掉，进而退回 §8.2 明令禁止的恒定 frameOffset。
    """
    return [s for s in seg["shots"] if s in mp.SING_SHOTS]


def shot_local_window(seg, shot):
    """镜相对 seg.window[0] 的局部时间窗 [start, end]（秒）。"""
    w0, w1 = seg["window"]
    real = [s for s in seg["shots"] if s in mp.SHOTS]
    i = real.index(shot)
    a = max(mp.BOARD_T0.get(shot, w0), w0) - w0
    b = (mp.BOARD_T0[real[i + 1]] if i + 1 < len(real) else w1) - w0
    return round(a, 4), round(b, 4)


def cut_wav(src, out, start, dur):
    """把 src 的 [start, start+dur) 裁成 16k 单声道 wav（输出端精确 seek）。"""
    sh(["ffmpeg", "-y", "-v", "error", "-i", src, "-ss", "%.4f" % start,
        "-t", "%.4f" % dur, "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", out])
    return os.path.exists(out) and os.path.getsize(out) > 2000


def extract_frames(mp4, outdir):
    os.makedirs(outdir, exist_ok=True)
    if os.path.exists(os.path.join(outdir, "f0000.png")):
        return len([f for f in os.listdir(outdir) if f.endswith(".png")])
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp4, "-vf", "fps=24",
                    "-start_number", "0", os.path.join(outdir, "f%04d.png")],
                   check=True)
    return len([f for f in os.listdir(outdir) if f.endswith(".png")])


def detect_events(mp4, filt, key):
    p = sh(["ffmpeg", "-v", "info", "-i", mp4, "-vf", filt, "-f", "null", "-"])
    return [round(float(x), 2) for x in re.findall(key + r":\s*([\d.]+)", p.stderr)]


def frame_cuts(frames_dir, min_delta=6.0):
    """逐帧灰度差分找硬切点。
    2026-10-01 c02 实测：暗场硬切（礼堂→深夜房间）在 ffmpeg scene 滤波下
    分数落在 0.1–0.35，`select='gt(scene,0.35)'` 直接漏检；逐帧差分不会。
    返回 (候选切点秒, 最大差分 top5)。
    """
    import glob
    from PIL import Image
    fs = sorted(glob.glob(os.path.join(frames_dir, "f*.png")))
    diffs, prev = [], None
    for f in fs:
        a = np.asarray(Image.open(f).convert("L").resize((336, 192)), dtype=float)
        if prev is not None:
            diffs.append(float(np.abs(a - prev).mean()))
        prev = a
    if not diffs:
        return [], []
    med = float(np.median(diffs))
    thr = max(min_delta, med * 4)
    merged = []
    for i, dv in enumerate(diffs):
        if dv >= thr:
            t = round((i + 1) / 24.0, 2)
            if merged and t - merged[-1] <= 0.12:
                merged[-1] = t
            else:
                merged.append(t)
    top = [round(x, 2) for x in sorted(diffs, reverse=True)[:5]]
    return merged, top


def band_envelope(path):
    """300–3400Hz 带限 → 包络（5Hz 低通）→ 100Hz 采样。"""
    import tempfile
    import wave
    from scipy.signal import butter, sosfiltfilt
    tf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tf.close()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-ac", "1",
                    "-ar", str(SR), "-c:a", "pcm_s16le", tf.name], check=True)
    with wave.open(tf.name, "rb") as w:
        n = w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(float) / 32768
    os.unlink(tf.name)
    sos = butter(4, [300, 3400], btype="bandpass", fs=SR, output="sos")
    x = sosfiltfilt(sos, x)
    env = np.abs(x)
    lpf = butter(4, 5, btype="lowpass", fs=SR, output="sos")
    env = sosfiltfilt(lpf, env)
    decim = SR // 100
    env = env[: len(env) // decim * decim].reshape(-1, decim).mean(axis=1)
    return env, 1.0 / 100


def timemap_ncc(clip, ref, pairs):
    """§8.2 择优线：映射窗 250ms 带限包络 NCC 均值（≥0.5 过线）。"""
    from retime_clip import interp_map
    ec, dc = band_envelope(clip)
    er, dr = band_envelope(ref)
    tc = np.arange(len(ec)) * dc
    tr = np.arange(len(er)) * dr
    half, step = 0.125, 0.01
    offs = np.arange(-half, half + 1e-9, step)
    scores = []
    t = half
    while t <= tr[-1] - half:
        rv = np.interp(t + offs, tr, er)
        cv = np.interp(interp_map(pairs, t + offs), tc, ec)
        if rv.std() > 1e-6 and cv.std() > 1e-6:
            scores.append(float(np.corrcoef(rv, cv)[0, 1]))
        t += 0.05
    a = np.array(scores)
    if not len(a):
        return {"n_windows": 0, "mean": None, "p25": None, "min": None}
    return {"n_windows": int(len(a)), "mean": round(float(a.mean()), 3),
            "p25": round(float(np.percentile(a, 25)), 3),
            "min": round(float(a.min()), 3)}


def _norm_words(ws, n=5):
    return ["".join(str(w).split()).lower() for w in (ws or [])[:n]]


def words_look_same(a, b, n=4, need=2):
    """两串转写是否"说的是同一句"。

    为什么这么松：whisper 在密集 techno 人声上转写极不稳定（纪律 §5），
    同一段音频两次转写都可能给出不同汉字。这里只取前 n 词做**按序**比对、
    命中 need 个即算同一句——用来兜"期望歌词行落点越界"的假阴性，
    真正的对齐质量仍由 NCC 门把关。
    """
    A, B = _norm_words(a, n), _norm_words(b, n)
    k = min(len(A), len(B))
    if k == 0:
        return False
    same = sum(1 for x, y in zip(A, B) if x and y and (x == y or x in y or y in x))
    return same >= min(need, k)


def qc_sung(sid, mp4, ref_wav, wf):
    """§8.2 工序 2–5：首词淘汰线 → DTW timemap → NCC 门槛。"""
    import wordsync
    out = {"ref": os.path.relpath(ref_wav, ROOT)}
    lyr = lyrics_for(sid, wf)
    out["lyrics_prompt"] = lyr[:80]
    words = {}
    for model in ("medium", "small"):
        try:
            w = wordsync.transcribe_words(mp4, model, initial_prompt=lyr)
            words[model] = [x["word"].strip() for x in w[:6]]
        except Exception as e:
            words[model] = ["<err " + str(e)[:60] + ">"]
    out["first_words"] = words
    first = (words.get("medium") or [""])[0]
    want = (lyr.split() or [""])[0]
    out["first_word_expected"] = want
    out["first_word_ok"] = bool(first) and (want in first or first in want)
    if re.search(r"[A-Za-z]", first or ""):
        out["first_word_octet"] = "含拉丁字母（英文/vlog 幻觉）"
    if not out["first_word_ok"]:
        # 回退判据：歌词行在窗内的落点常有 reanchor 误差（"期望首词"其实落在窗外），
        # 此时改判"clip 是否忠实复现参考音频"——同起点转写 ref，词面一致即过。
        try:
            rw = wordsync.transcribe_words(ref_wav, "medium", initial_prompt=lyr)
            ref_words = [x["word"].strip() for x in rw[:6]]
        except Exception as e:
            ref_words = ["<err " + str(e)[:50] + ">"]
        out["ref_first_words"] = ref_words
        out["first_word_ok_refmatch"] = words_look_same(words.get("medium"), ref_words)
        out["first_word_ok"] = out["first_word_ok"] or out["first_word_ok_refmatch"]
    tm = os.path.join(QC, sid + "-timemap.json")
    ws = os.path.join(QC, sid + "-wordsync.json")
    seg = seg_by_id(sid)
    sh([os.path.join(ROOT, "venv/bin/python"), "tools/wordsync.py", mp4,
        "--ref-words", "song/analysis/words-fixed.json",
        "--ref-t0", str(seg["window"][0]), "--lyrics", lyr, "--out", ws], cwd=ROOT)
    r = sh([os.path.join(ROOT, "venv/bin/python"), "tools/retime_clip.py", mp4,
            ref_wav, "--wordsync", ws, "--out", tm, "--shot-id", sid], cwd=ROOT)
    out["retime_log"] = [l for l in r.stdout.splitlines() if l.startswith("[qc]")]
    out["timemap"] = os.path.relpath(tm, ROOT)
    out["timemap_exists"] = os.path.exists(tm)
    if out["timemap_exists"]:
        tmj = json.load(open(tm))
        out["timemap_monotone"] = tmj.get("monotone")
        out["timemap_qc"] = tmj.get("qc")
        out["ncc"] = timemap_ncc(mp4, ref_wav, tmj["pairs"])
        out["ncc_pass"] = (out["ncc"]["mean"] or 0) >= 0.5
    out["note"] = "sung 素材机器只粗筛，人耳终审（纪律 §5）"
    return out


def qc_sung_shot(sid, seg, shot, mp4, ref_wav, wf):
    """容器段内的单镜 sung 质检：首词淘汰线 → 镜级 DTW timemap → NCC 门槛。

    timemap 口径与引擎一致（handover §0.4 / §14）：
        x = 镜内时间（相对 shot 起点；向前留 0.5s 余量故可为负）
        y = 段内 clip 时间（clip 从 seg.window[0] 起算）
    引擎取帧：clipT = interp_map(shot_t - shot.t0)。
    """
    w0, _ = seg["window"]
    a, b = shot_local_window(seg, shot)
    pad = 0.5
    a2 = max(0.0, a - pad)          # 输入音频的段内起点
    dur = (b + pad) - a2
    abs0 = w0 + a2                  # 输入音频在歌曲里的绝对起点
    out = {"shot": shot, "local_window": [a, b], "card": "shot",
           "ref": os.path.relpath(ref_wav, ROOT)}
    lyr = mp.lyrics_in_window(w0 + a, w0 + b, wf)
    out["lyrics_prompt"] = lyr[:120]
    out["first_word_expected"] = (lyr.split() or [""])[0]
    tmp = tempfile.mkdtemp(prefix="qcsung-")
    clip_w = os.path.join(tmp, "clip.wav")
    ref_w = os.path.join(tmp, "ref.wav")
    if not (cut_wav(mp4, clip_w, a2, dur) and cut_wav(ref_wav, ref_w, a2, dur)):
        out["error"] = "cut wav 失败（clip 或 ref 太短）"
        return out
    import wordsync
    words = {}
    for model in ("medium", "small"):
        try:
            w = wordsync.transcribe_words(clip_w, model, initial_prompt=lyr)
            words[model] = [x["word"].strip() for x in w[:6]]
        except Exception as e:
            words[model] = ["<err " + str(e)[:60] + ">"]
    out["first_words"] = words
    first = (words.get("medium") or [""])[0]
    want = out["first_word_expected"]
    out["first_word_ok"] = bool(first) and (want in first or first in want)
    if re.search(r"[A-Za-z]", first or ""):
        out["first_word_octet"] = "含拉丁字母（英文/vlog 幻觉）"
    if not out["first_word_ok"]:
        # 回退判据（同 qc_sung）：容器段镜窗内的歌词落点常越界，
        # 改判"clip 是否忠实复现参考音频"——同起点（同样带 0.5s 前摇）转写 ref，词面一致即过。
        try:
            rw = wordsync.transcribe_words(ref_w, "medium", initial_prompt=lyr)
            ref_words = [x["word"].strip() for x in rw[:6]]
        except Exception as e:
            ref_words = ["<err " + str(e)[:50] + ">"]
        out["ref_first_words"] = ref_words
        out["first_word_ok_refmatch"] = words_look_same(words.get("medium"), ref_words)
        out["first_word_ok"] = out["first_word_ok"] or out["first_word_ok_refmatch"]
    tm = os.path.join(QC, sid + "-" + shot + "-timemap.json")
    ws = os.path.join(QC, sid + "-" + shot + "-wordsync.json")
    sh([os.path.join(ROOT, "venv/bin/python"), "tools/wordsync.py", clip_w,
        "--ref-words", "song/analysis/words-fixed.json", "--ref-t0", "%.4f" % abs0,
        "--lyrics", lyr, "--out", ws], cwd=ROOT)
    r = sh([os.path.join(ROOT, "venv/bin/python"), "tools/retime_clip.py", clip_w,
            ref_w, "--wordsync", ws, "--out", tm, "--shot-id", shot], cwd=ROOT)
    out["retime_log"] = [l for l in r.stdout.splitlines() if l.startswith("[qc]")]
    out["timemap"] = os.path.relpath(tm, ROOT)
    out["timemap_exists"] = os.path.exists(tm)
    if out["timemap_exists"]:
        tmj = json.load(open(tm))
        raw = tmj["pairs"]                      # 输入音频（起点 a2）坐标系
        out["timemap_monotone"] = tmj.get("monotone")
        out["timemap_qc"] = tmj.get("qc")
        out["ncc"] = timemap_ncc(clip_w, ref_w, raw)
        out["ncc_pass"] = (out["ncc"]["mean"] or 0) >= 0.5
        # 回基到镜/段坐标系：x -= (a - a2)，y += a2
        tmj["pairs"] = [[round(float(x) - (a - a2), 4), round(float(y) + a2, 4)]
                        for x, y in raw]
        tmj["rebased"] = {"shot_local": True, "a": a, "a2": a2,
                          "clip_start_in_song": w0}
        json.dump(tmj, open(tm, "w"), ensure_ascii=False)
    out["note"] = "sung 素材机器只粗筛，人耳终审（纪律 §5）"
    return out


def qc_segment(sid, seg, wf):
    mp4 = os.path.join(FINAL, sid + ".mp4")
    frames = os.path.join(FINAL, sid + "-frames")
    exp_dur = round(seg["frames"] / 24.0, 3)
    ss = sung_shots_of(seg)
    d = {"sid": sid, "kind": seg["kind"], "shots": seg["shots"],
         "window": seg["window"], "sung": bool(ss), "sung_shots": ss,
         "expected_dur": exp_dur, "expected_frames": seg["frames"]}
    d["dur"] = ffprobe_dur(mp4)
    d["dur_ok"] = d["dur"] is not None and d["dur"] >= exp_dur - 0.05
    d["size_bytes"] = os.path.getsize(mp4)
    n = extract_frames(mp4, frames)
    d["frames_dir"] = os.path.relpath(frames, ROOT)
    d["frames_extracted"] = n
    d["frames_ok"] = n >= seg["frames"] - 1
    d["motion_pct"] = mp.qc_motion(frames)
    d["motion_ok"] = d["motion_pct"] >= 3.0
    d["freezes"] = detect_events(mp4, "freezedetect=n=0.003:d=1.0", "freeze_start")
    d["blacks"] = detect_events(mp4, "blackdetect=d=0.2:pix_th=0.10", "black_start")
    d["expected_cuts"] = expected_cuts(seg)
    cuts, _ = mp.qc_scene_cuts(mp4, d["expected_cuts"])
    d["scene_cuts_ffmpeg"] = cuts
    fc, topd = frame_cuts(frames)
    d["measured_cuts"], d["framediff_top5"] = fc, topd
    # 两法取并集：ffmpeg scene 在高对比切点灵，逐帧差分在小/暗场切点灵
    cand = sorted(set(fc) | set(cuts))
    d["cuts_ok"] = all(any(abs(c - e) <= 1.0 for c in cand) for e in d["expected_cuts"])
    d["cuts_dev"] = [round(min((abs(c - e) for c in cand), default=99.0), 2)
                     for e in d["expected_cuts"]]
    if seg["plates"]:
        d["firstframe_graydiff"] = mp.qc_firstframe(frames, seg["plates"][0])
    picks = [0, n // 4, n // 2, (3 * n) // 4, max(n - 1, 0)]
    d["sample_frames"] = [os.path.relpath(os.path.join(frames, "f%04d.png" % i), ROOT)
                          for i in sorted(set(picks)) if i < n]
    if ss:
        ref_wav = os.path.join(ROOT, "ref-audio-v3", sid + ".wav")
        real = [s for s in seg["shots"] if s in mp.SHOTS]
        if len(real) <= 1:
            d["sung_qc"] = qc_sung(sid, mp4, ref_wav, wf)
        else:
            d["sung_qc_shots"] = [qc_sung_shot(sid, seg, sh, mp4, ref_wav, wf)
                                  for sh in ss]
    return d


def build_concat(segs, tag):
    """raw 直串（§10.2 导演最终验收口径）：不改时序、不垫歌。"""
    lst = os.path.join(QC, "concat-" + tag + ".txt")
    with open(lst, "w") as f:
        for s in segs:
            f.write("file '" + os.path.join(FINAL, s["id"] + ".mp4") + "'\n")
    out = os.path.join(QC, "concat-" + tag + ".mp4")
    p = sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", lst, "-c", "copy", out])
    if p.returncode != 0:
        sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", lst, "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", out])
    return out


def seam_check(segs, tag):
    """逐接缝机检：±0.5s 音频连续性（真静音断点即接缝硬伤）。"""
    import wave
    rows = []
    for a, b in zip(segs, segs[1:]):
        pa = os.path.join(FINAL, a["id"] + ".mp4")
        pb = os.path.join(FINAL, b["id"] + ".mp4")
        da, db = ffprobe_dur(pa), ffprobe_dur(pb)
        tail = "/tmp/seam_" + a["id"] + "_tail.wav"
        head = "/tmp/seam_" + b["id"] + "_head.wav"
        sh(["ffmpeg", "-y", "-v", "error", "-ss", str(max((da or 0) - 0.5, 0)),
            "-i", pa, "-t", "0.5", "-ac", "1", "-ar", "16000", tail])
        sh(["ffmpeg", "-y", "-v", "error", "-i", pb, "-t", "0.5",
            "-ac", "1", "-ar", "16000", head])
        with wave.open(tail, "rb") as w:
            t = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
        with wave.open(head, "rb") as w:
            h = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
        rt = float(np.sqrt((t ** 2).mean())) if len(t) else 0.0
        rh = float(np.sqrt((h ** 2).mean())) if len(h) else 0.0
        rows.append({"seam": a["id"] + "->" + b["id"],
                     "tail_rms": round(rt, 4), "head_rms": round(rh, 4),
                     "silence_gap": bool(rt < 0.005 or rh < 0.005),
                     "dur_prev": da, "dur_next": db})
        for p in (tail, head):
            if os.path.exists(p):
                os.unlink(p)
    out = os.path.join(QC, "seams-" + tag + ".json")
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=2)
    return out, rows


def write_md(d):
    L = []
    L.append("\n## " + d["sid"] + " · " + d["kind"] + " · "
             + ("sung" if d["sung"] else "silent/none")
             + " · shots=" + "+".join(d["shots"]) + "\n")
    L.append("- 窗口 %.2f–%.2fs · 期望 %ss/%df · 实测 %ss（%s）/ 抽帧 %d（%s）"
             % (d["window"][0], d["window"][1], d["expected_dur"],
                d["expected_frames"], d["dur"],
                "OK" if d["dur_ok"] else "**不足**", d["frames_extracted"],
                "OK" if d["frames_ok"] else "**缺帧**"))
    L.append("- 动态 %s%%（%s）· freeze=%s · black=%s · 首帧锚灰度差 %s"
             % (d["motion_pct"], "OK" if d["motion_ok"] else "**疑似静帧**",
                d["freezes"], d["blacks"], d.get("firstframe_graydiff")))
    L.append("- 硬切点 期望 %s 实测(逐帧差分) %s 实测(scene) %s 偏差 %s → %s"
             % (d["expected_cuts"], d["measured_cuts"], d["scene_cuts_ffmpeg"],
                d.get("cuts_dev"), "OK" if d["cuts_ok"] else "**偏差>1.0s**"))
    L.append("  （code 镜切点属引擎层，不计；两法取并集，暗场硬切靠逐帧差分捕捉）")
    if d.get("sung_qc"):
        s = d["sung_qc"]
        L.append("- sung 首词 期望「%s」medium=%s → %s%s"
                 % (s["first_word_expected"], s["first_words"].get("medium"),
                    "OK" if s.get("first_word_ok") else "**淘汰线不过**",
                    (" ⛔" + s["first_word_octet"]) if s.get("first_word_octet") else ""))
        L.append("- DTW monotone=%s dev=%ss · NCC mean=%s p25=%s → %s"
                 % (s.get("timemap_monotone"),
                    (s.get("timemap_qc") or {}).get("dev_mean"),
                    (s.get("ncc") or {}).get("mean"), (s.get("ncc") or {}).get("p25"),
                    "过线" if s.get("ncc_pass") else "**低于 0.5**"))
    for s in d.get("sung_qc_shots", []):
        if s.get("error"):
            L.append("- sung 镜 %s ⛔ %s" % (s["shot"], s["error"]))
            continue
        L.append("- sung 镜 %s（段内 %.2f–%.2fs）首词 期望「%s」medium=%s → %s%s"
                 % (s["shot"], s["local_window"][0], s["local_window"][1],
                    s["first_word_expected"], s["first_words"].get("medium"),
                    "OK" if s.get("first_word_ok") else "**淘汰线不过**",
                    (" ⛔" + s["first_word_octet"]) if s.get("first_word_octet") else "")
                 + ("（回退判据：与 ref 同窗词面一致 ✓）" if s.get("first_word_ok_refmatch") else ""))
        L.append("-   DTW 镜级 monotone=%s dev=%ss · NCC mean=%s p25=%s → %s · %s"
                 % (s.get("timemap_monotone"),
                    (s.get("timemap_qc") or {}).get("dev_mean"),
                    (s.get("ncc") or {}).get("mean"), (s.get("ncc") or {}).get("p25"),
                    "过线" if s.get("ncc_pass") else "**低于 0.5**", s.get("timemap")))
    L.append("- 采样帧（人眼合板用）：" + ", ".join(d["sample_frames"]))
    L.append("- **机器判据**：见上；sung 段口型/音色须导演耳测终审"
             if d["sung"] else "- **机器判据**：见上")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segs", default="c01,i01,c02,c03")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--poll", type=int, default=25)
    ap.add_argument("--timeout", type=int, default=180, help="等待单段落地下来的上限（分钟）")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--no-concat", action="store_true")
    args = ap.parse_args()

    os.makedirs(QC, exist_ok=True)
    mp._load_board_t0()
    all_segs = load_segments()
    want = all_segs if args.all else [s for s in all_segs
                                      if s["id"] in set(args.segs.split(","))]
    tag = args.tag or ("all" if args.all else str(len(want)))
    wf = load_wordfix()
    if not os.path.exists(QCMD):
        with open(QCMD, "w") as f:
            f.write("# QC 报告 —— 示例项目 A（重制品）\n\n"
                    "> 由 `tools/qc_watch.py` 逐段追加。机器判据为粗筛，"
                    "sung 段口型/音色一律导演耳测终审（纪律 §5）。\n")

    dead = time.time() + args.timeout * 60
    for seg in want:
        sid = seg["id"]
        jf = os.path.join(QC, sid + ".json")
        if os.path.exists(jf) and not args.recheck:
            print("[skip] " + sid + " 已检过（--recheck 重检）", flush=True)
            continue
        mp4 = os.path.join(FINAL, sid + ".mp4")
        while not args.no_wait:
            rep = read_json(REPORT, {}) or {}
            ent = rep.get(sid, {})
            if ent.get("gen_min") and os.path.exists(mp4):
                break
            if time.time() > dead:
                print("[timeout] 等 " + sid + " 落地超时", flush=True)
                return 2
            print("[wait] " + sid + " 未落地（report=" + str(ent.get("verdict")) + "）…",
                  flush=True)
            time.sleep(args.poll)
        print("\n===== QC " + sid + " =====", flush=True)
        d = qc_segment(sid, seg, wf)
        gates = [d["dur_ok"], d["frames_ok"], d["motion_ok"], d["cuts_ok"],
                 not d["freezes"]]
        if d.get("sung_qc"):
            gates += [d["sung_qc"]["first_word_ok"], d["sung_qc"]["ncc_pass"]]
        for sq in d.get("sung_qc_shots", []):
            gates += [bool(sq.get("first_word_ok")), bool(sq.get("ncc_pass"))]
        d["verdict_suggest"] = "pass" if all(gates) else "fail"
        json.dump(d, open(jf, "w"), ensure_ascii=False, indent=2)
        with open(QCMD, "a") as f:
            f.write(write_md(d))
        v = json.load(open(VERDICTS)) if os.path.exists(VERDICTS) else {}
        v[sid] = {"verdict": d["verdict_suggest"], "machine": True,
                  "needs_director": bool(d["sung"]),
                  "note": "机器建议；sung 段须耳测，最终裁决权在导演"}
        json.dump(v, open(VERDICTS, "w"), ensure_ascii=False, indent=2)
        print("[qc] " + sid + " -> " + d["verdict_suggest"]
              + " (dur=" + str(d["dur"]) + " frames=" + str(d["frames_extracted"])
              + " motion=" + str(d["motion_pct"]) + "% cuts=" + str(d["measured_cuts"]) + ")",
              flush=True)

    if not args.no_concat:
        ready = [s for s in want if os.path.exists(os.path.join(FINAL, s["id"] + ".mp4"))]
        if len(ready) == len(want):
            out = build_concat(want, tag)
            sf, rows = seam_check(want, tag)
            with open(QCMD, "a") as f:
                f.write("\n## 全链验收（" + tag + "）\n\n")
                f.write("- raw 直串 `" + os.path.relpath(out, ROOT)
                        + "`（" + str(round(ffprobe_dur(out) or 0, 2))
                        + "s，§10.2 导演验收口径）\n")
                f.write("- 接缝机检 `" + os.path.relpath(sf, ROOT) + "`："
                        + "；".join(r["seam"] + " tail/head RMS "
                                    + str(r["tail_rms"]) + "/" + str(r["head_rms"])
                                    + (" ⛔静音断点" if r["silence_gap"] else "")
                                    for r in rows) + "\n")
            print("[ok] concat -> " + out + "\n[ok] seams -> " + sf, flush=True)
    print("[done] QC 段数=" + str(len(want)), flush=True)


if __name__ == "__main__":
    main()
