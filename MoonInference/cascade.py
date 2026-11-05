"""
Moon Inference - Cascaded Filtration Engine
Water filtration for neural networks.

Stage 1: Rank-256 decomposed (ALL in RAM, 3GB) runs all 80 layers FAST
         Output is garbage for text BUT hidden state deltas reveal
         which layers are IMPORTANT for this specific input.

Stage 2: Top-K important layers re-run with FULL quantized weights from SSD.
         These layers use native quantized matmul. Perfect quality.

Stage 3: Output from the corrected important layers produces coherent text.

Like water filtration:
- Coarse filter (rank-256): catches the big patterns, identifies what matters
- Fine filter (full weights): perfects only what matters
- Result: clean output at fraction of the full model cost
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


class MMapStore:
    def __init__(self, model_dir):
        self.dir = Path(model_dir)
        self.index = json.load(open(self.dir / "model.safetensors.index.json"))
        self.map = self.index["weight_map"]
        self._fh = {}

    def _open(self, fn):
        if fn not in self._fh:
            f = open(self.dir / fn, "rb")
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            hs = struct.unpack("<Q", mm[:8])[0]
            hdr = json.loads(mm[8:8 + hs])
            self._fh[fn] = (f, mm, 8 + hs, hdr)
        return self._fh[fn]

    def get(self, name):
        if name not in self.map:
            return None
        f, mm, do, hdr = self._open(self.map[name])
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

    def q(self, prefix):
        return self.get(f"{prefix}.weight"), self.get(f"{prefix}.scales"), self.get(f"{prefix}.biases")

    def close(self):
        for f, mm, _, _ in self._fh.values():
            mm.close()
            f.close()


class CascadeMoon:
    def __init__(self, model_dir, rank=256, top_k=15):
        self.model_dir = Path(model_dir)
        self.decomp_dir = self.model_dir / f"decomposed_r{rank}"
        self.store = MMapStore(str(self.model_dir))
        cfg = json.load(open(self.model_dir / "config.json"))

        self.nl = cfg["num_hidden_layers"]
        self.dim = cfg["hidden_size"]
        self.nh = cfg["num_attention_heads"]
        self.nkv = cfg.get("num_key_value_heads", self.nh)
        self.hd = self.dim // self.nh
        self.theta = cfg.get("rope_theta", 1000000.0)
        self.top_k = top_k  # How many layers get full weights

        try:
            from transformers import AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(str(self.model_dir), trust_remote_code=True)
        except:
            self.tok = None

        # Load decomposed layers (coarse filter) into RAM
        print(f"[Cascade] Loading rank-{rank} decomposed layers (coarse filter)...", flush=True)
        t0 = time.time()
        self.d_layers = []
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
            self.d_layers.append(layer)

        dt = time.time() - t0
        print(f"[Cascade] Coarse filter loaded in {dt:.1f}s", flush=True)
        print(f"[Cascade] Fine filter: top {top_k} layers from SSD (full weights)")
        print(f"[Cascade] Ready.", flush=True)

        self.kv = [None] * self.nl
        self.importance = np.zeros(self.nl)

    def decomp_layer(self, x, li, pos):
        """Fast approximate layer using decomposed weights from RAM."""
        L = self.d_layers[li]
        res = x
        x = rms_norm(x, L["in_norm"])
        B, Len, _ = x.shape

        q = decomp_mm(x, L["self_attn.q_proj"]["U"], L["self_attn.q_proj"]["S"], L["self_attn.q_proj"]["Vt"])
        k = decomp_mm(x, L["self_attn.k_proj"]["U"], L["self_attn.k_proj"]["S"], L["self_attn.k_proj"]["Vt"])
        v = decomp_mm(x, L["self_attn.v_proj"]["U"], L["self_attn.v_proj"]["S"], L["self_attn.v_proj"]["Vt"])

        q = q.reshape(B, Len, self.nh, self.hd).transpose(0, 2, 1, 3)
        k = k.reshape(B, Len, self.nkv, self.hd).transpose(0, 2, 1, 3)
        v = v.reshape(B, Len, self.nkv, self.hd).transpose(0, 2, 1, 3)
        q, k = rope(q, pos, self.theta), rope(k, pos, self.theta)

        if self.kv[li] is not None:
            kc, vc = self.kv[li]
            k = mx.concatenate([kc, k], axis=2)
            v = mx.concatenate([vc, v], axis=2)
        self.kv[li] = (k, v)

        if self.nkv < self.nh:
            k = mx.repeat(k, self.nh // self.nkv, axis=1)
            v = mx.repeat(v, self.nh // self.nkv, axis=1)

        sc = mx.softmax((q @ k.transpose(0, 1, 3, 2)) * (self.hd ** -0.5), axis=-1)
        ao = (sc @ v).transpose(0, 2, 1, 3).reshape(B, Len, -1)
        ao = decomp_mm(ao, L["self_attn.o_proj"]["U"], L["self_attn.o_proj"]["S"], L["self_attn.o_proj"]["Vt"])
        x = res + ao

        res = x
        x = rms_norm(x, L["post_norm"])
        gate = decomp_mm(x, L["mlp.gate_proj"]["U"], L["mlp.gate_proj"]["S"], L["mlp.gate_proj"]["Vt"])
        up = decomp_mm(x, L["mlp.up_proj"]["U"], L["mlp.up_proj"]["S"], L["mlp.up_proj"]["Vt"])
        x = nn.silu(gate) * up
        x = decomp_mm(x, L["mlp.down_proj"]["U"], L["mlp.down_proj"]["S"], L["mlp.down_proj"]["Vt"])
        return res + x

    def full_layer(self, x, li, pos):
        """Exact layer using full quantized weights from SSD."""
        p = f"model.layers.{li}"
        st = self.store

        res = x
        nw = st.get(f"{p}.input_layernorm.weight")
        x = rms_norm(x, nw)
        B, Len, _ = x.shape

        qw, qs, qb = st.q(f"{p}.self_attn.q_proj")
        kw, ks, kb = st.q(f"{p}.self_attn.k_proj")
        vw, vs, vb = st.q(f"{p}.self_attn.v_proj")

        q = mx.quantized_matmul(x, qw, scales=qs, biases=qb, transpose=True, group_size=64, bits=4)
        k = mx.quantized_matmul(x, kw, scales=ks, biases=kb, transpose=True, group_size=64, bits=4)
        v = mx.quantized_matmul(x, vw, scales=vs, biases=vb, transpose=True, group_size=64, bits=4)
        del qw, qs, qb, kw, ks, kb, vw, vs, vb

        q = q.reshape(B, Len, self.nh, self.hd).transpose(0, 2, 1, 3)
        k = k.reshape(B, Len, self.nkv, self.hd).transpose(0, 2, 1, 3)
        v = v.reshape(B, Len, self.nkv, self.hd).transpose(0, 2, 1, 3)
        q, k = rope(q, pos, self.theta), rope(k, pos, self.theta)

        if self.kv[li] is not None:
            kc, vc = self.kv[li]
            k = mx.concatenate([kc, k], axis=2)
            v = mx.concatenate([vc, v], axis=2)
        self.kv[li] = (k, v)

        if self.nkv < self.nh:
            k = mx.repeat(k, self.nh // self.nkv, axis=1)
            v = mx.repeat(v, self.nh // self.nkv, axis=1)

        sc = mx.softmax((q @ k.transpose(0, 1, 3, 2)) * (self.hd ** -0.5), axis=-1)
        ao = (sc @ v).transpose(0, 2, 1, 3).reshape(B, Len, -1)

        ow, os, ob = st.q(f"{p}.self_attn.o_proj")
        ao = mx.quantized_matmul(ao, ow, scales=os, biases=ob, transpose=True, group_size=64, bits=4)
        del ow, os, ob
        x = res + ao

        res = x
        nw2 = st.get(f"{p}.post_attention_layernorm.weight")
        x = rms_norm(x, nw2)

        gw, gs, gb = st.q(f"{p}.mlp.gate_proj")
        uw, us, ub = st.q(f"{p}.mlp.up_proj")
        gate = mx.quantized_matmul(x, gw, scales=gs, biases=gb, transpose=True, group_size=64, bits=4)
        up = mx.quantized_matmul(x, uw, scales=us, biases=ub, transpose=True, group_size=64, bits=4)
        del gw, gs, gb, uw, us, ub

        x = nn.silu(gate) * up
        del gate, up

        dw, ds, db = st.q(f"{p}.mlp.down_proj")
        x = mx.quantized_matmul(x, dw, scales=ds, biases=db, transpose=True, group_size=64, bits=4)
        del dw, ds, db

        return res + x

    def forward(self, token_id, pos):
        """
        Cascaded forward:
        1. Coarse pass (decomposed, RAM) - identify important layers
        2. Fine pass (full weights, SSD) - correct important layers
        """
        # Embed - only the row we need
        ew, es, eb = self.store.q("model.embed_tokens")
        cs = max(0, token_id - 4)
        ce = min(ew.shape[0], token_id + 4)
        chunk = mx.dequantize(ew[cs:ce], es[cs:ce], eb[cs:ce], group_size=64, bits=4)
        x = chunk[token_id - cs:token_id - cs + 1].reshape(1, 1, -1)
        mx.eval(x)
        del ew, es, eb, chunk

        # STAGE 1: Coarse filter - all 80 layers decomposed (fast, RAM)
        x_coarse = x
        deltas = []
        for li in range(self.nl):
            x_before = x_coarse
            x_coarse = self.decomp_layer(x_coarse, li, pos)
            if li % 20 == 19:
                mx.eval(x_coarse)
            # Track how much this layer changed the hidden state
            delta = mx.sum(mx.abs(x_coarse - x_before)).item()
            deltas.append(delta)
            self.importance[li] = 0.7 * self.importance[li] + 0.3 * delta

        # STAGE 2: Select top-K important layers
        top_layers = np.argsort(self.importance)[-self.top_k:]
        top_layers.sort()  # Keep sequential order

        # STAGE 3: Fine filter - re-run from original input through important layers
        # Use decomposed for non-important, full weights for important
        x_fine = x
        for li in range(self.nl):
            if li in top_layers:
                # Full weights from SSD - EXACT
                x_fine = self.full_layer(x_fine, li, pos)
            else:
                # Decomposed from RAM - approximate (but these layers don't matter much)
                x_fine = self.decomp_layer(x_fine, li, pos)

            if li % 10 == 9:
                mx.eval(x_fine)

        mx.eval(x_fine)

        # Final norm
        nw = self.store.get("model.norm.weight")
        x_fine = rms_norm(x_fine, nw)

        # LM head - chunked quantized
        lw, ls, lb = self.store.q("lm_head")
        chunk_sz = 16384
        parts = []
        for ci in range(0, lw.shape[0], chunk_sz):
            ce = min(ci + chunk_sz, lw.shape[0])
            p = mx.quantized_matmul(x_fine, lw[ci:ce], scales=ls[ci:ce],
                                     biases=lb[ci:ce], transpose=True,
                                     group_size=64, bits=4)
            mx.eval(p)
            parts.append(p)
        logits = mx.concatenate(parts, axis=-1)
        del lw, ls, lb, parts

        return logits, len(top_layers)

    def generate(self, prompt, max_tokens=50, temp=0.7):
        if not self.tok:
            return ""
        toks = self.tok.encode(prompt)
        print(f"[Cascade] {len(toks)} tokens | {self.top_k} fine layers\n", flush=True)

        pos = len(toks) - 1
        cur = toks[-1]
        out = []
        total = 0

        for step in range(max_tokens):
            t0 = time.time()
            logits, n_fine = self.forward(cur, pos)
            dt = time.time() - t0
            total += dt

            logits = logits[:, -1, :] / temp
            probs = mx.softmax(logits, axis=-1)
            nxt = mx.random.categorical(probs).item()

            txt = self.tok.decode([nxt])
            if step == 0:
                print(f"[{dt:.1f}s, {n_fine} fine layers] ", end="", flush=True)
            print(txt, end="", flush=True)

            out.append(nxt)
            cur = nxt
            pos += 1
            if nxt == self.tok.eos_token_id:
                break

        avg = total / max(len(out), 1)
        print(f"\n[Cascade] {len(out)} tok | {avg:.1f}s/tok | {1/avg:.2f} tok/s")
        return self.tok.decode(out)


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "models/qwen-72b-4bit"
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    m = CascadeMoon(d, top_k=k)
    m.generate("What is quantum physics?", max_tokens=20)
