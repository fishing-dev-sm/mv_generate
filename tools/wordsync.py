#!/usr/bin/env python3
"""口型对齐测量（word-level sync）：clip 音轨 vs 参考人声切片的逐词起音差。

方法（对 sung 人声的标准做法，替代会被 BPM 节拍周期欺骗的包络互相关）：
1. 对 clip 音轨和参考切片分别跑 faster-whisper（word_timestamps=True,
   vad_filter=False），得逐词起音时间。
2. 宽松匹配共同词：归一化后完全相等 / 编辑距离 ≤2 / 包含关系（听写近似容忍）。
3. 保序双指针滑动匹配（±max_dt 秒窗口），dt = clip词起音 - 参考词起音，
   输出 median、逐词对照表、稳定性（>0.5s 的跳变词）。

用法：
    # 参考端用已知逐词时间（推荐：参考就是我们自己的歌，words-fixed.json 即真值）
    venv/bin/python tools/wordsync.py CLIP.mp4 --ref-words song/analysis/words-fixed.json \
        --ref-t0 68.20 [--lyrics "示例 示例 美得嗷嗷叫"] [--out report.json]
    # 或参考端也走转录（外部参考才需要）
    venv/bin/python tools/wordsync.py CLIP.mp4 REF.wav [--out report.json]

判定：median 即 frameOffset 实测值（符号约定：嘴比参考晚为正）；
有效匹配词数 <3 视为测量失败。

注意：sung 人声务必给 --lyrics 作为 initial_prompt 偏置转录，
裸转录唱词会出大量听写垃圾；包络互相关（avsync.py）对 sung 人声
会被 BPM 节拍周期欺骗，只适用于无人声纯音乐。
"""
import argparse
import json
import re
import subprocess
import tempfile


def load_audio(path):
    tf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tf.close()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path,
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", tf.name],
                   check=True)
    return tf.name


def transcribe_words(path, model_name, initial_prompt=None):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    wav = load_audio(path)
    kwargs = dict(language="zh", word_timestamps=True, vad_filter=False,
                  beam_size=5, condition_on_previous_text=False)
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    segments, _ = model.transcribe(wav, **kwargs)
    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"word": w.word, "start": round(float(w.start), 3),
                          "end": round(float(w.end), 3)})
    return words


def ref_words_from_json(path, t0, t1, max_dt):
    """words-fixed.json 转切片相对时间的词表（只取与切片重叠的词）。"""
    data = json.load(open(path))
    out = []
    for w in data["words"]:
        st = w["start"] - t0
        if st >= -max_dt and st <= (t1 - t0) + max_dt:
            out.append({"word": w["word"], "start": round(st, 3),
                        "end": round(w["end"] - t0, 3)})
    return out


def norm(w):
    return re.sub(r"[\s\W_]+", "", w.lower())


def edit_dist(a, b):
    if abs(len(a) - len(b)) > 2:
        return 99
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[0] + 1, prev + (ca != cb))
            prev = cur
    return dp[-1]


def match_score(a, b):
    """0 = 不匹配, 1..3 = 弱→强"""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0
    if na == nb:
        return 3
    if len(na) >= 2 and len(nb) >= 2 and (na in nb or nb in na):
        return 2
    if edit_dist(na, nb) <= 2:
        return 1
    return 0


def match_words(ref_words, clip_words, max_dt):
    """保序匹配：每个参考词在 ±max_dt 内找最强的未占用 clip 词。"""
    pairs = []
    used = set()
    j0 = 0
    for rw in ref_words:
        best, best_j = 0, -1
        for j in range(j0, len(clip_words)):
            cw = clip_words[j]
            if cw["start"] - rw["start"] > max_dt:
                break
            if rw["start"] - cw["start"] > max_dt:
                j0 = j + 1
                continue
            if j in used:
                continue
            s = match_score(rw["word"], cw["word"])
            if s > best:
                best, best_j = s, j
        if best_j >= 0 and best >= 1:
            used.add(best_j)
            cw = clip_words[best_j]
            pairs.append({"ref_word": rw["word"], "ref_start": rw["start"],
                          "clip_word": cw["word"], "clip_start": cw["start"],
                          "dt": round(cw["start"] - rw["start"], 3),
                          "score": best})
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip", help="AI 视频 clip（或其音轨）")
    ap.add_argument("ref", nargs="?", help="参考人声切片 wav（参考端走转录时用）")
    ap.add_argument("--ref-words", help="words-fixed.json：参考端直接用已知逐词时间")
    ap.add_argument("--ref-t0", type=float, help="切片在歌曲中的起始秒（配 --ref-words）")
    ap.add_argument("--lyrics", help="窗口内确切歌词，作为 clip 转录的 initial_prompt 偏置")
    ap.add_argument("--out", help="报告 JSON 输出路径")
    ap.add_argument("--model", default="small")
    ap.add_argument("--max-dt", type=float, default=3.0)
    args = ap.parse_args()

    if args.ref_words:
        assert args.ref_t0 is not None, "--ref-words 需要 --ref-t0"
        ref_words = ref_words_from_json(args.ref_words, args.ref_t0,
                                        args.ref_t0 + 5.0, args.max_dt)
    elif args.ref:
        ref_words = transcribe_words(args.ref, args.model)
    else:
        ap.error("需要 REF.wav 或 --ref-words")

    clip_words = transcribe_words(args.clip, args.model, args.lyrics)
    pairs = match_words(ref_words, clip_words, args.max_dt)

    if len(pairs) >= 3:
        dts = sorted(p["dt"] for p in pairs)
        median = float(dts[len(dts) // 2])
        outliers = [p for p in pairs if abs(p["dt"] - median) > 0.5]
        ok = bool(abs(median) <= 0.15 and not outliers)
    else:
        median, outliers, ok = None, [], False

    report = {
        "summary": {
            "n_matched": int(len(pairs)),
            "median_dt_s": median,
            "mean_dt_s": float(round(sum(p["dt"] for p in pairs) / len(pairs), 3)) if pairs else None,
            "outliers_over_0.5s": int(len(outliers)),
            "in_sync": ok,
        },
        "pairs": pairs,
        "ref_transcript": [f'{w["start"]:6.2f} {w["word"]}' for w in ref_words],
        "clip_transcript": [f'{w["start"]:6.2f} {w["word"]}' for w in clip_words],
    }
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    s = report["summary"]
    print(f"n_matched={s['n_matched']}  median_dt={s['median_dt_s']}  "
          f"mean_dt={s['mean_dt_s']}  outliers={s['outliers_over_0.5s']}  in_sync={ok}")
    for p in pairs:
        flag = " <<<" if median is not None and abs(p["dt"] - median) > 0.5 else ""
        print(f'  {p["ref_start"]:6.2f} {p["ref_word"]:<12} -> '
              f'{p["clip_start"]:6.2f} {p["clip_word"]:<12} dt={p["dt"]:+.3f}{flag}')


if __name__ == "__main__":
    main()
