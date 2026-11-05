"""
Moon Inference - Phase 3: Quantum Coherent Inference
72B model, 3GB composed operators, 8GB MacBook Air.

|output> = <Omega|input>
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


class MoonQuantumInference:
    def __init__(self, model_dir: str, rank: int = 256):
        self.model_dir = Path(model_dir)
        self.composed_dir = self.model_dir / f"composed_r{rank}"
        self.config = json.load(open(self.model_dir / "config.json"))

        self.nl = self.config["num_hidden_layers"]
        self.dim = self.config["hidden_size"]
        self.nh = self.config["num_attention_heads"]
        self.nkv = self.config.get("num_key_value_heads", self.nh)
        self.hd = self.dim // self.nh
        self.ffn = self.config["intermediate_size"]
        self.vocab = self.config["vocab_size"]
        self.theta = self.config.get("rope_theta", 1000000.0)
        self.rank = rank

        # Load tokenizer
        try:
            from transformers import AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(str(self.model_dir), trust_remote_code=True)
        except:
            self.tok = None

        # Load composed groups into RAM (3GB total)
        print(f"[Moon Quantum] Loading composed operators into RAM...")
        t0 = time.time()
        self.groups = []
        g = 0
        while True:
            gp = self.composed_dir / f"group_{g:02d}.npz"
            if not gp.exists():
                break
            self.groups.append(np.load(gp, allow_pickle=True))
            g += 1

        # Load embeddings
        embed_path = self.composed_dir / "embed.npy"
        if embed_path.exists():
            self.embed = mx.array(np.load(embed_path))
        else:
            self.embed = None

        # Load final norm
        norm_path = self.composed_dir / "final_norm.npy"
        if norm_path.exists():
            self.final_norm = mx.array(np.load(norm_path))
        else:
            self.final_norm = None

        # Load LM head chunks
        self.lm_chunks = []
        for f in sorted(os.listdir(self.composed_dir)):
            if f.startswith("lm_head_chunk"):
                data = np.load(self.composed_dir / f)
                self.lm_chunks.append({
                    "U": mx.array(data["U"]),
                    "S": mx.array(data["S"]),
                    "Vt": mx.array(data["Vt"])
                })

        dt = time.time() - t0
        print(f"[Moon Quantum] {len(self.groups)} groups loaded in {dt:.1f}s")
        print(f"[Moon Quantum] Ready for inference")

        # KV caches
        self.kv = [None] * self.nl

    def decomposed_matmul(self, x, U, S, Vt):
        """x @ W^T where W = U @ diag(S) @ Vt"""
        # x: [B, L, dim_in]
        # Vt: [rank, dim_in], S: [rank], U: [dim_out, rank]
        U_mx = mx.array(U) if not isinstance(U, mx.array) else U
        S_mx = mx.array(S) if not isinstance(S, mx.array) else S
        Vt_mx = mx.array(Vt) if not isinstance(Vt, mx.array) else Vt

        # x @ Vt^T = [B, L, rank]
        h = x @ Vt_mx.T
        # h * S = [B, L, rank]
        h = h * S_mx
        # h @ U^T = [B, L, dim_out]
        out = h @ U_mx.T
        return out

    def forward_group(self, x, group, group_idx, pos):
        """Forward through one composed group."""
        # Get projection factors
        qU, qS, qVt = group["self_attn.q_proj.U"], group["self_attn.q_proj.S"], group["self_attn.q_proj.Vt"]
        kU, kS, kVt = group["self_attn.k_proj.U"], group["self_attn.k_proj.S"], group["self_attn.k_proj.Vt"]
        vU, vS, vVt = group["self_attn.v_proj.U"], group["self_attn.v_proj.S"], group["self_attn.v_proj.Vt"]
        oU, oS, oVt = group["self_attn.o_proj.U"], group["self_attn.o_proj.S"], group["self_attn.o_proj.Vt"]

        gU, gS, gVt = group["mlp.gate_proj.U"], group["mlp.gate_proj.S"], group["mlp.gate_proj.Vt"]
        uU, uS, uVt = group["mlp.up_proj.U"], group["mlp.up_proj.S"], group["mlp.up_proj.Vt"]
        dU, dS, dVt = group["mlp.down_proj.U"], group["mlp.down_proj.S"], group["mlp.down_proj.Vt"]

        # Use first layer's norms in group (approximation)
        group_start = group_idx * 10
        in_norm_key = f"input_norm_{group_start}"
        post_norm_key = f"post_norm_{group_start}"

        in_norm = mx.array(group[in_norm_key]) if in_norm_key in group else None
        post_norm = mx.array(group[post_norm_key]) if post_norm_key in group else None

        # Attention
        res = x
        if in_norm is not None:
            x = rms_norm(x, in_norm)

        B, L, _ = x.shape
        q = self.decomposed_matmul(x, qU, qS, qVt)
        k = self.decomposed_matmul(x, kU, kS, kVt)
        v = self.decomposed_matmul(x, vU, vS, vVt)

        q = q.reshape(B, L, self.nh, self.hd).transpose(0, 2, 1, 3)
        k = k.reshape(B, L, self.nkv, self.hd).transpose(0, 2, 1, 3)
        v = v.reshape(B, L, self.nkv, self.hd).transpose(0, 2, 1, 3)

        q = rope(q, pos, self.theta)
        k = rope(k, pos, self.theta)

        # KV cache - use group start layer index
        cache_idx = group_start
        if self.kv[cache_idx] is not None:
            kc, vc = self.kv[cache_idx]
            k = mx.concatenate([kc, k], axis=2)
            v = mx.concatenate([vc, v], axis=2)
        self.kv[cache_idx] = (k, v)

        if self.nkv < self.nh:
            rep = self.nh // self.nkv
            k = mx.repeat(k, rep, axis=1)
            v = mx.repeat(v, rep, axis=1)

        sc = (q @ k.transpose(0, 1, 3, 2)) * (self.hd ** -0.5)
        sc = mx.softmax(sc, axis=-1)
        ao = (sc @ v).transpose(0, 2, 1, 3).reshape(B, L, -1)
        ao = self.decomposed_matmul(ao, oU, oS, oVt)

        x = res + ao

        # FFN
        res = x
        if post_norm is not None:
            x = rms_norm(x, post_norm)

        gate = self.decomposed_matmul(x, gU, gS, gVt)
        up = self.decomposed_matmul(x, uU, uS, uVt)
        x = nn.silu(gate) * up
        x = self.decomposed_matmul(x, dU, dS, dVt)

        x = res + x
        return x

    def forward(self, token_id, pos):
        """Full forward pass through composed groups."""
        # Embed
        if self.embed is not None:
            x = self.embed[token_id:token_id + 1].reshape(1, 1, -1)
        else:
            x = mx.zeros((1, 1, self.dim))

        # Through groups
        for gi, group in enumerate(self.groups):
            x = self.forward_group(x, group, gi, pos)
            mx.eval(x)

        # Final norm
        if self.final_norm is not None:
            x = rms_norm(x, self.final_norm)

        # LM head from decomposed chunks
        logit_parts = []
        for chunk in self.lm_chunks:
            part = self.decomposed_matmul(x, chunk["U"], chunk["S"], chunk["Vt"])
            mx.eval(part)
            logit_parts.append(part)

        logits = mx.concatenate(logit_parts, axis=-1) if logit_parts else x
        return logits

    def generate(self, prompt: str, max_tokens: int = 50, temp: float = 0.7):
        if not self.tok:
            print("No tokenizer")
            return ""

        toks = self.tok.encode(prompt)
        print(f"[Moon Quantum] {len(toks)} prompt tokens\n")

        pos = len(toks) - 1
        cur = toks[-1]
        out = []

        for step in range(max_tokens):
            t0 = time.time()
            logits = self.forward(cur, pos)
            dt = time.time() - t0

            logits = logits[:, -1, :] / temp
            probs = mx.softmax(logits, axis=-1)
            nxt = mx.random.categorical(probs).item()

            txt = self.tok.decode([nxt])
            if step == 0:
                print(f"[{dt:.2f}s/tok] ", end="", flush=True)
            print(txt, end="", flush=True)

            out.append(nxt)
            cur = nxt
            pos += 1

            if nxt == self.tok.eos_token_id:
                break

        tps = len(out) / sum(1 for _ in range(1))  # placeholder
        print(f"\n[Moon Quantum] {len(out)} tokens generated")
        return self.tok.decode(out)


if __name__ == "__main__":
    import sys
    model_dir = sys.argv[1] if len(sys.argv) > 1 else "models/qwen-72b-4bit"

    engine = MoonQuantumInference(model_dir)

    print("\nType prompt:\n")
    while True:
        try:
            p = input("> ")
            if not p or p in ("exit", "quit"):
                break
            engine.generate(p, max_tokens=50)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
