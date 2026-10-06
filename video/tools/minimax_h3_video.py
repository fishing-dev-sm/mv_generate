#!/usr/bin/env python3
"""MiniMax-H3 video generation client for the ComfyUI deployment on {{H3_HOST}}.

Usage:
    # text-to-video
    python3 minimax_h3_video.py t2v --prompt "..." [--width 864 --height 480 \
        --duration 5 --steps 6 --seed -1 --out ./out.mp4]

    # reference-to-video (1-9 reference images)
    python3 minimax_h3_video.py r2v --prompt "... <Picture 1> ..." \
        --ref ./char.png [--ref ./char2.png] [--out ./out.mp4]

Prereq: an SSH tunnel forwarding local 8188 to {{H3_HOST}}, e.g.
    ssh -f -N {{H3_HOST}}        # the host config already forwards 8188
or pass --server http://host:8188 directly.
"""

import argparse
import json
import mimetypes
import os
import random
import sys
import time
import urllib.request
import urllib.error
import uuid

DEFAULT_SERVER = os.environ.get("COMFYUI_SERVER", "http://127.0.0.1:8188")

VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
TURBO_LORA = "minimax_h3_turbo_v4_step600_ema.safetensors"
FL2VA_MODEL = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"   # t2v / i2v
REF2VA_MODEL = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"  # reference-to-video
FPS = 24


def frames_for_duration(seconds: float) -> int:
    """Snap a duration in seconds to H3's 17k+5 frame grid at 24 fps."""
    n = max(5, round(seconds * FPS))
    return n + (5 - n % 17) % 17


def build_prompt(*, mode, prompt, width, height, length, steps, seed,
                 ref_images=None, ref_image_size="match",
                 filename_prefix="video/MiniMax_H3"):
    model = REF2VA_MODEL if mode == "r2v" else FL2VA_MODEL
    g = {
        "1": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "3": {"class_type": "UNETLoader",
              "inputs": {"unet_name": model, "weight_dtype": "default"}},
        "4": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax",
                         "device": "default"}},
        "5": {"class_type": "MiniMaxH3TurboLoRA",
              "inputs": {"model": ["3", 0], "lora_name": TURBO_LORA,
                         "strength": 1.0, "low_vram": False}},
        "7": {"class_type": "BasicGuider",
              "inputs": {"model": ["5", 0], "conditioning": ["6", 0]}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "BasicScheduler",
              "inputs": {"model": ["5", 0], "scheduler": "simple",
                         "steps": steps, "denoise": 1.0}},
        "10": {"class_type": "MiniMaxH3TurboSampler", "inputs": {}},
        "11": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["8", 0], "guider": ["7", 0],
                          "sampler": ["10", 0], "sigmas": ["9", 0],
                          "latent_image": ["6", 1]}},
        "12": {"class_type": "VAEDecode",
               "inputs": {"samples": ["11", 0], "vae": ["1", 0]}},
        "13": {"class_type": "VAEDecodeAudio",
               "inputs": {"samples": ["11", 0], "vae": ["2", 0]}},
        "14": {"class_type": "CreateVideo",
               "inputs": {"images": ["12", 0], "audio": ["13", 0], "fps": float(FPS)}},
        "15": {"class_type": "SaveVideo",
               "inputs": {"video": ["14", 0], "filename_prefix": filename_prefix,
                          "format": "auto", "codec": "auto"}},
    }
    if mode == "t2v":
        g["6"] = {"class_type": "MiniMaxH3ImageToVideo",
                  "inputs": {"clip": ["4", 0], "vae": ["1", 0],
                             "prompt": prompt, "width": width,
                             "height": height, "length": length}}
    else:
        inputs = {"clip": ["4", 0], "vae": ["1", 0], "audio_vae": ["2", 0],
                  "prompt": prompt, "width": width, "height": height,
                  "length": length, "ref_image_size": ref_image_size}
        for i, img_name in enumerate(ref_images or []):
            node_id = f"10{i}"
            g[node_id] = {"class_type": "LoadImage",
                          "inputs": {"image": img_name}}
            inputs[f"ref_images.ref_image_{i}"] = [node_id, 0]
        g["6"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": inputs}
    return g


class ComfyClient:
    def __init__(self, server):
        self.server = server.rstrip("/")

    def _req(self, method, path, data=None, raw=False, timeout=30):
        url = self.server + path
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None and not raw:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return body if raw else json.loads(body)

    def upload_image(self, path):
        boundary = uuid.uuid4().hex
        name = os.path.basename(path)
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
        req = urllib.request.Request(self.server + "/upload/image", data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
        return resp["name"]

    def queue(self, graph):
        resp = self._req("POST", "/prompt",
                         data=json.dumps({"prompt": graph}).encode())
        return resp["prompt_id"]

    def wait_done(self, prompt_id, poll=5, timeout=3600):
        deadline = time.time() + timeout
        while time.time() < deadline:
            h = self._req("GET", f"/history/{prompt_id}")
            if prompt_id in h:
                entry = h[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = status.get("messages", [])
                    raise RuntimeError(f"generation failed: {msgs}")
                if status.get("completed"):
                    return entry
            time.sleep(poll)
        raise TimeoutError(f"prompt {prompt_id} not finished in {timeout}s")

    def download_video(self, entry, out_path):
        for node_out in entry.get("outputs", {}).values():
            media = (node_out.get("videos") or []) + (node_out.get("images") or [])
            for v in media:
                q = (f"/view?filename={v['filename']}"
                     f"&subfolder={v.get('subfolder', '')}&type={v['type']}")
                data = self._req("GET", q, raw=True, timeout=300)
                with open(out_path, "wb") as f:
                    f.write(data)
                return out_path
        raise RuntimeError("no video in outputs: "
                           + json.dumps(entry.get("outputs", {}))[:500])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["t2v", "r2v"])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--ref", action="append", default=[],
                    help="reference image path (r2v, up to 9, repeatable)")
    ap.add_argument("--ref-image-size", default="match", choices=["match", "max"])
    ap.add_argument("--width", type=int, default=864)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--duration", type=float, default=5.0, help="seconds")
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--prefix", default="video/MiniMax_H3")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    seed = args.seed if args.seed >= 0 else random.randrange(2**50)
    length = frames_for_duration(args.duration)
    client = ComfyClient(args.server)

    ref_names = []
    for p in args.ref:
        print(f"uploading {p} ...", file=sys.stderr)
        ref_names.append(client.upload_image(p))

    graph = build_prompt(mode=args.mode, prompt=args.prompt,
                         width=args.width, height=args.height, length=length,
                         steps=args.steps, seed=seed, ref_images=ref_names,
                         ref_image_size=args.ref_image_size,
                         filename_prefix=args.prefix)
    print(f"queueing: mode={args.mode} {args.width}x{args.height} "
          f"length={length} ({length/FPS:.1f}s) steps={args.steps} seed={seed}",
          file=sys.stderr)
    pid = client.queue(graph)
    print(f"prompt_id={pid}", file=sys.stderr)

    t0 = time.time()
    entry = client.wait_done(pid, timeout=args.timeout)
    print(f"done in {time.time()-t0:.0f}s", file=sys.stderr)

    out = args.out or f"minimax_h3_{args.mode}_{seed}.mp4"
    client.download_video(entry, out)
    print(out)


if __name__ == "__main__":
    main()
