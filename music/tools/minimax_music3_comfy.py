#!/usr/bin/env python3
"""MiniMax-Music3 client via ComfyUI API on {{H3_HOST}} (port 8188).

Usage:
    python3 minimax_music3_comfy.py \
        --lyrics-file lyrics.txt --caption-file caption.txt \
        --duration 60 --seed 7 --out song.mp3

Prereq: ComfyUI running on {{H3_HOST}} + tunnel:
    ssh -f -N {{H3_HOST}}        # host config forwards 8188
or pass --server http://host:8188.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_SERVER = os.environ.get("COMFYUI_SERVER", "http://127.0.0.1:8188")

DIT_FP16 = "minimax_music3_dit_fp16.safetensors"
DIT_INT8 = "minimax_music3_dit_int8_convrot.safetensors"
TEXT_ENCODER = "minimax_music3_text_encoder_pruned_bf16.safetensors"
VAE = "minimax_music3_dav.safetensors"


def build_prompt(*, caption, lyrics, duration, seed, steps=30, cfg=1.7, top_k=50,
                 int8=False, tiled_decode=False, filename_prefix="audio/minimax_music3",
                 fmt="mp3", quality="V0"):
    g = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": DIT_INT8 if int8 else DIT_FP16,
                         "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax",
                         "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "MiniMaxMusic3TextEncode",
              "inputs": {"clip": ["2", 0], "caption": caption, "lyrics": lyrics,
                         "seed": seed, "max_duration": float(duration),
                         "cfg_scale": cfg, "top_k": top_k}},
        "5": {"class_type": "ConditioningZeroOut",
              "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyMiniMaxMusic3LatentAudio",
              "inputs": {"seconds": ["4", 1], "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0],
                         "negative": ["5", 0], "latent_image": ["6", 0],
                         "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1.0}},
        "8": ({"class_type": "VAEDecodeAudioTiled",
               "inputs": {"samples": ["7", 0], "vae": ["3", 0],
                          "tile_size": 1536, "overlap": 64}}
              if tiled_decode else
              {"class_type": "VAEDecodeAudio",
               "inputs": {"samples": ["7", 0], "vae": ["3", 0]}}),
        "9": {"class_type": "SaveAudioAdvanced",
              "inputs": {"audio": ["8", 0], "filename_prefix": filename_prefix,
                         "format": fmt, "format.quality": quality}},
    }
    return g


class ComfyClient:
    def __init__(self, server):
        self.server = server.rstrip("/")

    def _req(self, method, path, data=None, raw=False, timeout=60):
        req = urllib.request.Request(self.server + path, data=data, method=method)
        if data is not None and not raw:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                return body if raw else json.loads(body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:2000]
            raise RuntimeError(f"HTTP {e.code} {path}: {detail}") from None

    def queue(self, graph):
        return self._req("POST", "/prompt",
                         data=json.dumps({"prompt": graph}).encode())["prompt_id"]

    def wait_done(self, prompt_id, poll=5, timeout=7200):
        deadline = time.time() + timeout
        while time.time() < deadline:
            h = self._req("GET", f"/history/{prompt_id}")
            if prompt_id in h:
                entry = h[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(
                        f"generation failed: {status.get('messages')}")
                if status.get("completed"):
                    return entry
            time.sleep(poll)
        raise TimeoutError(f"prompt {prompt_id} not finished in {timeout}s")

    def download_audio(self, entry, out_path):
        for node_out in entry.get("outputs", {}).values():
            for a in (node_out.get("audio") or []) + (node_out.get("images") or []):
                q = (f"/view?filename={a['filename']}"
                     f"&subfolder={a.get('subfolder', '')}&type={a['type']}")
                data = self._req("GET", q, raw=True, timeout=300)
                with open(out_path, "wb") as f:
                    f.write(data)
                return out_path
        raise RuntimeError("no audio in outputs: "
                           + json.dumps(entry.get("outputs", {}))[:500])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lyrics", default=None)
    ap.add_argument("--lyrics-file", default=None)
    ap.add_argument("--caption", default=None,
                    help="music description / Structured Caption")
    ap.add_argument("--caption-file", default=None)
    ap.add_argument("--duration", type=float, default=60.0,
                    help="max seconds (model may end earlier; max 360)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=1.7)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--int8", action="store_true", help="use int8 DiT (low VRAM)")
    ap.add_argument("--tiled-decode", action="store_true",
                    help="tiled VAE decode, cuts VRAM for long songs")
    ap.add_argument("--format", default="mp3", choices=["mp3", "wav", "flac", "ogg"])
    ap.add_argument("--quality", default="V0")
    ap.add_argument("--out", default=None)
    ap.add_argument("--prefix", default="audio/minimax_music3")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--timeout", type=int, default=7200)
    args = ap.parse_args()

    lyrics = args.lyrics
    if args.lyrics_file:
        lyrics = open(args.lyrics_file, encoding="utf-8").read()
    if lyrics is None:
        ap.error("need --lyrics or --lyrics-file")
    lyrics = lyrics.replace("\\n", "\n")

    caption = args.caption or ""
    if args.caption_file:
        caption = open(args.caption_file, encoding="utf-8").read()

    out = args.out or f"music3_{args.seed}.{args.format}"
    client = ComfyClient(args.server)
    graph = build_prompt(caption=caption, lyrics=lyrics, duration=args.duration,
                         seed=args.seed, steps=args.steps, cfg=args.cfg,
                         top_k=args.top_k, int8=args.int8,
                         tiled_decode=args.tiled_decode,
                         filename_prefix=args.prefix, fmt=args.format,
                         quality=args.quality)
    print(f"queueing: music3 {args.duration:.0f}s seed={args.seed} "
          f"steps={args.steps} cfg={args.cfg} int8={args.int8}", file=sys.stderr)
    pid = client.queue(graph)
    print(f"prompt_id={pid}", file=sys.stderr)
    t0 = time.time()
    entry = client.wait_done(pid, timeout=args.timeout)
    print(f"done in {time.time()-t0:.0f}s", file=sys.stderr)
    client.download_audio(entry, out)
    print(out)


if __name__ == "__main__":
    main()
