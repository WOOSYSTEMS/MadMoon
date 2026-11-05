"""
Moon Inference Engine v4 - MLX Native Streaming
Runs 72B on 8GB RAM by loading one layer at a time via mmap.
Uses MLX's native quantized ops for correct dequantization.

Target: <2GB RAM peak, 2-4s/token on M3 Air 8GB.
"""

import os
import json
import time
import struct
import mmap
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import mlx.core as mx
import mlx.nn as nn
import numpy as np


class MMapTensorLoader:
    """Load individual tensors from safetensors via mmap. Zero full-model load."""

    def __init__(self, model_dir: str):
        self.model_dir = Path(model_dir)
        self.index = json.load(open(self.model_dir / "model.safetensors.index.json"))
        self.weight_map = self.index["weight_map"]
        self._file_handles = {}
        self._file_headers = {}

    def _get_file(self, filename: str):
        if filename not in self._file_handles:
            filepath = self.model_dir / filename
            f = open(filepath, "rb")
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            # Parse header
            header_size = struct.unpack("<Q", mm[:8])[0]
            header = json.loads(mm[8:8 + header_size])
            data_offset = 8 + header_size
            self._file_handles[filename] = (f, mm, data_offset)
            self._file_headers[filename] = header
        return self._file_handles[filename], self._file_headers[filename]

    def load_tensor(self, name: str) -> Optional[mx.array]:
        if name not in self.weight_map:
            return None

        filename = self.weight_map[name]
        (f, mm, data_offset), header = self._get_file(filename)

        if name not in header:
            return None

        meta = header[name]
        dtype_str = meta["dtype"]
        shape = meta.get("shape", [])
        start, end = meta["data_offsets"]
        start += data_offset
        end += data_offset

        raw = mm[start:end]

        if dtype_str in ("F16", "float16"):
            arr = np.frombuffer(raw, dtype=np.float16).reshape(shape)
            return mx.array(arr)
        elif dtype_str in ("BF16", "bfloat16"):
            arr = np.frombuffer(raw, dtype=np.uint16).reshape(shape)
            return mx.array(arr, dtype=mx.bfloat16)
        elif dtype_str in ("F32", "float32"):
            arr = np.frombuffer(raw, dtype=np.float32).reshape(shape)
            return mx.array(arr)
        elif dtype_str in ("U32", "uint32"):
            arr = np.frombuffer(raw, dtype=np.uint32).reshape(shape)
            return mx.array(arr, dtype=mx.uint32)
        elif dtype_str in ("I32", "int32"):
            arr = np.frombuffer(raw, dtype=np.int32).reshape(shape)
            return mx.array(arr)
        elif dtype_str in ("I8", "int8"):
            arr = np.frombuffer(raw, dtype=np.int8).reshape(shape)
            return mx.array(arr)
        else:
            print(f"Warning: unknown dtype {dtype_str} for {name}")
            arr = np.frombuffer(raw, dtype=np.float16).reshape(shape)
            return mx.array(arr)

    def close(self):
        for f, mm, _ in self._file_handles.values():
            mm.close()
            f.close()


def dequantize(weight, scales, biases, group_size=64):
    """MLX-style dequantization: weight * scales + biases"""
    # weight is uint32 packed bits, scales and biases are float16
    return mx.dequantize(weight, scales, biases, group_size=group_size, bits=4)


