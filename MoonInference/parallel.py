"""
Moon Inference - Parallel Residual Stream
All 80 layers compute from the SAME input simultaneously.
Deltas summed. Nonlinearities preserved.

x_final = x_0 + SUM(delta_i(x_0)) for i in 0..79

Quantum superposition: input exists at all layers at once.
Each layer contributes independently. Interference = summation.
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


def decomp_mm(x, U, S, Vt):
    return (x @ Vt.T) * S @ U.T


class ParallelMoon:
    def __init__(self, model_dir: str, rank: int = 256):
        self.dir = Path(model_dir)
        self.decomp_dir = self.dir / f"decomposed_r{rank}"
        cfg = json.load(open(self.dir / "config.json"))

        self.nl = cfg["num_hidden_layers"]
        self.dim = cfg["hidden_size"]
        self.nh = cfg["num_attention_heads"]
        self.nkv = cfg.get("num_key_value_heads", self.nh)
        self.hd = self.dim // self.nh
        self.theta = cfg.get("rope_theta", 1000000.0)

        try:
            from transformers import AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(str(self.dir), trust_remote_code=True)
        except:
            self.tok = None

        # Load all decomposed layers into RAM
        print(f"[Parallel] Loading {self.nl} decomposed layers...", flush=True)
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

        # Embeddings
        embed_path = self.decomp_dir / "embed.npy"
        self.embed = mx.array(np.load(embed_path)) if embed_path.exists() else None

        # Final norm
        norm_path = self.decomp_dir / "final_norm.npy"
        self.final_norm = mx.array(np.load(norm_path)) if norm_path.exists() else None

        # LM head chunks
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
        print(f"[Parallel] Loaded in {dt:.1f}s", flush=True)

    def compute_delta(self, x0, layer, pos):
        """
        Compute one layer's delta from the ORIGINAL input x0.
        Keeps all nonlinearities. Returns delta (not x0 + delta).
        """
        L = layer
        x = x0

        # Attention block
        xn = rms_norm(x, L["in_norm"])

        B, Len, _ = xn.shape
        q = decomp_mm(xn, L["self_attn.q_proj"]["U"], L["self_attn.q_proj"]["S"], L["self_attn.q_proj"]["Vt"])
        k = decomp_mm(xn, L["self_attn.k_proj"]["U"], L["self_attn.k_proj"]["S"], L["self_attn.k_proj"]["Vt"])
        v = decomp_mm(xn, L["self_attn.v_proj"]["U"], L["self_attn.v_proj"]["S"], L["self_attn.v_proj"]["Vt"])

        q = q.reshape(B, Len, self.nh, self.hd).transpose(0, 2, 1, 3)
        k = k.reshape(B, Len, self.nkv, self.hd).transpose(0, 2, 1, 3)
        v = v.reshape(B, Len, self.nkv, self.hd).transpose(0, 2, 1, 3)

        q = rope(q, pos, self.theta)
        k = rope(k, pos, self.theta)

        if self.nkv < self.nh:
            rep = self.nh // self.nkv
            k = mx.repeat(k, rep, axis=1)
            v = mx.repeat(v, rep, axis=1)

        sc = (q @ k.transpose(0, 1, 3, 2)) * (self.hd ** -0.5)
        sc = mx.softmax(sc, axis=-1)
        ao = (sc @ v).transpose(0, 2, 1, 3).reshape(B, Len, -1)
        attn_delta = decomp_mm(ao, L["self_attn.o_proj"]["U"], L["self_attn.o_proj"]["S"], L["self_attn.o_proj"]["Vt"])

        # FFN block (from x0, not x0 + attn_delta)
        x_after_attn = x + attn_delta
        xn2 = rms_norm(x_after_attn, L["post_norm"])

        gate = decomp_mm(xn2, L["mlp.gate_proj"]["U"], L["mlp.gate_proj"]["S"], L["mlp.gate_proj"]["Vt"])
        up = decomp_mm(xn2, L["mlp.up_proj"]["U"], L["mlp.up_proj"]["S"], L["mlp.up_proj"]["Vt"])
        ffn_out = nn.silu(gate) * up
        ffn_delta = decomp_mm(ffn_out, L["mlp.down_proj"]["U"], L["mlp.down_proj"]["S"], L["mlp.down_proj"]["Vt"])

        # Total delta for this layer
        return attn_delta + ffn_delta

    def forward(self, token_id, pos):
        """
        Parallel forward: compute all layer deltas from x0, sum them.
        """
        if self.embed is None:
            return None

        x0 = self.embed[token_id:token_id+1].reshape(1, 1, -1)
        mx.eval(x0)

        # Compute all deltas from the same x0
        total_delta = mx.zeros_like(x0)

        for li in range(self.nl):
            delta = self.compute_delta(x0, self.layers[li], pos)
            total_delta = total_delta + delta

            # Eval periodically to manage memory
            if li % 20 == 19:
                mx.eval(total_delta)

        # Final output = x0 + sum of all deltas
        x_final = x0 + total_delta
        mx.eval(x_final)

        # Final norm
        if self.final_norm is not None:
            x_final = rms_norm(x_final, self.final_norm)

        # LM head
        parts = []
        for ch in self.lm_chunks:
            p = decomp_mm(x_final, ch["U"], ch["S"], ch["Vt"])
            mx.eval(p)
            parts.append(p)

        return mx.concatenate(parts, axis=-1) if parts else x_final

    def generate(self, prompt: str, max_tokens: int = 50, temp: float = 0.7):
        if not self.tok:
            return ""

        toks = self.tok.encode(prompt)
        print(f"[Parallel] {len(toks)} tokens\n", flush=True)

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
                print(f"[{dt:.2f}s] ", end="", flush=True)
            print(txt, end="", flush=True)

            out.append(nxt)
            cur = nxt
            pos += 1

            if nxt == self.tok.eos_token_id:
                break

        avg = total_time / max(len(out), 1)
        tps = 1.0 / avg if avg > 0 else 0
        print(f"\n[Parallel] {len(out)} tokens | {avg:.2f}s/tok | {tps:.1f} tok/s")
        return self.tok.decode(out)


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "models/qwen-72b-4bit"
    engine = ParallelMoon(d)
    engine.generate("What is quantum physics?", max_tokens=20)
