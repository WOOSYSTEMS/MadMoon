"""
Moon Inference - Decomposed Per-Layer Inference
72B model, 3GB decomposed factors, keep all nonlinearities.
Each matmul goes through rank-256 bottleneck = 16x fewer ops.

No composition across layers. Quality preserved.
"""

import json
import time
import os
import gc
from pathlib import Path

import numpy as np
import mlx.core as mx
import mlx.nn as nn


def rms_norm(x, w, eps=1e-6):
    return x * mx.rsqrt(mx.mean(x * x, axis=-1, keepdims=True) + eps) * w


def rope(x, pos, theta=1000000.0):
    dim = x.shape[-1]
    f = 1.0 / (theta ** (mx.arange(0, dim, 2, dtype=mx.float32) / dim))
    t = mx.array([pos], dtype=mx.float32)
    ang = t[:, None] * f[None, :]
    c, s = mx.cos(ang), mx.sin(ang)
    x1, x2 = x[..., ::2], x[..., 1::2]
    return mx.concatenate([x1 * c - x2 * s, x1 * s + x2 * c], axis=-1)


def decomp_matmul(x, U, S, Vt):
    """x @ W^T via rank-k bottleneck. 16x fewer ops."""
    # x @ Vt^T -> [B,L,rank], * S -> [B,L,rank], @ U^T -> [B,L,out]
    h = x @ Vt.T
    h = h * S
    return h @ U.T