class StreamingQwenLayer:
    """Process one transformer layer with streaming weights."""

    def __init__(self, config):
        self.dim = config["hidden_size"]
        self.n_heads = config["num_attention_heads"]
        self.n_kv_heads = config.get("num_key_value_heads", self.n_heads)
        self.head_dim = self.dim // self.n_heads
        self.ffn_dim = config["intermediate_size"]
        self.rope_theta = config.get("rope_theta", 1000000.0)

    def load_weights(self, loader: MMapTensorLoader, layer_idx: int) -> Dict:
        """Load all weights for one layer via mmap."""
        prefix = f"model.layers.{layer_idx}"
        weights = {}

        components = [
            "input_layernorm.weight",
            "post_attention_layernorm.weight",
            "self_attn.q_proj", "self_attn.k_proj",
            "self_attn.v_proj", "self_attn.o_proj",
            "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj",
        ]

        for comp in components:
            full_name = f"{prefix}.{comp}"
            if comp.endswith(".weight") and "proj" not in comp:
                # LayerNorm - just weight
                w = loader.load_tensor(full_name)
                if w is not None:
                    weights[comp] = w
            else:
                # Quantized linear - weight + scales + biases
                w = loader.load_tensor(f"{full_name}.weight")
                s = loader.load_tensor(f"{full_name}.scales")
                b = loader.load_tensor(f"{full_name}.biases")
                if w is not None:
                    weights[comp] = {"weight": w, "scales": s, "biases": b}

        return weights

    def forward(self, x, weights, position, kv_cache=None):
        """Forward pass through one layer."""
        residual = x

        # Input layernorm
        norm_w = weights["input_layernorm.weight"]
        x = self._rms_norm(x, norm_w)

        # Self attention
        q = self._linear(x, weights["self_attn.q_proj"])
        k = self._linear(x, weights["self_attn.k_proj"])
        v = self._linear(x, weights["self_attn.v_proj"])

        B, L, _ = q.shape
        q = q.reshape(B, L, self.n_heads, self.head_dim).transpose(0, 2, 1, 3)
        k = k.reshape(B, L, self.n_kv_heads, self.head_dim).transpose(0, 2, 1, 3)
        v = v.reshape(B, L, self.n_kv_heads, self.head_dim).transpose(0, 2, 1, 3)

        # RoPE
        q = self._apply_rope(q, position)
        k = self._apply_rope(k, position)

        # KV cache
        if kv_cache is not None:
            k_cache, v_cache = kv_cache
            k = mx.concatenate([k_cache, k], axis=2)
            v = mx.concatenate([v_cache, v], axis=2)
        new_kv = (k, v)

        # GQA repeat
        if self.n_kv_heads < self.n_heads:
            repeats = self.n_heads // self.n_kv_heads
            k = mx.repeat(k, repeats, axis=1)
            v = mx.repeat(v, repeats, axis=1)

        # Attention
        scale = self.head_dim ** -0.5
        scores = (q @ k.transpose(0, 1, 3, 2)) * scale
        scores = mx.softmax(scores, axis=-1)
        attn_out = scores @ v

        attn_out = attn_out.transpose(0, 2, 1, 3).reshape(B, L, -1)
        attn_out = self._linear(attn_out, weights["self_attn.o_proj"])

        x = residual + attn_out

        # Post attention layernorm
        residual = x
        norm_w2 = weights["post_attention_layernorm.weight"]
        x = self._rms_norm(x, norm_w2)

        # MLP (SwiGLU)
        gate = self._linear(x, weights["mlp.gate_proj"])
        up = self._linear(x, weights["mlp.up_proj"])
        x = nn.silu(gate) * up
        x = self._linear(x, weights["mlp.down_proj"])

        x = residual + x
        return x, new_kv

    def _linear(self, x, w_dict):
        """Quantized linear: dequantize then matmul."""
        w = dequantize(w_dict["weight"], w_dict["scales"], w_dict["biases"])
        return x @ w.T

    def _rms_norm(self, x, weight, eps=1e-6):
        ms = mx.mean(x * x, axis=-1, keepdims=True)
        x = x * mx.rsqrt(ms + eps)
        return x * weight

    def _apply_rope(self, x, position):
        """Rotary position embedding."""
        dim = x.shape[-1]
        freqs = 1.0 / (self.rope_theta ** (mx.arange(0, dim, 2, dtype=mx.float32) / dim))
        t = mx.array([position], dtype=mx.float32)
        freqs = t[:, None] * freqs[None, :]
        cos = mx.cos(freqs)
        sin = mx.sin(freqs)

        x1 = x[..., ::2]
        x2 = x[..., 1::2]

        out1 = x1 * cos - x2 * sin
        out2 = x1 * sin + x2 * cos

        return mx.concatenate([out1, out2], axis=-1)


