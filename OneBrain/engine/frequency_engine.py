"""
OneBrain — Frequency Generator Engine
Generates binaural beats, isochronic tones, and sub-threshold frequencies.
"""

import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from typing import Optional


SAMPLE_RATE = 44100

# Preset frequency targets (Hz)
PRESETS = {
    "alpha": {"type": "binaural", "base": 200, "target": 10.0, "description": "Relaxed focus"},
    "theta": {"type": "binaural", "base": 200, "target": 6.0, "description": "Meditation / drowsiness"},
    "delta": {"type": "binaural", "base": 200, "target": 2.0, "description": "Deep sleep"},
    "gamma": {"type": "binaural", "base": 200, "target": 40.0, "description": "Higher cognition"},
    "sleep": {"type": "layered", "ambient": 432.0, "binaural_base": 200, "binaural_target": 2.0, "description": "432 Hz + delta binaural"},
    "focus": {"type": "isochronic", "carrier": 300, "target": 14.0, "description": "Beta focus"},
    "calm": {"type": "binaural", "base": 150, "target": 8.0, "description": "Alpha calm"},
}


def generate_sine(frequency: float, duration: float, amplitude: float = 1.0) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    return amplitude * np.sin(2 * np.pi * frequency * t)


def generate_binaural(base_freq: float, target_freq: float, duration: float, amplitude: float = 0.8) -> np.ndarray:
    """Left ear = base_freq, Right ear = base_freq + target_freq. Brain perceives target_freq."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    left = amplitude * np.sin(2 * np.pi * base_freq * t)
    right = amplitude * np.sin(2 * np.pi * (base_freq + target_freq) * t)
    return np.column_stack([left, right])


def generate_isochronic(carrier_freq: float, pulse_freq: float, duration: float, amplitude: float = 0.8) -> np.ndarray:
    """Pulsed tone — works through speakers, no headphones needed."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    carrier = np.sin(2 * np.pi * carrier_freq * t)
    # Square wave envelope at pulse frequency
    envelope = 0.5 * (1 + np.sign(np.sin(2 * np.pi * pulse_freq * t)))
    signal = amplitude * carrier * envelope
    return np.column_stack([signal, signal])


def generate_subliminal(main_audio: np.ndarray, hidden_freq: float, volume_db: float = -20.0) -> np.ndarray:
    """Embed a frequency into existing audio at sub-threshold volume."""
    duration = len(main_audio) / SAMPLE_RATE
    hidden_amplitude = 10 ** (volume_db / 20.0)
    hidden = generate_sine(hidden_freq, duration, hidden_amplitude)

    if main_audio.ndim == 1:
        main_audio = np.column_stack([main_audio, main_audio])

    hidden_stereo = np.column_stack([hidden, hidden])
    return np.clip(main_audio + hidden_stereo, -1.0, 1.0)


def generate_layered_sleep(duration: float) -> np.ndarray:
    """432 Hz ambient + 2 Hz delta binaural — the OneBrain sleep formula."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    # 432 Hz ambient (both channels, soft)
    ambient = 0.3 * np.sin(2 * np.pi * 432.0 * t)
    # Delta binaural: 200 Hz left, 202 Hz right
    left_binaural = 0.5 * np.sin(2 * np.pi * 200.0 * t)
    right_binaural = 0.5 * np.sin(2 * np.pi * 202.0 * t)

    left = np.clip(ambient + left_binaural, -1.0, 1.0)
    right = np.clip(ambient + right_binaural, -1.0, 1.0)
    return np.column_stack([left, right])


def generate_from_preset(preset_name: str, duration: float = 300.0) -> np.ndarray:
    """Generate audio from a named preset."""
    if preset_name not in PRESETS:
        raise ValueError(f"Unknown preset: {preset_name}. Available: {list(PRESETS.keys())}")

    p = PRESETS[preset_name]

    if p["type"] == "binaural":
        return generate_binaural(p["base"], p["target"], duration)
    elif p["type"] == "isochronic":
        return generate_isochronic(p["carrier"], p["target"], duration)
    elif p["type"] == "layered":
        return generate_layered_sleep(duration)
    else:
        raise ValueError(f"Unknown preset type: {p['type']}")


def play(audio: np.ndarray, blocking: bool = True):
    """Play audio through default output device."""
    sd.play(audio, SAMPLE_RATE)
    if blocking:
        sd.wait()


def stop():
    sd.stop()


def save_wav(audio: np.ndarray, filepath: str):
    """Save audio to WAV file."""
    audio_int16 = np.int16(audio * 32767)
    wavfile.write(filepath, SAMPLE_RATE, audio_int16)
    print(f"Saved: {filepath}")


def play_preset(preset_name: str, duration: float = 300.0, blocking: bool = True):
    """Generate and play a preset."""
    print(f"Playing preset: {preset_name} — {PRESETS[preset_name]['description']} ({duration}s)")
    audio = generate_from_preset(preset_name, duration)
    play(audio, blocking)


if __name__ == "__main__":
    print("OneBrain Frequency Engine")
    print(f"Available presets: {list(PRESETS.keys())}")
    print("Generating 10s alpha binaural test...")
    audio = generate_binaural(200, 10.0, 10.0)
    save_wav(audio, "test_alpha.wav")
    print("Done. Play test_alpha.wav with headphones to hear the binaural beat.")
