"""
Moon Inference - Vaccine Engine
Full attention (the vaccine) + decomposed FFN (the immune system).

Attention = quality critical, stays full weights in GPU.
FFN = redundant, decomposed to save memory.
Error resets every layer because attention is exact.

Test on 3B first. Scale to 14B if quality holds.
"""

import json
import time
import struct
import mmap
import gc
import os
from pathlib import Path

import numpy as np
import mlx.core as mx
import mlx.nn as nn


class VaccineCompiler:
    """
    Load model with:
    - FULL quantized attention weights (in GPU)
    - DECOMPOSED FFN weights (in GPU, smaller)
    - Full norms and embeddings
    """

    def __init__(self, model_dir: str, ffn_rank: int = 128):
        self.dir = Path(model_dir)
        self.config = json.load(open(self.dir / "config.json"))
        self.nl = self.config["num_hidden_layers"]
        self.dim = self.config["hidden_size"]
        self.nh = self.config["num_attention_heads"]
        self.nkv = self.config.get("num_key_value_heads", self.nh)
        self.hd = self.dim // self.nh
        self.ffn_dim = self.config["intermediate_size"]
        self.vocab = self.config["vocab_size"]
        self.theta = self.config.get("rope_theta", 1000000.0)
        self.ffn_rank = ffn_rank

        # Load safetensors index
        idx_path = self.dir / "model.safetensors.index.json"
        if idx_path.exists():
            self.index = json.load(open(idx_path))
            self.wmap = self.index["weight_map"]
        else:
            self.wmap = None

        self._fh = {}

        try:
            from transformers import AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(str(self.dir), trust_remote_code=True)
        except:
            self.tok = None

        print(f"[Vaccine] {self.nl}L {self.dim}D | FFN rank {ffn_rank}")

    def _load(self, name):
        if self.wmap:
            fn = self.wmap.get(name)
            if not fn:
                return None
        else:
            fn = "model.safetensors"

        if fn not in self._fh:
            f = open(self.dir / fn, "rb")
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            hs = struct.unpack("<Q", mm[:8])[0]
            hdr = json.loads(mm[8:8 + hs])
            self._fh[fn] = (f, mm, 8 + hs, hdr)

        f, mm, do, hdr = self._fh[fn]
        if name not in hdr:
            return None
        m = hdr[name]
        dt, sh = m["dtype"], m.get("shape", [])
        s, e = m["data_offsets"]
        raw = mm[s + do:e + do]

        if dt in ("F16", "float16"):
            return mx.array(np.frombuffer(raw, np.float16).reshape(sh))
        elif dt in ("U32", "uint32"):
            return mx.array(np.frombuffer(raw, np.uint32).reshape(sh), dtype=mx.uint32)
        elif dt in ("BF16", "bfloat16"):
            return mx.array(np.frombuffer(raw, np.uint16).reshape(sh), dtype=mx.bfloat16)
        elif dt in ("F32", "float32"):
            return mx.array(np.frombuffer(raw, np.float32).reshape(sh))
        return mx.array(np.frombuffer(raw, np.float16).reshape(sh))

    def _load_q(self, prefix):
        w = self._load(f"{prefix}.weight")
        s = self._load(f"{prefix}.scales")
        b = self._load(f"{prefix}.biases")
        return (w, s, b) if w is not None else None

    def _decompose_ffn(self, prefix):
        """Load FFN weight, dequantize, SVD decompose, return factors."""
        w, s, b = self._load(f"{prefix}.weight"), self._load(f"{prefix}.scales"), self._load(f"{prefix}.biases")
        if w is None:
            return None

        # Dequantize
        dense = mx.dequantize(w, s, b, group_size=64, bits=4)
        mx.eval(dense)
        dense_np = np.array(dense, dtype=np.float32)
        del w, s, b, dense

        # GPU-accelerated randomized SVD
        m, n = dense_np.shape
        rank = min(self.ffn_rank, min(m, n))

        A = mx.array(dense_np)
        omega = mx.random.normal((n, rank + 10))
        Y = A @ omega
        mx.eval(Y)
        del omega

        Y_np = np.array(Y, dtype=np.float32)
        del Y
        Q, _ = np.linalg.qr(Y_np)
        Q = Q[:, :rank]
        del Y_np

        Q_mx = mx.array(Q.astype(np.float16))
        B = Q_mx.T @ A
        mx.eval(B)
        del A, Q_mx

        B_np = np.array(B, dtype=np.float32)
        del B
        Ub, S, Vt = np.linalg.svd(B_np, full_matrices=False)
        Ub = Ub[:rank, :rank].astype(np.float16)
        S = S[:rank].astype(np.float16)
        Vt = Vt[:rank, :].astype(np.float16)
        del B_np

        U = (Q[:, :rank].astype(np.float16) @ Ub).astype(np.float16)
        del Q, Ub, dense_np
        gc.collect()

        return (mx.array(U), mx.array(S), mx.array(Vt))

    def compile(self):
        """Compile: full attention + decomposed FFN."""
        print(f"[Vaccine] Compiling...", flush=True)
        t0 = time.time()

        self.layers = []
        for li in range(self.nl):
            prefix = f"model.layers.{li}"
            layer = {}

            # FULL attention weights (the vaccine)
            for proj in ["self_attn.q_proj", "self_attn.k_proj",
                         "self_attn.v_proj", "self_attn.o_proj"]:
                layer[proj] = self._load_q(f"{prefix}.{proj}")

            # DECOMPOSED FFN weights (the immune system)
            for proj in ["mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"]:
                print(f"  [{li}] decomposing {proj}...", end="", flush=True)
                factors = self._decompose_ffn(f"{prefix}.{proj}")
                layer[proj] = factors
                if factors:
                    print(f" {factors[0].shape}", flush=True)
                else:
                    print(" skip", flush=True)

            layer["in_norm"] = self._load(f"{prefix}.input_layernorm.weight")
            layer["post_norm"] = self._load(f"{prefix}.post_attention_layernorm.weight")

            self.layers.append(layer)
            print(f"  Layer {li+1}/{self.nl} done", flush=True)

        # Embeddings (full)
        self.embed = self._load_q("model.embed_tokens")
        self.final_norm = self._load("model.norm.weight")

        # LM head (tied or separate)
        lm = self._load_q("lm_head")
        self.lm_head = lm if lm and lm[0] is not None else self.embed

        # Close files
        for f, mm, _, _ in self._fh.values():
            mm.close()
            f.close()
        self._fh = {}

        dt = time.time() - t0
        print(f"\n[Vaccine] Compiled in {dt:.1f}s. No disk access during inference.")

        self.kv = [None] * self.nl
        return self