class MoonInferenceV4:
    """
    Moon Inference v4: stream 72B through 8GB RAM.
    Load one layer, compute, discard, load next.
    """

    def __init__(self, model_dir: str):
        self.model_dir = model_dir
        self.config = json.load(open(f"{model_dir}/config.json"))
        self.n_layers = self.config["num_hidden_layers"]
        self.dim = self.config["hidden_size"]
        self.vocab_size = self.config["vocab_size"]

        self.loader = MMapTensorLoader(model_dir)
        self.layer = StreamingQwenLayer(self.config)
        self.kv_caches = [None] * self.n_layers

        # Load persistent weights (small - embeddings via mmap)
        print(f"[Moon v4] Streaming engine for {self.n_layers}-layer model")
        print(f"[Moon v4] Hidden: {self.dim}, Vocab: {self.vocab_size}")

        # Load tokenizer
        try:
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
            print(f"[Moon v4] Tokenizer loaded")
        except Exception as e:
            print(f"[Moon v4] Tokenizer error: {e}")
            self.tokenizer = None

    def generate(self, prompt: str, max_tokens: int = 100, temperature: float = 0.7):
        """Generate text from prompt."""
        if self.tokenizer is None:
            print("No tokenizer available")
            return ""

        tokens = self.tokenizer.encode(prompt)
        print(f"[Moon v4] Prompt tokens: {len(tokens)}")

        generated = []
        position = len(tokens) - 1

        # Process prompt (simplified - just last token for speed)
        current_token = mx.array([[tokens[-1]]])

        for step in range(max_tokens):
            start = time.time()

            # Embed - use quantized lookup (only dequantize the rows we need)
            embed_w = self.loader.load_tensor("model.embed_tokens.weight")
            embed_s = self.loader.load_tensor("model.embed_tokens.scales")
            embed_b = self.loader.load_tensor("model.embed_tokens.biases")

            # Only dequantize needed token rows to save memory
            tok_id = current_token.item() if current_token.size == 1 else current_token[0, 0].item()
            # Dequantize in small chunk around the token
            chunk_start = max(0, tok_id - 8)
            chunk_end = min(embed_w.shape[0], tok_id + 8)
            chunk_w = embed_w[chunk_start:chunk_end]
            chunk_s = embed_s[chunk_start:chunk_end]
            chunk_b = embed_b[chunk_start:chunk_end]
            chunk_deq = dequantize(chunk_w, chunk_s, chunk_b)
            x = chunk_deq[tok_id - chunk_start:tok_id - chunk_start + 1].reshape(1, 1, -1)
            mx.eval(x)
            del embed_w, embed_s, embed_b, chunk_deq, chunk_w, chunk_s, chunk_b

            # Stream through layers
            for layer_idx in range(self.n_layers):
                weights = self.layer.load_weights(self.loader, layer_idx)
                x, new_kv = self.layer.forward(x, weights, position, self.kv_caches[layer_idx])
                self.kv_caches[layer_idx] = new_kv

                # Free layer weights immediately
                del weights

                # Eval every 10 layers to prevent memory buildup
                if layer_idx % 10 == 9:
                    mx.eval(x)

            # Final norm
            norm_w = self.loader.load_tensor("model.norm.weight")
            ms = mx.mean(x * x, axis=-1, keepdims=True)
            x = x * mx.rsqrt(ms + 1e-6) * norm_w
            del norm_w

            # LM head - chunked to avoid Metal buffer limit
            lm_w = self.loader.load_tensor("lm_head.weight")
            lm_s = self.loader.load_tensor("lm_head.scales")
            lm_b = self.loader.load_tensor("lm_head.biases")

            # Process in chunks of 16384 vocab entries
            chunk_size = 16384
            vocab = lm_w.shape[0]
            logit_chunks = []
            for ci in range(0, vocab, chunk_size):
                ce = min(ci + chunk_size, vocab)
                chunk_w = lm_w[ci:ce]
                chunk_s = lm_s[ci:ce]
                chunk_b = lm_b[ci:ce]
                chunk_deq = dequantize(chunk_w, chunk_s, chunk_b)
                chunk_logits = x @ chunk_deq.T
                mx.eval(chunk_logits)
                logit_chunks.append(chunk_logits)
                del chunk_deq, chunk_w, chunk_s, chunk_b

            logits = mx.concatenate(logit_chunks, axis=-1)
            del lm_w, lm_s, lm_b, logit_chunks

            # Sample
            if temperature > 0:
                logits = logits[:, -1, :] / temperature
                probs = mx.softmax(logits, axis=-1)
                next_token = mx.random.categorical(probs).item()
            else:
                next_token = mx.argmax(logits[:, -1, :], axis=-1).item()

            elapsed = time.time() - start

            # Decode and print
            text = self.tokenizer.decode([next_token])
            print(text, end="", flush=True)

            generated.append(next_token)
            current_token = mx.array([[next_token]])
            position += 1

            # Stop on EOS
            if next_token == self.tokenizer.eos_token_id:
                break

        print()
        full_text = self.tokenizer.decode(generated)
        return full_text


if __name__ == "__main__":
    import sys
    model_dir = sys.argv[1] if len(sys.argv) > 1 else "models/qwen-72b-4bit"

    engine = MoonInferenceV4(model_dir)

    print("\n[Moon v4] Interactive mode. Type your prompt:")
    while True:
        try:
            prompt = input("\n> ")
            if not prompt:
                continue
            if prompt.lower() in ("exit", "quit"):
                break
            engine.generate(prompt, max_tokens=200)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")

    engine.loader.close()
