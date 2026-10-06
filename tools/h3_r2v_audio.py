#!/usr/bin/env python3
"""MiniMax-H3 r2v：参考图 + 参考音频（音频参考脚本不支持，按手册 §8 patch）。

用法：
    venv/bin/python tools/h3_r2v_audio.py \
        --prompt "... <Picture 1> ... <Audio 1> ..." \
        --ref-image plates/s023-a.png --ref-audio /tmp/vocal-6820.wav \
        --width 1344 --height 768 --duration 5 --steps 6 --seed 20260930 \
        --out clips/h3-s023.mp4
"""
import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "video", "tools"))
import minimax_h3_video as h3


def upload_media(client, path):
    boundary = uuid.uuid4().hex
    name = path.rsplit("/", 1)[-1]
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        blob = f.read()
    parts = []
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                 f'name="image"; filename="{name}"\r\n'
                 f"Content-Type: {mime}\r\n\r\n".encode() + blob + b"\r\n")
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                 f'name="overwrite"\r\n\r\ntrue\r\n'.encode())
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(client.server + "/upload/image", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    print(f"uploaded {path} -> {resp['name']}", file=sys.stderr)
    return resp["name"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--ref-image", action="append", default=[])
    ap.add_argument("--ref-audio", action="append", default=[])
    ap.add_argument("--width", type=int, default=1344)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20260930)
    ap.add_argument("--out", required=True)
    ap.add_argument("--server", default=h3.DEFAULT_SERVER)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    client = h3.ComfyClient(args.server)
    img_names = [upload_media(client, p) for p in args.ref_image]
    aud_names = [upload_media(client, p) for p in args.ref_audio]

    graph = h3.build_prompt(
        mode="r2v", prompt=args.prompt, width=args.width, height=args.height,
        length=h3.frames_for_duration(args.duration), steps=args.steps,
        seed=args.seed, ref_images=img_names, ref_image_size="match",
        filename_prefix="video/example_take10")
    r2v_inputs = graph["6"]["inputs"]
    for i, aud in enumerate(aud_names):
        node_id = f"20{i}"
        graph[node_id] = {"class_type": "LoadAudio",
                          "inputs": {"audio": aud}}
        # 手册 §8：键必须带点号完整路径
        r2v_inputs[f"ref_audios.ref_audio_{i}"] = [node_id, 0]

    print(f"queueing r2v+audio {args.width}x{args.height} "
          f"steps={args.steps} seed={args.seed}", file=sys.stderr)
    pid = client.queue(graph)
    print(f"prompt_id={pid}", file=sys.stderr)
    t0 = time.time()
    entry = client.wait_done(pid, timeout=args.timeout)
    print(f"done in {time.time()-t0:.0f}s", file=sys.stderr)
    client.download_video(entry, args.out)
    print(args.out)


if __name__ == "__main__":
    main()
