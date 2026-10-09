"""
OneBrain — TGAM (ThinkGear ASIC Module) Data Parser
Parses NeuroSky ThinkGear serial protocol for raw EEG and eSense values.
"""

import struct
import time
import threading
from typing import Callable, Optional, Dict

try:
    import serial
except ImportError:
    serial = None

try:
    import asyncio
    from bleak import BleakClient, BleakScanner
except ImportError:
    BleakClient = None


# ThinkGear packet codes
CODE_RAW_EEG = 0x80
CODE_SIGNAL_QUALITY = 0x02
CODE_ATTENTION = 0x04
CODE_MEDITATION = 0x05
CODE_EEG_POWER = 0x83


class TGAMParser:
    """Parses ThinkGear ASIC Module data stream."""

    def __init__(self):
        self.on_raw_eeg: Optional[Callable[[int], None]] = None
        self.on_attention: Optional[Callable[[int], None]] = None
        self.on_meditation: Optional[Callable[[int], None]] = None
        self.on_bands: Optional[Callable[[Dict[str, int]], None]] = None
        self.on_signal_quality: Optional[Callable[[int], None]] = None
        self.on_blink: Optional[Callable[[int], None]] = None

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._serial: Optional[object] = None

        # Latest values
        self.signal_quality = 200  # 0=good, 200=no contact
        self.attention = 0
        self.meditation = 0
        self.raw_eeg = 0
        self.bands: Dict[str, int] = {
            "delta": 0, "theta": 0,
            "low_alpha": 0, "high_alpha": 0,
            "low_beta": 0, "high_beta": 0,
            "low_gamma": 0, "mid_gamma": 0,
        }

    def connect_serial(self, port: str, baud: int = 57600):
        """Connect via USB serial."""
        if serial is None:
            raise ImportError("pyserial not installed. Run: pip install pyserial")
        self._serial = serial.Serial(port, baud, timeout=1)
        print(f"Connected to TGAM on {port} at {baud} baud")

    def start(self):
        """Start reading in background thread."""
        if self._serial is None:
            raise RuntimeError("Not connected. Call connect_serial() first.")
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        print("TGAM parser started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._serial:
            self._serial.close()
        print("TGAM parser stopped")

    def _read_loop(self):
        """Main read loop — finds sync bytes and parses packets."""
        while self._running:
            try:
                # Find sync bytes: 0xAA 0xAA
                byte = self._read_byte()
                if byte != 0xAA:
                    continue
                byte = self._read_byte()
                if byte != 0xAA:
                    continue

                # Read payload length (1 byte, must be < 170)
                plen = self._read_byte()
                if plen >= 170:
                    continue

                # Read payload
                payload = []
                for _ in range(plen):
                    payload.append(self._read_byte())

                # Verify checksum
                checksum = self._read_byte()
                computed = (~sum(payload)) & 0xFF
                if checksum != computed:
                    continue

                # Parse payload
                self._parse_payload(payload)

            except Exception:
                if self._running:
                    time.sleep(0.01)

    def _read_byte(self) -> int:
        data = self._serial.read(1)
        if not data:
            raise TimeoutError("No data")
        return data[0]

    def _parse_payload(self, payload: list):
        i = 0
        while i < len(payload):
            code = payload[i]
            i += 1

            if code == CODE_SIGNAL_QUALITY:
                self.signal_quality = payload[i]
                i += 1
                if self.on_signal_quality:
                    self.on_signal_quality(self.signal_quality)

            elif code == CODE_ATTENTION:
                self.attention = payload[i]
                i += 1
                if self.on_attention:
                    self.on_attention(self.attention)

            elif code == CODE_MEDITATION:
                self.meditation = payload[i]
                i += 1
                if self.on_meditation:
                    self.on_meditation(self.meditation)

            elif code == CODE_RAW_EEG:
                # 2-byte length, then 2-byte signed value
                length = payload[i]
                i += 1
                if length == 2 and i + 1 < len(payload):
                    raw = struct.unpack('>h', bytes(payload[i:i+2]))[0]
                    self.raw_eeg = raw
                    i += 2
                    if self.on_raw_eeg:
                        self.on_raw_eeg(raw)

            elif code == CODE_EEG_POWER:
                # 3-byte length, then 8 x 3-byte unsigned values
                length = payload[i]
                i += 1
                if length == 24 and i + 23 < len(payload):
                    band_names = ["delta", "theta", "low_alpha", "high_alpha",
                                  "low_beta", "high_beta", "low_gamma", "mid_gamma"]
                    for name in band_names:
                        val = (payload[i] << 16) | (payload[i+1] << 8) | payload[i+2]
                        self.bands[name] = val
                        i += 3
                    if self.on_bands:
                        self.on_bands(self.bands.copy())
            else:
                # Unknown code — skip
                if code >= 0x80:
                    if i < len(payload):
                        skip_len = payload[i]
                        i += 1 + skip_len
                else:
                    i += 1


class TGAMSimulator:
    """Simulates TGAM data for testing without hardware."""

    def __init__(self):
        self.on_raw_eeg: Optional[Callable[[int], None]] = None
        self.on_attention: Optional[Callable[[int], None]] = None
        self.on_meditation: Optional[Callable[[int], None]] = None
        self.on_bands: Optional[Callable[[Dict[str, int]], None]] = None
        self.on_signal_quality: Optional[Callable[[int], None]] = None

        self._running = False
        self._thread: Optional[threading.Thread] = None

        self.signal_quality = 0
        self.attention = 50
        self.meditation = 50
        self.raw_eeg = 0
        self.bands = {k: 1000 for k in
                      ["delta", "theta", "low_alpha", "high_alpha",
                       "low_beta", "high_beta", "low_gamma", "mid_gamma"]}

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._sim_loop, daemon=True)
        self._thread.start()
        print("TGAM simulator started (no hardware needed)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _sim_loop(self):
        import random
        while self._running:
            # Simulate raw EEG at ~512 Hz
            self.raw_eeg = random.randint(-2048, 2047)
            if self.on_raw_eeg:
                self.on_raw_eeg(self.raw_eeg)

            # Simulate eSense at ~1 Hz
            if random.random() < 0.002:  # ~1/512
                self.attention = max(0, min(100, self.attention + random.randint(-5, 5)))
                self.meditation = max(0, min(100, self.meditation + random.randint(-5, 5)))
                if self.on_attention:
                    self.on_attention(self.attention)
                if self.on_meditation:
                    self.on_meditation(self.meditation)
                if self.on_bands:
                    for k in self.bands:
                        self.bands[k] = max(0, self.bands[k] + random.randint(-200, 200))
                    self.on_bands(self.bands.copy())

            time.sleep(1/512)


if __name__ == "__main__":
    print("OneBrain TGAM Parser — Simulator Test")
    sim = TGAMSimulator()
    sim.on_attention = lambda v: print(f"  Attention: {v}")
    sim.on_meditation = lambda v: print(f"  Meditation: {v}")
    sim.start()
    try:
        time.sleep(5)
    finally:
        sim.stop()
    print("Done.")
