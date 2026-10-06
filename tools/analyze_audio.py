#!/usr/bin/env python3
"""音频分析：节拍网格 + 逐词时间对齐。

对一个音频窗口做两件事：
1. librosa 动态节拍跟踪 -> beatmap.json（逐拍时间戳 + 局部 tempo 曲线，不假设恒定 BPM）
2. faster-whisper (CPU int8) 逐词转录 -> words.json（word-level timestamps）

用法：
    analyze_audio.py INPUT --t0 58 --t1 73 --out-dir ../out
产出：
    <out-dir>/window.wav   16kHz mono 窗口音频（t 轴以窗口起点为 0）
    <out-dir>/beatmap.json
    <out-dir>/words.json
"""
import argparse
import json
import os
import subprocess
import sys


def extract_window(input_path, t0, t1, out_wav, sr=16000):
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", str(t0), "-to", str(t1),
        "-i", input_path,
        "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le",
        out_wav,
    ]
    subprocess.run(cmd, check=True)


def analyze_beats(wav_path):
    import librosa
    import numpy as np

    y, sr = librosa.load(wav_path, sr=22050, mono=True)
    hop = 512
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    # 动态节拍跟踪（动态规划，逐拍时间戳，不锁定恒定 BPM）
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=oenv, sr=sr, hop_length=hop, trim=False
    )
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    # 由拍间间隔推 BPM（比 tempo 先验更可信，渐速曲直接用逐拍戳）
    intervals = np.diff(beat_times)
    bpm_from_beats = float(60.0 / np.median(intervals)) if len(intervals) else 0.0
    # 局部 tempo 曲线（帧级，反映渐速）
    local_tempo = librosa.feature.tempo(
        onset_envelope=oenv, sr=sr, hop_length=hop, aggregate=None
    )
    tempo_frames = np.arange(len(local_tempo))
    tempo_times = librosa.frames_to_time(tempo_frames, sr=sr, hop_length=hop)
    return {
        "sr": sr,
        "duration": float(len(y) / sr),
        "bpm_global": float(np.atleast_1d(tempo)[0]),
        "bpm_window": [float(local_tempo[0]), float(local_tempo[-1])],
        "bpm_median": float(np.median(local_tempo)),
        "bpm_from_beats": round(bpm_from_beats, 2),
        "beats": [round(float(t), 4) for t in beat_times],
        "tempo_curve": [
            {"t": round(float(tt), 3), "bpm": round(float(bb), 1)}
            for tt, bb in zip(tempo_times[:: max(1, len(local_tempo) // 32)],
                              local_tempo[:: max(1, len(local_tempo) // 32)])
        ],
    }


def transcribe_words(input_path, t0, t1, pad, model_size, vad=False):
    """扩窗转录：在 [t0-pad, t1+pad] 上转录保住上下文，再裁回窗口并平移到窗口时间轴。

    直接转录 15s 短窗会丢上下文，唱段大量漏词（实测 12 词只剩 3 词）。
    """
    from faster_whisper import WhisperModel

    pt0 = max(0.0, t0 - pad)
    pt1 = t1 + pad
    import tempfile
    tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    extract_window(input_path, pt0, pt1, tmp_wav)

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        tmp_wav,
        language="en",
        word_timestamps=True,
        vad_filter=vad,
    )
    words = []
    segments_out = []
    lo, hi = t0 - pt0, t1 - pt0  # 窗口在扩窗音频里的位置
    for seg in segments:
        seg_words = []
        for w in (seg.words or []):
            mid = (w.start + w.end) / 2
            if lo <= mid < hi:
                seg_words.append({
                    "word": w.word.strip(),
                    "start": round(w.start - lo, 4),
                    "end": round(w.end - lo, 4),
                })
        if seg_words:
            words.extend(seg_words)
            segments_out.append({
                "start": seg_words[0]["start"],
                "end": seg_words[-1]["end"],
                "text": " ".join(x["word"] for x in seg_words),
            })
    os.unlink(tmp_wav)
    return {
        "language": info.language,
        "pad_window": [pt0, pt1],
        "words": words,
        "segments": segments_out,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="输入音频文件（mp3/wav 等，ffmpeg 可读）")
    p.add_argument("--t0", type=float, required=True, help="窗口起点（秒）")
    p.add_argument("--t1", type=float, required=True, help="窗口终点（秒）")
    p.add_argument("--out-dir", default=".", help="输出目录（默认当前目录）")
    p.add_argument("--model", default="small",
                   help="faster-whisper 模型尺寸（默认 small）")
    p.add_argument("--vad", action="store_true",
                   help="开启 VAD 过滤（唱段+伴奏场景容易被误杀，默认关）")
    p.add_argument("--pad", type=float, default=25.0,
                   help="转录扩窗秒数（默认 25，保住上下文防漏词；0=不扩窗）")
    p.add_argument("--no-transcribe", action="store_true", help="只出 beatmap")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    wav = os.path.join(args.out_dir, "window.wav")
    extract_window(args.input, args.t0, args.t1, wav)
    print(f"[ok] 窗口音频 -> {wav} ({args.t1 - args.t0:.1f}s, 16kHz mono)")

    beatmap = analyze_beats(wav)
    beatmap.update({"t0": args.t0, "t1": args.t1, "source": os.path.abspath(args.input)})
    bm_path = os.path.join(args.out_dir, "beatmap.json")
    with open(bm_path, "w") as f:
        json.dump(beatmap, f, ensure_ascii=False, indent=2)
    print(f"[ok] beatmap -> {bm_path}: {len(beatmap['beats'])} beats, "
          f"局部 tempo {beatmap['bpm_window'][0]:.1f}→{beatmap['bpm_window'][1]:.1f} BPM "
          f"(median {beatmap['bpm_median']:.1f})")

    if not args.no_transcribe:
        words = transcribe_words(args.input, args.t0, args.t1, args.pad,
                                 args.model, vad=args.vad)
        words.update({"t0": args.t0, "t1": args.t1})
        w_path = os.path.join(args.out_dir, "words.json")
        with open(w_path, "w") as f:
            json.dump(words, f, ensure_ascii=False, indent=2)
        print(f"[ok] words -> {w_path}: {len(words['words'])} 词, "
              f"{len(words['segments'])} 段")


if __name__ == "__main__":
    sys.exit(main())
