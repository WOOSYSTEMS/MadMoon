#!/usr/bin/env python3
"""
OneBrain — Brain Frequency Platform
CLI for calibration, focus, sleep, calm, recording, and analysis.
"""

import sys
import time
import signal
from engine.frequency_engine import (
    generate_from_preset, generate_binaural, play, stop, save_wav, PRESETS, SAMPLE_RATE
)
from engine.tgam_parser import TGAMParser, TGAMSimulator
from engine.session_recorder import SessionRecorder


def get_device(port: str = None):
    """Connect to TGAM device, or fall back to simulator."""
    if port:
        try:
            parser = TGAMParser()
            parser.connect_serial(port)
            parser.start()
            return parser, "tgam"
        except Exception as e:
            print(f"Could not connect to TGAM on {port}: {e}")

    print("No TGAM device — using simulator")
    sim = TGAMSimulator()
    sim.start()
    return sim, "simulator"


def cmd_calibrate(port: str = None):
    """5-minute calibration: plays different frequencies, records brain response."""
    device, dtype = get_device(port)
    recorder = SessionRecorder()
    recorder.start_session(device_type=dtype, notes="calibration")

    freqs = [
        ("delta", 2.0, "binaural"),
        ("theta", 6.0, "binaural"),
        ("alpha", 10.0, "binaural"),
        ("beta", 14.0, "binaural"),
        ("gamma", 40.0, "binaural"),
    ]

    print("\n=== OneBrain Calibration ===")
    print("Sit comfortably. Close your eyes. Each frequency plays for 60 seconds.\n")

    def record_callback():
        recorder.record_sample(
            frequency_hz=current_freq,
            frequency_type=current_type,
            raw_eeg=device.raw_eeg,
            attention=device.attention,
            meditation=device.meditation,
            signal_quality=device.signal_quality,
            bands=device.bands,
        )

    for name, freq, ftype in freqs:
        current_freq = freq
        current_type = ftype
        print(f"Playing {name} ({freq} Hz) for 60 seconds...")

        audio = generate_binaural(200, freq, 60.0)
        play(audio, blocking=False)

        start = time.time()
        while time.time() - start < 60:
            record_callback()
            time.sleep(1/10)  # 10 samples/sec for eSense
        stop()
        recorder.flush()
        print(f"  → Avg attention: {device.attention}, meditation: {device.meditation}")
        time.sleep(2)

    recorder.end_session()
    device.stop()

    print("\n=== Calibration Complete ===")
    print("Analyzing results...")
    for metric in ("attention", "meditation"):
        results = recorder.analyze_best_frequency(metric)
        if results:
            best = results[0]
            print(f"  Best for {metric}: {best['frequency_hz']} Hz (avg: {best[f'avg_{metric}']})")
    print("\nRun 'python main.py focus' or 'python main.py sleep' to use personalized frequencies.")


def cmd_preset(preset_name: str, duration: float = 300.0, port: str = None):
    """Play a preset with optional brain recording."""
    device, dtype = get_device(port)
    recorder = SessionRecorder()
    recorder.start_session(device_type=dtype, notes=f"preset:{preset_name}")

    preset = PRESETS[preset_name]
    freq = preset.get("target", preset.get("binaural_target", 0))
    print(f"\nPlaying: {preset_name} — {preset['description']}")
    print(f"Duration: {int(duration)}s. Press Ctrl+C to stop.\n")

    audio = generate_from_preset(preset_name, duration)
    play(audio, blocking=False)

    def cleanup(*args):
        stop()
        recorder.end_session()
        device.stop()
        print("\nSession ended.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)

    start = time.time()
    while time.time() - start < duration:
        recorder.record_sample(
            frequency_hz=freq,
            frequency_type=preset["type"],
            raw_eeg=device.raw_eeg,
            attention=device.attention,
            meditation=device.meditation,
            signal_quality=device.signal_quality,
            bands=device.bands,
        )
        time.sleep(1/10)

    cleanup()


def cmd_record(duration: float = 60.0, port: str = None):
    """Record raw EEG without playing anything."""
    device, dtype = get_device(port)
    recorder = SessionRecorder()
    recorder.start_session(device_type=dtype, notes="raw_recording")

    print(f"\nRecording brain activity for {int(duration)}s (no audio). Press Ctrl+C to stop.\n")

    def cleanup(*args):
        recorder.end_session()
        device.stop()
        print("Recording saved.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)

    start = time.time()
    while time.time() - start < duration:
        recorder.record_sample(
            raw_eeg=device.raw_eeg,
            attention=device.attention,
            meditation=device.meditation,
            signal_quality=device.signal_quality,
            bands=device.bands,
        )
        time.sleep(1/10)

    cleanup()


def cmd_analyze():
    """Show best frequencies from past sessions."""
    recorder = SessionRecorder()

    print("\n=== OneBrain Analysis ===\n")

    sessions = recorder.get_sessions()
    print(f"Total sessions: {len(sessions)}\n")

    for metric in ("attention", "meditation"):
        results = recorder.analyze_best_frequency(metric)
        print(f"Best frequencies for {metric}:")
        if not results:
            print("  No data yet. Run 'python main.py calibrate' first.")
        for r in results[:5]:
            print(f"  {r['frequency_hz']} Hz ({r['frequency_type']}) → avg {r[f'avg_{metric}']} ({r['samples']} samples)")
        print()


def main():
    if len(sys.argv) < 2:
        print("""
OneBrain — Brain Frequency Platform

Usage:
  python main.py calibrate [--port /dev/ttyUSB0]    Run 5-min calibration
  python main.py focus [--duration 300]              Play focus frequency
  python main.py sleep [--duration 300]              Play sleep frequency
  python main.py calm [--duration 300]               Play calm frequency
  python main.py alpha [--duration 300]              Play alpha preset
  python main.py theta [--duration 300]              Play theta preset
  python main.py gamma [--duration 300]              Play gamma preset
  python main.py record [--duration 60]              Record EEG only
  python main.py analyze                             Show best frequencies
        """)
        return

    cmd = sys.argv[1]
    port = None
    duration = 300.0

    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = sys.argv[i + 1]
        if arg == "--duration" and i + 1 < len(sys.argv):
            duration = float(sys.argv[i + 1])

    if cmd == "calibrate":
        cmd_calibrate(port)
    elif cmd in PRESETS:
        cmd_preset(cmd, duration, port)
    elif cmd == "record":
        cmd_record(duration, port)
    elif cmd == "analyze":
        cmd_analyze()
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
