"""
Moon Inference - Vaccine V2
Uses mlx_lm (proven correct) as base.
Replaces FFN layers with decomposed versions to save memory.
Full attention preserved. Quality guided by mlx_lm's correct implementation.
"""

import time
import gc
import numpy as np
import mlx.core as mx
import mlx.nn as nn
from mlx_lm import load


class DecomposedLinear(nn.Module):
    """Drop-in replacement for nn.QuantizedLinear using SVD factors."""
    def __init__(self, U, S, Vt):
        super().__init__()
        self.U = U
        self.S = S
        self.Vt = Vt

    def __call__(self, x):
        return (x @ self.Vt.T) * self.S @ self.U.T


def decompose_linear(layer, rank):
    """Decompose a QuantizedLinear into DecomposedLinear."""
    # Dequantize the original weights
    W = mx.dequantize(layer.weight, layer.scales, layer.biases,
                       group_size=layer.group_size, bits=layer.bits)
    mx.eval(W)
    W_np = np.array(W, dtype=np.float32)
    del W

    m, n = W_np.shape
    r = min(rank, min(m, n))

    # GPU-accelerated randomized SVD
    A = mx.array(W_np)
    omega = mx.random.normal((n, r + 10))
    Y = A @ omega
    mx.eval(Y)
    del omega

    Y_np = np.array(Y, dtype=np.float32)
    del Y
    Q, _ = np.linalg.qr(Y_np)
    Q = Q[:, :r]
    del Y_np

    Q_mx = mx.array(Q.astype(np.float16))
    B = Q_mx.T @ A
    mx.eval(B)
    del A, Q_mx

    B_np = np.array(B, dtype=np.float32)
    del B
    Ub, S, Vt = np.linalg.svd(B_np, full_matrices=False)
    Ub = Ub[:r, :r].astype(np.float16)
    S = S[:r].astype(np.float16)
    Vt = Vt[:r, :].astype(np.float16)
    del B_np

    U = (Q[:, :r].astype(np.float16) @ Ub).astype(np.float16)
    del Q, Ub, W_np
    gc.collect()

    return DecomposedLinear(mx.array(U), mx.array(S), mx.array(Vt))


def vaccine_compile(model_dir, ffn_rank=256):
    """
    Load model via mlx_lm (correct), then replace FFN with decomposed.
    """
    print(f"[Vaccine V2] Loading model via mlx_lm...", flush=True)
    model, tokenizer = load(model_dir)
    print(f"[Vaccine V2] Model loaded. Decomposing FFN at rank {ffn_rank}...", flush=True)

    n_layers = len(model.model.layers)
    for li in range(n_layers):
        layer = model.model.layers[li]

        # Replace FFN projections with decomposed versions
        print(f"  [{li}] gate...", end="", flush=True)
        layer.mlp.gate_proj = decompose_linear(layer.mlp.gate_proj, ffn_rank)
        print(f" up...", end="", flush=True)
        layer.mlp.up_proj = decompose_linear(layer.mlp.up_proj, ffn_rank)
        print(f" down...", end="", flush=True)
        layer.mlp.down_proj = decompose_linear(layer.mlp.down_proj, ffn_rank)
        print(f" done", flush=True)

        gc.collect()

    print(f"[Vaccine V2] All FFN layers decomposed. Attention intact.", flush=True)
    return model, tokenizer


if __name__ == "__main__":
    import sys
    from mlx_lm import generate

    d = sys.argv[1] if len(sys.argv) > 1 else "models/qwen-3b-4bit"
    rank = int(sys.argv[2]) if len(sys.argv) > 2 else 256

    model, tokenizer = vaccine_compile(d, ffn_rank=rank)

    print(f"\n[Vaccine V2] Generating...\n", flush=True)
    response = generate(model, tokenizer,
                        prompt="What is quantum physics? One sentence.",
                        max_tokens=30, verbose=True)
    print(f"\nResponse: {response}")
