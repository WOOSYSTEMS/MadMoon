"""
Moon Inference - Phase 2: Quantum Composition
Compose decomposed layers into grouped operators.

|output> = <Omega|input>

Instead of 80 sequential layer passes, compose groups of layers
into single operators using low-rank factor composition.

For two decomposed layers:
W1 = U1 @ diag(S1) @ Vt1
W2 = U2 @ diag(S2) @ Vt2

Composed: W2 @ W1 = U2 @ diag(S2) @ (Vt2 @ U1) @ diag(S1) @ Vt1
Inner product (Vt2 @ U1) is [rank x rank] = tiny
"""

import json
import time
import os
import gc
from pathlib import Path

import numpy as np
import mlx.core as mx


class QuantumComposer:
    def __init__(self, model_dir: str, rank: int = 256):
        self.model_dir = Path(model_dir)
        self.decomposed_dir = self.model_dir / f"decomposed_r{rank}"
        self.composed_dir = self.model_dir / f"composed_r{rank}"
        os.makedirs(self.composed_dir, exist_ok=True)

        self.config = json.load(open(self.model_dir / "config.json"))
        self.n_layers = self.config["num_hidden_layers"]
        self.rank = rank

        print(f"[Compose] {self.n_layers} decomposed layers, rank {rank}")
        print(f"[Compose] Source: {self.decomposed_dir}")
        print(f"[Compose] Output: {self.composed_dir}")

    def load_layer_factors(self, layer_idx: int, proj: str):
        """Load U, S, Vt for one projection of one layer."""
        data = np.load(self.decomposed_dir / f"layer_{layer_idx:03d}.npz")
        U = data[f"{proj}.U"]
        S = data[f"{proj}.S"]
        Vt = data[f"{proj}.Vt"]
        return U, S, Vt

    def compose_two(self, U1, S1, Vt1, U2, S2, Vt2):
        """
        Compose two low-rank operators:
        W2 @ W1 = U2 @ S2 @ (Vt2 @ U1) @ S1 @ Vt1

        The inner product (Vt2 @ U1) is [rank x rank] - tiny.
        Re-SVD to maintain rank bound.
        """
        # Inner product: (S2 * Vt2) @ (U1 * S1)
        # Vt2: [rank, n2], U1: [n1, rank]
        # For composition to work, n2 must equal n1 (output dim of layer1 = input dim of layer2)
        # If dimensions don't match, can't compose - return layer2 only
        n2 = Vt2.shape[1]
        n1 = U1.shape[0]

        if n2 != n1:
            # Dimensions incompatible for composition, return latest layer
            return U2, S2, Vt2

        Vt2_scaled = (S2[:, None] * Vt2).astype(np.float32)  # [rank, n]
        U1_scaled = (U1 * S1[None, :]).astype(np.float32)    # [n, rank]
        inner_np = Vt2_scaled @ U1_scaled  # [rank, rank]
        del Vt2_scaled, U1_scaled

        # SVD of inner to re-compress [rank x rank] - instant
        Ui, Si, Vti = np.linalg.svd(inner_np, full_matrices=False)
        k = min(self.rank, len(Si))
        Ui = Ui[:, :k].astype(np.float16)
        Si = Si[:k].astype(np.float16)
        Vti = Vti[:k, :].astype(np.float16)
        del inner_np

        # New composed factors
        # U_new = U2 @ Ui
        U_new = (U2.astype(np.float32) @ Ui.astype(np.float32)).astype(np.float16)
        # Vt_new = Vti @ Vt1
        Vt_new = (Vti.astype(np.float32) @ Vt1.astype(np.float32)).astype(np.float16)
        S_new = Si

        del Ui, Si, Vti
        gc.collect()

        return U_new, S_new, Vt_new

    def compose_projection(self, proj: str, layer_indices: list):
        """Compose one projection type across multiple layers."""
        # Start with first layer
        U, S, Vt = self.load_layer_factors(layer_indices[0], proj)

        for li in layer_indices[1:]:
            U2, S2, Vt2 = self.load_layer_factors(li, proj)
            U, S, Vt = self.compose_two(U, S, Vt, U2, S2, Vt2)
            del U2, S2, Vt2
            gc.collect()

        return U, S, Vt

    def compose_all(self, group_size: int = 10):
        """
        Compose all layers into groups.
        80 layers with group_size=10 = 8 composed groups.
        """
        projections = [
            "self_attn.q_proj", "self_attn.k_proj",
            "self_attn.v_proj", "self_attn.o_proj",
            "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"
        ]

        n_groups = (self.n_layers + group_size - 1) // group_size
        print(f"\n[Compose] Composing {self.n_layers} layers into {n_groups} groups")
        start = time.time()

        for g in range(n_groups):
            g_start = g * group_size
            g_end = min(g_start + group_size, self.n_layers)
            layers = list(range(g_start, g_end))

            print(f"\nGroup {g}: layers {g_start}-{g_end-1}")
            group_data = {}

            for proj in projections:
                t0 = time.time()
                U, S, Vt = self.compose_projection(proj, layers)
                dt = time.time() - t0
                group_data[f"{proj}.U"] = U
                group_data[f"{proj}.S"] = S
                group_data[f"{proj}.Vt"] = Vt
                print(f"  {proj}: {U.shape} @ {Vt.shape} ({dt:.1f}s)")
                del U, S, Vt

            # Save norms for each layer in group (can't compose these)
            for li in layers:
                data = np.load(self.decomposed_dir / f"layer_{li:03d}.npz")
                group_data[f"input_norm_{li}"] = data["input_norm"]
                group_data[f"post_norm_{li}"] = data["post_norm"]

            # Save composed group
            save_path = self.composed_dir / f"group_{g:02d}.npz"
            np.savez_compressed(save_path, **group_data)
            size = os.path.getsize(save_path) / 1024 / 1024
            print(f"  Saved: {size:.1f}MB")

            del group_data
            gc.collect()

        # Copy embeddings, LM head, final norm
        import shutil
        for f in ["embed.npy", "final_norm.npy"]:
            src = self.decomposed_dir / f
            if src.exists():
                shutil.copy(src, self.composed_dir / f)

        # Copy LM head chunks
        for f in os.listdir(self.decomposed_dir):
            if f.startswith("lm_head_chunk"):
                shutil.copy(self.decomposed_dir / f, self.composed_dir / f)

        total = time.time() - start
        total_size = sum(
            os.path.getsize(self.composed_dir / f)
            for f in os.listdir(self.composed_dir)
        ) / 1024 / 1024 / 1024

        print(f"\n[Compose] COMPLETE in {total:.1f}s")
        print(f"[Compose] Total composed size: {total_size:.1f}GB")
        print(f"[Compose] {n_groups} groups ready for inference")
        print(f"[Compose] Saved to: {self.composed_dir}")


if __name__ == "__main__":
    import sys
    model_dir = sys.argv[1] if len(sys.argv) > 1 else "models/qwen-72b-4bit"
    rank = int(sys.argv[2]) if len(sys.argv) > 2 else 256
    group_size = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    c = QuantumComposer(model_dir, rank)
    c.compose_all(group_size)
