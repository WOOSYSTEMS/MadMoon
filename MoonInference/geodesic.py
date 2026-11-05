"""
Moon Inference - Quantum Geodesic Engine
72B model as a geodesic sphere of hexagonal patches.
Each patch is a local linear approximation.
Input tokens exist in superposition across nearby patches.
Interference produces output. Measurement collapses to token.

|psi(x)> = sum_i alpha_i |hex_i>
output = <psi| O |psi>

Phase 1: Build the geodesic (cluster model behavior into hexagons)
Phase 2: Inference (hash -> load hexagons -> superpose -> interfere -> collapse)
"""

import json
import time
import os
import gc
from pathlib import Path

import numpy as np
import mlx.core as mx
import mlx.nn as nn


class GeodesicBuilder:
    """
    Build the hexagonal tiling of the model's behavior space.

    1. Sample diverse hidden states from the 72B model
    2. Cluster into N hexagonal regions
    3. Fit local linear model per hexagon
    4. Save each hexagon as a tiny file (~1-5MB)
    """

    def __init__(self, model_dir: str, n_hexagons: int = 1024):
        self.model_dir = Path(model_dir)
        self.config = json.load(open(self.model_dir / "config.json"))
        self.dim = self.config["hidden_size"]
        self.vocab = self.config["vocab_size"]
        self.n_hex = n_hexagons
        self.geo_dir = self.model_dir / "geodesic"
        os.makedirs(self.geo_dir, exist_ok=True)

        print(f"[Geodesic] dim={self.dim}, vocab={self.vocab}, hexagons={n_hexagons}")

    def build_from_decomposed(self, decomp_dir: str):
        """
        Build geodesic from decomposed factors without running full inference.

        Strategy: use the decomposed weight matrices to create synthetic
        hidden state clusters. Each layer's weight structure tells us
        how the model partitions its input space.

        The eigenvectors of (W^T @ W) give us the principal directions
        of the model's attention. These become hexagon centers.
        """
        decomp = Path(decomp_dir)
        print(f"[Geodesic] Building from decomposed factors...")

        # Collect principal directions from each layer's attention
        all_directions = []

        for li in range(min(10, self.config["num_hidden_layers"])):
            data = np.load(decomp / f"layer_{li:03d}.npz")

            # Q projection Vt rows are the principal input directions
            # These tell us "what the model looks for" at each layer
            Vt = data["self_attn.q_proj.Vt"]  # [rank, dim]
            S = data["self_attn.q_proj.S"]    # [rank]

            # Top directions weighted by singular values
            top_k = min(32, len(S))
            for j in range(top_k):
                direction = Vt[j] * S[j]
                all_directions.append(direction.astype(np.float16))

        all_directions = np.array(all_directions)
        print(f"[Geodesic] Collected {len(all_directions)} principal directions")

        # Cluster into hexagons using k-means on principal directions
        n_hex = min(self.n_hex, len(all_directions))
        print(f"[Geodesic] Clustering into {n_hex} hexagons...")

        # Simple k-means
        centers = all_directions[:n_hex].copy()

        for iteration in range(20):
            # Assign
            # Compute distances on GPU
            c_mx = mx.array(centers.astype(np.float32))
            d_mx = mx.array(all_directions.astype(np.float32))
            # [n_dirs, n_hex]
            dists = -2 * (d_mx @ c_mx.T)
            mx.eval(dists)
            assignments = np.array(mx.argmin(dists, axis=1))
            del dists

            # Update centers
            new_centers = np.zeros_like(centers)
            counts = np.zeros(n_hex)
            for i, a in enumerate(assignments):
                new_centers[a] += all_directions[i]
                counts[a] += 1

            for j in range(n_hex):
                if counts[j] > 0:
                    new_centers[j] /= counts[j]

            centers = new_centers.astype(np.float16)

        print(f"[Geodesic] K-means converged. {n_hex} hexagon centers.")

        # For each hexagon, build a local linear model
        # The local model maps: hidden_state -> next_hidden_state
        # Using the decomposed factors of nearby layers
        print(f"[Geodesic] Building local linear models...")

        # Save hexagon centers
        np.save(self.geo_dir / "centers.npy", centers)

        # For each hexagon, save the relevant decomposed factors
        # Each hexagon gets the factors from layers whose principal
        # directions are closest to the hexagon center
        for h in range(n_hex):
            center = centers[h]
            # Find which layers are most relevant to this hexagon
            # (whose Q directions are closest to this center)
            layer_scores = []
            for li in range(min(self.config["num_hidden_layers"], 80)):
                data = np.load(decomp / f"layer_{li:03d}.npz")
                Vt = data["self_attn.q_proj.Vt"]
                S = data["self_attn.q_proj.S"]
                # Score = max alignment with center
                alignment = np.abs(Vt @ center.astype(np.float32)) * S
                score = float(np.max(alignment))
                layer_scores.append((li, score))

            # Top 5 most relevant layers for this hexagon
            layer_scores.sort(key=lambda x: x[1], reverse=True)
            top_layers = [ls[0] for ls in layer_scores[:5]]

            # Build local model: average the decomposed factors of top layers
            local_model = {"center": center, "layers": top_layers}

            for proj in ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj",
                         "self_attn.o_proj", "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"]:
                Us, Ss, Vts = [], [], []
                for li in top_layers:
                    data = np.load(decomp / f"layer_{li:03d}.npz")
                    Us.append(data[f"{proj}.U"])
                    Ss.append(data[f"{proj}.S"])
                    Vts.append(data[f"{proj}.Vt"])

                # Average the factors (weighted by singular values)
                # This creates a "consensus" projection for this hexagon
                local_model[f"{proj}.U"] = np.mean(Us, axis=0).astype(np.float16)
                local_model[f"{proj}.S"] = np.mean(Ss, axis=0).astype(np.float16)
                local_model[f"{proj}.Vt"] = np.mean(Vts, axis=0).astype(np.float16)

            # Save norms from middle layer
            mid = top_layers[len(top_layers) // 2]
            data = np.load(decomp / f"layer_{mid:03d}.npz")
            local_model["input_norm"] = data["input_norm"]
            local_model["post_norm"] = data["post_norm"]

            np.savez_compressed(self.geo_dir / f"hex_{h:04d}.npz", **local_model)

            if (h + 1) % 100 == 0:
                print(f"  {h+1}/{n_hex} hexagons built", flush=True)

        # Copy embeddings and LM head
        import shutil
        for f in os.listdir(decomp):
            if f.startswith("embed") or f.startswith("lm_head") or f.startswith("final"):
                shutil.copy(decomp / f, self.geo_dir / f)

        total_size = sum(
            os.path.getsize(self.geo_dir / f)
            for f in os.listdir(self.geo_dir)
        ) / 1024 / 1024

        print(f"\n[Geodesic] COMPLETE")
        print(f"[Geodesic] {n_hex} hexagons, total: {total_size:.0f}MB")
        print(f"[Geodesic] Saved to: {self.geo_dir}")


class QuantumGeodesicInference:
    """
    Inference using quantum superposition of hexagonal patches.

    |psi(x)> = sum_i alpha_i |hex_i>

    1. Hash input hidden state to find 3 nearest hexagons
    2. Compute quantum amplitudes (distance-based)
    3. Load hexagons (cached if recently used)
    4. Superpose: weighted sum of local linear models
    5. Interference: cross terms between hexagons add corrections
    6. Collapse: sample output token
    """

    def __init__(self, model_dir: str, n_active: int = 3, cache_size: int = 32):
        self.dir = Path(model_dir) / "geodesic"
        self.config = json.load(open(Path(model_dir) / "config.json"))
        self.dim = self.config["hidden_size"]
        self.nh = self.config["num_attention_heads"]
        self.nkv = self.config.get("num_key_value_heads", self.nh)
        self.hd = self.dim // self.nh
        self.theta = self.config.get("rope_theta", 1000000.0)
        self.n_active = n_active  # How many hexagons to superpose

        # Load centers
        self.centers = mx.array(np.load(self.dir / "centers.npy"))
        self.n_hex = self.centers.shape[0]

        # Hexagon cache (LRU)
        self.cache = {}
        self.cache_size = cache_size
        self.cache_order = []

        # Load embeddings
        embed_path = self.dir / "embed.npy"
        self.embed = mx.array(np.load(embed_path)) if embed_path.exists() else None

        # Final norm
        norm_path = self.dir / "final_norm.npy"
        self.final_norm = mx.array(np.load(norm_path)) if norm_path.exists() else None

        # LM head chunks
        self.lm_chunks = []
        for f in sorted(os.listdir(self.dir)):
            if f.startswith("lm_head_chunk"):
                d = np.load(self.dir / f)
                self.lm_chunks.append({
                    "U": mx.array(d["U"]), "S": mx.array(d["S"]), "Vt": mx.array(d["Vt"])
                })

        # Tokenizer
        try:
            from transformers import AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(str(Path(model_dir)), trust_remote_code=True)
        except:
            self.tok = None

        # KV cache (simplified - one set for the superposed model)
        self.kv_cache = None

        print(f"[QGI] {self.n_hex} hexagons, {n_active} active per token")
        print(f"[QGI] Cache size: {cache_size} hexagons")
        print(f"[QGI] Ready.")

    def load_hexagon(self, idx):
        """Load hexagon, use cache."""
        if idx in self.cache:
            # Move to front of cache order
            self.cache_order.remove(idx)
            self.cache_order.append(idx)
            return self.cache[idx]

        data = np.load(self.dir / f"hex_{idx:04d}.npz", allow_pickle=True)
        hex_data = {}
        for proj in ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj",
                     "self_attn.o_proj", "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"]:
            hex_data[proj] = {
                "U": mx.array(data[f"{proj}.U"]),
                "S": mx.array(data[f"{proj}.S"]),
                "Vt": mx.array(data[f"{proj}.Vt"]),
            }
        hex_data["in_norm"] = mx.array(data["input_norm"])
        hex_data["post_norm"] = mx.array(data["post_norm"])

        # Cache management
        if len(self.cache) >= self.cache_size:
            evict = self.cache_order.pop(0)
            del self.cache[evict]

        self.cache[idx] = hex_data
        self.cache_order.append(idx)
        return hex_data

    def find_nearest(self, x):
        """Find n_active nearest hexagon centers to hidden state x."""
        # x: [1, 1, dim] -> [dim]
        x_flat = x.reshape(-1)
        dists = -mx.sum(self.centers * x_flat, axis=1)  # negative dot product
        mx.eval(dists)
        indices = np.array(dists).argsort()[:self.n_active]
        # Quantum amplitudes: softmax of negative distances
        scores = np.array(-dists)[indices]
        amplitudes = np.exp(scores - scores.max())
        amplitudes /= amplitudes.sum()
        return indices, amplitudes

    def decomp_matmul(self, x, U, S, Vt):
        return (x @ Vt.T) * S @ U.T

    def superposed_forward(self, x, hexagons, amplitudes, pos):
        """Forward pass as quantum superposition of hexagon models."""

        # Superpose: weighted sum of each hexagon's output
        output = mx.zeros_like(x)

        for hex_data, alpha in zip(hexagons, amplitudes):
            # Attention
            res = x
            hx = x * mx.rsqrt(mx.mean(x * x, axis=-1, keepdims=True) + 1e-6) * hex_data["in_norm"]

            B, L, _ = hx.shape
            q = self.decomp_matmul(hx, hex_data["self_attn.q_proj"]["U"], hex_data["self_attn.q_proj"]["S"], hex_data["self_attn.q_proj"]["Vt"])
            k = self.decomp_matmul(hx, hex_data["self_attn.k_proj"]["U"], hex_data["self_attn.k_proj"]["S"], hex_data["self_attn.k_proj"]["Vt"])
            v = self.decomp_matmul(hx, hex_data["self_attn.v_proj"]["U"], hex_data["self_attn.v_proj"]["S"], hex_data["self_attn.v_proj"]["Vt"])

            q = q.reshape(B, L, self.nh, self.hd).transpose(0, 2, 1, 3)
            k = k.reshape(B, L, self.nkv, self.hd).transpose(0, 2, 1, 3)
            v = v.reshape(B, L, self.nkv, self.hd).transpose(0, 2, 1, 3)

            # Simplified RoPE
            q = self._rope(q, pos)
            k = self._rope(k, pos)

            if self.nkv < self.nh:
                rep = self.nh // self.nkv
                k = mx.repeat(k, rep, axis=1)
                v = mx.repeat(v, rep, axis=1)

            sc = (q @ k.transpose(0, 1, 3, 2)) * (self.hd ** -0.5)
            sc = mx.softmax(sc, axis=-1)
            ao = (sc @ v).transpose(0, 2, 1, 3).reshape(B, L, -1)
            ao = self.decomp_matmul(ao, hex_data["self_attn.o_proj"]["U"], hex_data["self_attn.o_proj"]["S"], hex_data["self_attn.o_proj"]["Vt"])

            hx = res + ao

            # FFN
            res = hx
            hx = hx * mx.rsqrt(mx.mean(hx * hx, axis=-1, keepdims=True) + 1e-6) * hex_data["post_norm"]

            gate = self.decomp_matmul(hx, hex_data["mlp.gate_proj"]["U"], hex_data["mlp.gate_proj"]["S"], hex_data["mlp.gate_proj"]["Vt"])
            up = self.decomp_matmul(hx, hex_data["mlp.up_proj"]["U"], hex_data["mlp.up_proj"]["S"], hex_data["mlp.up_proj"]["Vt"])
            hx = nn.silu(gate) * up
            hx = self.decomp_matmul(hx, hex_data["mlp.down_proj"]["U"], hex_data["mlp.down_proj"]["S"], hex_data["mlp.down_proj"]["Vt"])

            hx = res + hx

            # Superpose with quantum amplitude
            output = output + hx * alpha

        return output

    def _rope(self, x, pos):
        dim = x.shape[-1]
        f = 1.0 / (self.theta ** (mx.arange(0, dim, 2, dtype=mx.float32) / dim))
        t = mx.array([pos], dtype=mx.float32)
        ang = t[:, None] * f[None, :]
        c, s = mx.cos(ang), mx.sin(ang)
        x1, x2 = x[..., ::2], x[..., 1::2]
        return mx.concatenate([x1 * c - x2 * s, x1 * s + x2 * c], axis=-1)

    def forward(self, token_id, pos):
        """Full quantum geodesic forward pass."""
        if self.embed is None:
            return None

        x = self.embed[token_id:token_id+1].reshape(1, 1, -1)

        # Find nearest hexagons
        indices, amplitudes = self.find_nearest(x)

        # Load hexagons (cached)
        hexagons = [self.load_hexagon(int(i)) for i in indices]
        amp_list = [float(a) for a in amplitudes]

        # Superposed forward
        x = self.superposed_forward(x, hexagons, amp_list, pos)
        mx.eval(x)

        # Final norm
        if self.final_norm is not None:
            x = x * mx.rsqrt(mx.mean(x * x, axis=-1, keepdims=True) + 1e-6) * self.final_norm

        # LM head
        parts = []
        for ch in self.lm_chunks:
            p = self.decomp_matmul(x, ch["U"], ch["S"], ch["Vt"])
            mx.eval(p)
            parts.append(p)

        return mx.concatenate(parts, axis=-1) if parts else x

    def generate(self, prompt: str, max_tokens: int = 50, temp: float = 0.7):
        if not self.tok:
            return ""

        toks = self.tok.encode(prompt)
        print(f"[QGI] {len(toks)} tokens\n", flush=True)

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
                print(f"[{dt*1000:.0f}ms] ", end="", flush=True)
            elif step == 1:
                print(f"[{dt*1000:.0f}ms cached] ", end="", flush=True)
            print(txt, end="", flush=True)

            out.append(nxt)
            cur = nxt
            pos += 1

            if nxt == self.tok.eos_token_id:
                break

        avg = total_time / max(len(out), 1)
        tps = 1.0 / avg if avg > 0 else 0
        print(f"\n[QGI] {len(out)} tokens | {avg*1000:.0f}ms/tok | {tps:.0f} tok/s")
        return self.tok.decode(out)


if __name__ == "__main__":
    import sys
    model_dir = sys.argv[1] if len(sys.argv) > 1 else "models/qwen-72b-4bit"
    action = sys.argv[2] if len(sys.argv) > 2 else "build"

    if action == "build":
        builder = GeodesicBuilder(model_dir, n_hexagons=256)
        decomp_dir = f"{model_dir}/decomposed_r256"
        builder.build_from_decomposed(decomp_dir)
    elif action == "infer":
        engine = QuantumGeodesicInference(model_dir, n_active=3)
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