class VaccineInference:
    def __init__(self, compiler: VaccineCompiler):
        self.c = compiler

    def qmm(self, x, wt):
        w, s, b = wt
        return mx.quantized_matmul(x, w, scales=s, biases=b,
                                    transpose=True, group_size=64, bits=4)

    def dmm(self, x, factors):
        """Decomposed matmul via SVD factors."""
        U, S, Vt = factors
        return (x @ Vt.T) * S @ U.T

    def rope(self, x, pos):
        dim = x.shape[-1]
        f = 1.0 / (self.c.theta ** (mx.arange(0, dim, 2, dtype=mx.float32) / dim))
        ang = mx.array([pos], dtype=mx.float32)[:, None] * f[None, :]
        c, s = mx.cos(ang), mx.sin(ang)
        x1, x2 = x[..., ::2], x[..., 1::2]
        return mx.concatenate([x1 * c - x2 * s, x1 * s + x2 * c], axis=-1)

    def norm(self, x, w, eps=1e-6):
        return x * mx.rsqrt(mx.mean(x * x, axis=-1, keepdims=True) + eps) * w

    def forward(self, token_id, pos):
        # Embed
        e = mx.dequantize(self.c.embed[0], self.c.embed[1], self.c.embed[2],
                          group_size=64, bits=4)
        x = e[token_id:token_id+1].reshape(1, 1, -1)
        del e

        for li in range(self.c.nl):
            L = self.c.layers[li]

            # FULL ATTENTION (vaccine - exact, resets errors)
            res = x
            x = self.norm(x, L["in_norm"])
            B, Len, _ = x.shape

            q = self.qmm(x, L["self_attn.q_proj"])
            k = self.qmm(x, L["self_attn.k_proj"])
            v = self.qmm(x, L["self_attn.v_proj"])

            q = q.reshape(B, Len, self.c.nh, self.c.hd).transpose(0, 2, 1, 3)
            k = k.reshape(B, Len, self.c.nkv, self.c.hd).transpose(0, 2, 1, 3)
            v = v.reshape(B, Len, self.c.nkv, self.c.hd).transpose(0, 2, 1, 3)

            q = self.rope(q, pos)
            k = self.rope(k, pos)

            if self.c.kv[li] is not None:
                kc, vc = self.c.kv[li]
                k = mx.concatenate([kc, k], axis=2)
                v = mx.concatenate([vc, v], axis=2)
            self.c.kv[li] = (k, v)

            if self.c.nkv < self.c.nh:
                k = mx.repeat(k, self.c.nh // self.c.nkv, axis=1)
                v = mx.repeat(v, self.c.nh // self.c.nkv, axis=1)

            sc = mx.softmax((q @ k.transpose(0, 1, 3, 2)) * (self.c.hd ** -0.5), axis=-1)
            ao = (sc @ v).transpose(0, 2, 1, 3).reshape(B, Len, -1)
            ao = self.qmm(ao, L["self_attn.o_proj"])
            x = res + ao

            # DECOMPOSED FFN (immune system - approximate but guided by attention)
            res = x
            x = self.norm(x, L["post_norm"])

            gate = self.dmm(x, L["mlp.gate_proj"])
            up = self.dmm(x, L["mlp.up_proj"])
            x = nn.silu(gate) * up
            x = self.dmm(x, L["mlp.down_proj"])

            x = res + x

        x = self.norm(x, self.c.final_norm)
        logits = self.qmm(x, self.c.lm_head)
        return logits

    def generate(self, prompt, max_tokens=50, temp=0.7):
        if not self.c.tok:
            return ""
        toks = self.c.tok.encode(prompt)
        print(f"[Vaccine] {len(toks)} tokens\n", flush=True)

        pos = len(toks) - 1
        cur = toks[-1]
        out = []
        total = 0

        for step in range(max_tokens):
            t0 = time.time()
            logits = self.forward(cur, pos)
            mx.eval(logits)
            dt = time.time() - t0
            total += dt

            logits = logits[:, -1, :] / temp
            probs = mx.softmax(logits, axis=-1)
            nxt = mx.random.categorical(probs).item()

            txt = self.c.tok.decode([nxt])
            if step == 0:
                print(f"[{dt*1000:.0f}ms] ", end="", flush=True)
            print(txt, end="", flush=True)

            out.append(nxt)
            cur = nxt
            pos += 1
            if nxt == self.c.tok.eos_token_id:
                break

        avg = total / max(len(out), 1)
        tps = 1.0 / avg if avg > 0 else 0
        print(f"\n[Vaccine] {len(out)} tok | {avg*1000:.0f}ms/tok | {tps:.1f} tok/s")
        return self.c.tok.decode(out)


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "models/qwen-3b-4bit"
    rank = int(sys.argv[2]) if len(sys.argv) > 2 else 128

    compiler = VaccineCompiler(d, ffn_rank=rank).compile()
    engine = VaccineInference(compiler)
    engine.generate("What is quantum physics?", max_tokens=30)
