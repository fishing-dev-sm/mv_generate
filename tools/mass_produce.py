#!/usr/bin/env python3
"""H3 全片量产 watcher：segments.json 驱动的串行生成 + QC + 断点续跑。

用法： venv/bin/python tools/mass_produce.py [--only segId,...] [--dry-run]
产出： clips/final/{id}.mp4 / {id}-frames/ / sung 段 timemap
      clips/final/segments-report.json（增量更新，断点续跑依据）
日志： stdout 行级心跳；单段超过 35min 未完工打 [ALERT]（不杀任务）。
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h3_r2v_audio as h3sub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINAL = os.path.join(ROOT, "clips", "final")
REPORT = os.path.join(FINAL, "segments-report.json")
SERVER = "http://127.0.0.1:8188"

# 口径（导演裁决 2026-10-01）：下面这条"不出现任何字幕、标题、文字、字母或数字"
# 只约束叠加字幕类文字（字幕/标题/水印/幻觉烧录歌词）；画面内实景文字
# （霓虹招牌字母、LED 数码管、电子屏数字、店招、路牌）不判 fail，勿因此重出。
STYLE_CONTINUITY = ("全片连续性条款：冷峻电影感，蓝黑与钢蓝色调，一盏红色小灯是画面中唯一暖色"
                    "（宣言墙全亮段除外），细腻胶片颗粒，"
                    "画面中不出现任何字幕、标题、文字、字母或数字")
CHARACTER_CANON = ("主角是年轻女性、黑色凌乱狼尾中长发（后颈发尾较长）、"
                   "苍白肤色、淡妆冷脸、黑色无袖上衣，形象始终一致")

# 每镜：plate 描述（board-final.md plate_prompt 全文去 S 后缀）+ 运镜
SHOTS = {

 "s001": ("示例场景", "示例运镜"),
 "s002": ("示例场景", "示例运镜"),
 "s003": ("示例场景", "示例运镜"),
 "s004": ("示例场景", "示例运镜"),
 "s006": ("示例场景", "示例运镜"),
 "s007": ("示例场景", "示例运镜"),
 "s008": ("示例场景", "示例运镜"),
 "s009": ("示例场景", "示例运镜"),
 "s010": ("示例场景", "示例运镜"),
 "s011": ("示例场景", "示例运镜"),
 "s012": ("示例场景", "示例运镜"),
 "s013": ("示例场景", "示例运镜"),
 "s014": ("示例场景", "示例运镜"),
 "s015": ("示例场景", "示例运镜"),
 "s016": ("示例场景", "示例运镜"),
 "s017": ("示例场景", "示例运镜"),
 "s018": ("示例场景", "示例运镜"),
 "s019": ("示例场景", "示例运镜"),
 "s020": ("示例场景", "示例运镜"),
 "s021": ("示例场景", "示例运镜"),
 "s022": ("示例场景", "示例运镜"),
 "s023": ("示例场景", "示例运镜"),
 "s024": ("示例场景", "示例运镜"),
 "s025": ("示例场景", "示例运镜"),
 "s026": ("示例场景", "示例运镜"),
 "s027": ("示例场景", "示例运镜"),
 "s028": ("示例场景", "示例运镜"),
 "s029": ("示例场景", "示例运镜"),
 "s030": ("示例场景", "示例运镜"),
 "s031": ("示例场景", "示例运镜"),
 "s032": ("示例场景", "示例运镜"),
 "s033": ("示例场景", "示例运镜"),
 "s034": ("示例场景", "示例运镜"),
 "s035": ("示例场景", "示例运镜"),
 "s036": ("示例场景", "示例运镜"),
 "s037": ("示例场景", "示例运镜"),
 "s038": ("示例场景", "示例运镜"),
 "s039": ("示例场景", "示例运镜"),
 "s040": ("示例场景", "示例运镜"),
 "s041": ("示例场景", "示例运镜"),
 "s042": ("示例场景", "示例运镜"),
 "s043": ("示例场景", "示例运镜"),
 "s044": ("示例场景", "示例运镜"),
 "s045": ("示例场景", "示例运镜"),
 "s046": ("示例场景", "示例运镜"),
 "s047": ("示例场景", "示例运镜"),
 "s048": ("示例场景", "示例运镜"),
 "s049": ("示例场景", "示例运镜"),
 "s050": ("示例场景", "示例运镜"),
 "s051": ("示例场景", "示例运镜"),
 "s052": ("示例场景", "示例运镜"),
 "s053": ("示例场景", "示例运镜"),
 "s054": ("示例场景", "示例运镜"),
 "s055": ("示例场景", "示例运镜"),
}


SUNG_BEHAVIOR = ("<Picture {p}> 的角色跟着 <Audio 1> 的歌声演唱，嘴型和节奏严格跟随 "
                 "<Audio 1> 里的人声，她用女声演唱，是年轻女性的歌声")

SILENT_BEHAVIOR = ("<Picture {p}> 的角色不唱歌，歌声来自画外，她的嘴不乱动")








CUT1_COMP = 1.47
SING_SHOTS = {"s002", "s004", "s006", "s007", "s011", "s013", "s015", "s022",
              "s023", "s024", "s028", "s035", "s036", "s043", "s044", "s045",
              "s049", "s052", "s053", "s054", "s055"}
SILENT_SHOTS = {"s003", "s014", "s016", "s017", "s018", "s026", "s038", "s039"}

NOPEOPLE_SHOTS = {"s001", "s008", "s009", "s010", "s012", "s025", "s027", "s029",
                  "s030", "s031", "s037", "s040", "s042", "s046", "s047", "s048",
                  "s050", "s051"}

SUBJECT_SHOTS = {"s019", "s020", "s021", "s032", "s034", "s041"}


def build_prompt(seg, wf):
    """CUT TO 结构：风格定调 → CUT n（演唱/画外/出场约束+plate 描述+运镜+时长）→ 连续性 → 逐 CUT 歌词行。"""
    t0, t1 = seg["window"]
    real_shots = [s for s in seg["shots"] if s in SHOTS]   # s005 等 code 镜无 plate
    cuts, lyric_lines = [], []
    for i, sh in enumerate(real_shots):
        desc, cam = SHOTS[sh]
        pic = i + 1
        dur = ""
        cut_end = t1
        if i + 1 < len(real_shots):
            nxt = real_shots[i + 1]
            cut_end = BOARD_T0[nxt]
            dt = round(cut_end - t0, 2)

            prompt_dt = round(dt * (CUT1_COMP if i == 0 else 1.0), 2)
            dur = f"；到本段第 {prompt_dt:.1f} 秒时硬切到下一个画面（瞬间切换，无淡入淡出，无渐变 morph 过渡）"
        behave = ""
        if sh in SING_SHOTS:
            behave = SUNG_BEHAVIOR.format(p=pic) + "，"
            lyr = lyrics_in_window(max(t0, BOARD_T0.get(sh, t0)), cut_end, wf)
            if lyr:
                lyric_lines.append(f"第 {pic} 个画面的歌词：\"{lyr}\"")
        elif sh in SILENT_SHOTS:
            behave = SILENT_BEHAVIOR.format(p=pic) + "，"
        elif sh in NOPEOPLE_SHOTS:
            behave = "画面中没有人物，是空镜，"
        elif sh in SUBJECT_SHOTS:
            behave = "画面中不出现那位年轻女性主角，"
        cuts.append(f"CUT {i+1}：{behave}<Picture {pic}> {desc}，镜头{cam}{dur}")
    body = "。".join(cuts)
    if len(real_shots) > 1:
        body += (f"。各 CUT 之间是硬切（hard cut）：到指定秒数时画面瞬间切换，"
                 f"绝不渐变、绝不淡入淡出、绝不形变过渡；"
                 f"每个 CUT 内主体动作在其时长内持续进行，画面内容随时间连续变化，禁止静止定格")

    has_her = any(s in SING_SHOTS or s in SILENT_SHOTS or s == "s033" for s in real_shots)
    continuity = f"{CHARACTER_CANON}，{STYLE_CONTINUITY}" if has_her else STYLE_CONTINUITY
    prompt = f"{body}。{continuity}。整体画面运动节奏跟随 <Audio 1> 的音乐"
    if not lyric_lines:          # 全段无演唱 CUT：歌词作为画外歌声内容
        lyr = lyrics_in_window(t0, t1, wf)
        if lyr:
            lyric_lines.append(f"画外歌声的歌词：\"{lyr}\"")
    if lyric_lines:
        prompt += "\n" + "\n".join(lyric_lines)
    return prompt


BOARD_T0 = {}
def _load_board_t0():
    import re
    txt = open(os.path.join(ROOT, "storyboard/board-final.md"), encoding="utf8").read()
    for m in re.finditer(r"\| (s\d{3}) \| ([\d.]+) \| ([\d.]+) \|", txt):
        BOARD_T0[m.group(1)] = float(m.group(2))


def lyrics_in_window(t0, t1, wf):
    import re
    ws = [w for w in wf["words"] if t0 - 0.2 <= w["start"] < t1]
    seen, out = set(), []
    for w in ws:
        tok = re.sub(r"[^\u4e00-\u9fff]", "", w["word"])   # 只留 CJK，英文 token 会被 H3 念出来
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return " ".join(out)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def extract_frames(mp4, outdir):
    os.makedirs(outdir, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp4, "-vf", "fps=24",
                    "-start_number", "0", os.path.join(outdir, "f%04d.png")], check=True)


def qc_motion(frames_dir):
    """首帧 vs 第12帧差分：返回变化像素占比(%)，<3% 判静帧失败。"""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(os.path.join(frames_dir, "f0000.png")).convert("L"), dtype=float)
    b = np.asarray(Image.open(os.path.join(frames_dir, "f0012.png")).convert("L"), dtype=float)
    if a.shape != b.shape:
        b = np.asarray(Image.fromarray(b.astype("uint8")).resize(a.shape[::-1]), dtype=float)
    return round(float((np.abs(a - b) > 10).mean() * 100), 2)


def qc_firstframe(frames_dir, plate_path):
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(os.path.join(frames_dir, "f0000.png")).convert("L").resize((1344, 768)), dtype=float)
    b = np.asarray(Image.open(os.path.join(ROOT, plate_path)).convert("L"), dtype=float)
    return round(float(np.abs(a - b).mean()), 1)


def qc_scene_cuts(mp4, expected_rel):
    """ffmpeg scene detect，返回实测切点（相对窗口秒），与期望比较。"""
    p = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", mp4,
         "-vf", "select='gt(scene,0.35)',showinfo", "-f", "null", "-"],
        capture_output=True, text=True)
    cuts = [float(x) for x in
            __import__("re").findall(r"pts_time:([\d.]+)", p.stderr)]
    ok = all(any(abs(c - e) <= 1.0 for c in cuts) for e in expected_rel) if expected_rel else True
    return [round(c, 2) for c in cuts], ok


def qc_sung(seg, mp4, ref_wav, lyrics):
    """sung 段轻量记录：whisper 首词（raw）。DTW/NCC 推迟到质检阶段，这里不算。"""
    import wordsync
    info = {}
    try:
        w = wordsync.transcribe_words(mp4, "small", initial_prompt=lyrics)
        info["first_words"] = [x["word"] for x in w[:3]]
        info["clip_head"] = [f'{x["start"]:.1f}{x["word"]}' for x in w[:8]]
    except Exception as e:
        info["qc_note"] = f"whisper failed: {e}"[:120]
    return info


def qc_gender(sid, mp4):
    """声带性别关：抽音轨 scp 到 {{VOICE_HOST}}，demucs 分离人声 + pyin 中位 f0。<150Hz 疑似男声。"""
    wav = f"/tmp/vg_{sid}.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp4,
                    "-vn", "-ac", "1", "-ar", "44100", wav], check=True)
    subprocess.run(["scp", "-q", wav, "{{SSH_USER}}@{{VOICE_HOST}}:/tmp/"], check=True)
    p = subprocess.run(
        ["ssh", "{{SSH_USER}}@{{VOICE_HOST}}",
         f"~/voice-tools/.venv/bin/python ~/voice-tools/gender_f0.py /tmp/vg_{sid}.wav"],
        capture_output=True, text=True, timeout=300)
    return float(p.stdout.strip().splitlines()[-1])


class TransportError(Exception):
    pass


def ensure_tunnel(tries=12):
    """隧道断则重连（ssh -f -N 幂等），返回是否可用。"""
    import urllib.error
    for i in range(tries):
        try:
            with urllib.request.urlopen(SERVER + "/system_stats", timeout=10) as r:
                r.read()
            return True
        except Exception:
            print("[tunnel] 重连 ssh -f -N {{H3_HOST}} ...", flush=True)
            subprocess.run(["ssh", "-f", "-N", "{{H3_HOST}}"],
                           capture_output=True)
            time.sleep(15)
    return False


def resilient_req(client, method, path, **kw):
    for i in range(30):
        try:
            return client._req(method, path, **kw)
        except Exception as e:
            if not ensure_tunnel():
                raise TransportError(f"tunnel down: {e}")
    raise TransportError("unreachable")


def wait_and_download(client, seg, pid, out_mp4):
    t0 = time.time()
    while True:
        if time.time() - t0 > 35 * 60:
            print(f"[ALERT] {seg['id']} 超过35min未完工（prompt {pid}），继续等待", flush=True)
            t0 = time.time()
        time.sleep(20)
        h = resilient_req(client, "GET", f"/history/{pid}")
        if pid in h:
            entry = h[pid]
            st = entry.get("status", {})
            if st.get("status_str") == "error":
                raise RuntimeError(f"generation error: {st.get('messages')}")
            if st.get("completed"):
                img = entry["outputs"]["15"]["images"][0]
                data = resilient_req(client, "GET",
                    f"/view?filename={img['filename']}"
                    f"&subfolder={img.get('subfolder','')}&type=output",
                    raw=True, timeout=300)
                with open(out_mp4, "wb") as f:
                    f.write(data)
                return


def submit(seg, seed, prompt, plates, ref_wav, out_mp4):
    client = h3sub.h3.ComfyClient(SERVER)
    names = [h3sub.upload_media(client, os.path.join(ROOT, p)) for p in plates]
    aud = h3sub.upload_media(client, ref_wav)
    graph = h3sub.h3.build_prompt(
        mode="r2v", prompt=prompt, width=1344, height=768,
        length=h3sub.h3.frames_for_duration(seg["frames"] / 24.0),
        steps=6, seed=seed, ref_images=names, ref_image_size="match",
        filename_prefix=f"video/example_final")
    r2v = graph["6"]["inputs"]
    r2v["ref_audios.ref_audio_0"] = ["200", 0]
    graph["200"] = {"class_type": "LoadAudio", "inputs": {"audio": aud}}
    # 队列纪律：占用时 seed 匹配→收养在跑的同构任务；不匹配→等待（不烧次数）
    while True:
        q = resilient_req(client, "GET", "/queue")
        if not q.get("queue_running") and not q.get("queue_pending"):
            break
        job = (q.get("queue_running") or q.get("queue_pending"))[0]
        jseed = job[2].get("8", {}).get("inputs", {}).get("noise_seed")
        if jseed == seed:
            print(f"[adopt] {seg['id']} 收养在跑的同构任务 {job[1]}（seed={seed}）", flush=True)
            return wait_and_download(client, seg, job[1], out_mp4)
        print(f"[wait] 队列被占用（seed={jseed}），60s 后重查…", flush=True)
        time.sleep(60)
    pid = resilient_req(client, "POST", "/prompt",
                        data=json.dumps({"prompt": graph}).encode())
    wait_and_download(client, seg, pid, out_mp4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed-offset", type=int, default=0,
                    help="加到每段 seed 上（重头来过时换新种子用）")
    ap.add_argument("--no-frames", action="store_true",
                    help="生成侧不抽帧（抽帧交给 QC 侧，H3 立即接下一段）")
    ap.add_argument("--force", action="store_true",
                    help="连 pending_qc 的段也重出（默认只重出 verdict=fail / 无记录的段）")
    args = ap.parse_args()
    _load_board_t0()
    segs = json.load(open(os.path.join(ROOT, "segments.json")))["segments"]
    if args.only:
        keep = set(args.only.split(","))
        segs = [s for s in segs if s["id"] in keep]
    report = json.load(open(REPORT)) if os.path.exists(REPORT) else {}
    wf = json.load(open(os.path.join(ROOT, "song/analysis/words-fixed.json")))
    for seg in segs:
        sid = seg["id"]
        # 幂等护栏：已落地（pass / pending_qc）的段默认不重出，避免误跑覆盖已生成产物
        if not args.force and report.get(sid, {}).get("verdict") in ("pass", "pending_qc"):
            print(f"[skip] {sid} 已落地（{report[sid]['verdict']}），需重出请先 mark_qc.py fail 或加 --force",
                  flush=True)
            continue
        prompt = build_prompt(seg, wf)
        out_mp4 = os.path.join(FINAL, f"{sid}.mp4")
        frames_dir = os.path.join(FINAL, f"{sid}-frames")
        ref_wav = os.path.join(ROOT, f"ref-audio-v3/{sid}.wav")
        print(f"\n===== {sid} kind={seg['kind']} shots={'+'.join(seg['shots'])} "
              f"frames={seg['frames']} sung={seg['sung']} =====", flush=True)
        if args.dry_run:
            print(prompt[:300] + " ...", flush=True)
            continue
        attempt = report.get(sid, {}).get("attempts", 0)
        seed = 20261200 + int(sid[1:]) if sid[0] == "c" else 20261100 + int(sid[1:])
        attempt += 1
        this_seed = seed + (attempt - 1) * 1000 + args.seed_offset
        info = {"attempts": attempt, "seed": this_seed, "shots": seg["shots"],
                "kind": seg["kind"], "mode": "gen-first"}
        if os.path.exists(out_mp4):     # 重出前备份上一版，供 A/B 对照
            os.rename(out_mp4, out_mp4.replace(".mp4", f".attempt{attempt - 1}.mp4"))
        # 生成优先：单趟提交，QC 只记录不拦截（raw 测量值供质检阶段审查）
        while True:
            try:
                print(f"[submit] {sid} attempt={attempt} seed={this_seed}", flush=True)
                t0 = time.time()
                submit(seg, this_seed, prompt, seg["plates"], ref_wav, out_mp4)
                info["gen_min"] = round((time.time() - t0) / 60, 1)
                print(f"[gen ok] {sid} {info['gen_min']}min", flush=True)
                break
            except TransportError as e:
                info["error"] = f"transport: {e}"[:200]
                report[sid] = info
                json.dump(report, open(REPORT, "w"), ensure_ascii=False, indent=2)
                print(f"[transport-retry] {sid}: {info['error']}", flush=True)
                time.sleep(60)
            except Exception as e:
                info["error"] = str(e)[:300]
                report[sid] = info
                json.dump(report, open(REPORT, "w"), ensure_ascii=False, indent=2)
                print(f"[gen-fail] {sid}: {info['error']}（记录，继续下一段）", flush=True)
                break
        if "gen_min" not in info:
            continue
        # 不做机器 QC：抽帧（引擎素材）→ pending_qc，等导演电话裁决后 mark_qc.py 改判
        if not args.no_frames:
            try:
                extract_frames(out_mp4, frames_dir)
            except Exception as e:
                info["frames_error"] = str(e)[:150]
        info["frames_pending"] = bool(args.no_frames)
        info["verdict"] = "pending_qc"
        report[sid] = info
        json.dump(report, open(REPORT, "w"), ensure_ascii=False, indent=2)
        print(f"[PENDING-QC] {sid} —— 等导演裁决", flush=True)
    print(f"\n[done] all=ok", flush=True)


if __name__ == "__main__":
    main()