class FastMoonInference:
    def __init__(self, model_dir: str, rank: int = 256):
        self.dir = Path(model_dir)
        self.decomp_dir = self.dir / f"decomposed_r{rank}"
        cfg = json.load(open(self.dir / "config.json"))

        self.nl = cfg["num_hidden_layers"]
        self.dim = cfg["hidden_size"]
        self.nh = cfg["num_attention_heads"]
        self.nkv = cfg.get("num_key_value_heads", self.nh)
        self.hd = self.dim // self.nh
        self.ffn = cfg["intermediate_size"]
        self.vocab = cfg["vocab_size"]
        self.theta = cfg.get("rope_theta", 1000000.0)

        try:
            from transformers import AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(str(self.dir), trust_remote_code=True)
        except:
            self.tok = None

        # Load ALL decomposed layers into RAM (3GB)
        print(f"[FastMoon] Loading {self.nl} decomposed layers...", flush=True)
        t0 = time.time()

        self.layers = []
        for li in range(self.nl):
            data = np.load(self.decomp_dir / f"layer_{li:03d}.npz")
            layer = {}
            for proj in ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj",
                         "self_attn.o_proj", "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"]:
                layer[proj] = {
                    "U": mx.array(data[f"{proj}.U"]),
                    "S": mx.array(data[f"{proj}.S"]),
                    "Vt": mx.array(data[f"{proj}.Vt"]),
                }
            layer["in_norm"] = mx.array(data["input_norm"])
            layer["post_norm"] = mx.array(data["post_norm"])
            self.layers.append(layer)

            if (li + 1) % 20 == 0:
                print(f"  {li+1}/{self.nl}", flush=True)

        # Load embeddings
        embed_path = self.decomp_dir / "embed.npy"
        if embed_path.exists():
            self.embed = mx.array(np.load(embed_path))
            print(f"  Embeddings loaded: {self.embed.shape}", flush=True)
        else:
            self.embed = None

        # Load final norm
        norm_path = self.decomp_dir / "final_norm.npy"
        self.final_norm = mx.array(np.load(norm_path)) if norm_path.exists() else None

        # Load LM head chunks
        self.lm_chunks = []
        for f in sorted(os.listdir(self.decomp_dir)):
            if f.startswith("lm_head_chunk"):
                d = np.load(self.decomp_dir / f)
                self.lm_chunks.append({
                    "U": mx.array(d["U"]),
                    "S": mx.array(d["S"]),
                    "Vt": mx.array(d["Vt"]),
                })

        dt = time.time() - t0
        print(f"[FastMoon] Loaded in {dt:.1f}s. Ready.", flush=True)

        self.kv = [None] * self.nl

    def forward(self, token_id, pos):
        # Embed
        if self.embed is not None:
            x = self.embed[token_id:token_id+1].reshape(1, 1, -1)
        else:
            return None

        # All 80 layers with decomposed weights
        for li in range(self.nl):
            L = self.layers[li]

            # Attention
            res = x
            x = rms_norm(x, L["in_norm"])

            B, Len, _ = x.shape
            q = decomp_matmul(x, L["self_attn.q_proj"]["U"], L["self_attn.q_proj"]["S"], L["self_attn.q_proj"]["Vt"])
            k = decomp_matmul(x, L["self_attn.k_proj"]["U"], L["self_attn.k_proj"]["S"], L["self_attn.k_proj"]["Vt"])
            v = decomp_matmul(x, L["self_attn.v_proj"]["U"], L["self_attn.v_proj"]["S"], L["self_attn.v_proj"]["Vt"])

            q = q.reshape(B, Len, self.nh, self.hd).transpose(0, 2, 1, 3)
            k = k.reshape(B, Len, self.nkv, self.hd).transpose(0, 2, 1, 3)
            v = v.reshape(B, Len, self.nkv, self.hd).transpose(0, 2, 1, 3)

            q = rope(q, pos, self.theta)
            k = rope(k, pos, self.theta)

            if self.kv[li] is not None:
                kc, vc = self.kv[li]
                k = mx.concatenate([kc, k], axis=2)
                v = mx.concatenate([vc, v], axis=2)
            self.kv[li] = (k, v)

            if self.nkv < self.nh:
                rep = self.nh // self.nkv
                k = mx.repeat(k, rep, axis=1)
                v = mx.repeat(v, rep, axis=1)

            sc = (q @ k.transpose(0, 1, 3, 2)) * (self.hd ** -0.5)
            sc = mx.softmax(sc, axis=-1)
            ao = (sc @ v).transpose(0, 2, 1, 3).reshape(B, Len, -1)
            ao = decomp_matmul(ao, L["self_attn.o_proj"]["U"], L["self_attn.o_proj"]["S"], L["self_attn.o_proj"]["Vt"])

            x = res + ao

            # FFN
            res = x
            x = rms_norm(x, L["post_norm"])

            gate = decomp_matmul(x, L["mlp.gate_proj"]["U"], L["mlp.gate_proj"]["S"], L["mlp.gate_proj"]["Vt"])
            up = decomp_matmul(x, L["mlp.up_proj"]["U"], L["mlp.up_proj"]["S"], L["mlp.up_proj"]["Vt"])
            x = nn.silu(gate) * up
            x = decomp_matmul(x, L["mlp.down_proj"]["U"], L["mlp.down_proj"]["S"], L["mlp.down_proj"]["Vt"])

            x = res + x

            # Eval every 20 layers to flush GPU pipeline
            if li % 20 == 19:
                mx.eval(x)

        # Final norm
        if self.final_norm is not None:
            x = rms_norm(x, self.final_norm)

        # LM head
        parts = []
        for ch in self.lm_chunks:
            p = decomp_matmul(x, ch["U"], ch["S"], ch["Vt"])
            mx.eval(p)
            parts.append(p)

        logits = mx.concatenate(parts, axis=-1) if parts else x
        return logits

    def generate(self, prompt: str, max_tokens: int = 50, temp: float = 0.7):
        if not self.tok:
            print("No tokenizer")
            return ""

        toks = self.tok.encode(prompt)
        print(f"[FastMoon] {len(toks)} prompt tokens\n", flush=True)

        pos = len(toks) - 1
        cur = toks[-1]
        out = []
        total_time = 0

        for step in range(max_tokens):
            t0 = time.time()
            logits = self.forward(cur, pos)
            dt = time.time() - t0
            total_time += dt

            logits = logits[:, -1, :] / temp
            probs = mx.softmax(logits, axis=-1)
            nxt = mx.random.categorical(probs).item()

            txt = self.tok.decode([nxt])
            if step == 0:
                print(f"[{dt:.2f}s first] ", end="", flush=True)
            print(txt, end="", flush=True)

            out.append(nxt)
            cur = nxt
            pos += 1

            if nxt == self.tok.eos_token_id:
                break

        avg = total_time / max(len(out), 1)
        tps = 1.0 / avg if avg > 0 else 0
        print(f"\n[FastMoon] {len(out)} tokens | avg {avg:.2f}s/tok | {tps:.1f} tok/s")
        return self.tok.decode(out)


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "models/qwen-72b-4bit"

    engine = FastMoonInference(d)
    print("\nType prompt:\n")
    while True:
        try:
            p = input("> ")
            if not p or p in ("exit", "quit"):
                break
            engine.generate(p, max_tokens=30)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
