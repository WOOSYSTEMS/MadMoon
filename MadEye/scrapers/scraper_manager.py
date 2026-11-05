"""
MadEye Sniper Mode — Scraper Manager (Orchestrator)
Runs all 12+ scrapers on tiered schedule. Generates SNIPER BUY signals.

Tier 1 (every 5 min):  houthi_telegram, iran_media, satellite_thermal, ship_tracker
Tier 2 (every 15 min): saudi_media, opec_monitor, oil_twitter, libya_nigeria, hurricane_monitor,
                        crack_spread, cross_commodity, spreads, demand_advanced
Tier 3 (every 30 min): russian_energy, china_demand, eia_prerelease, floating_storage, etf_flows

SNIPER LOGIC:
  - 3+ scrapers score >= 8 simultaneously = SNIPER BUY
  - 5+ scrapers score >= 7 = SNIPER BUY
  - New factors (crack_spread, spreads, demand_advanced) included in composite
"""

import os
import json
import time
import threading
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MADEYE] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, "manager.log")),
    ]
)
log = logging.getLogger("madeye")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SIGNAL_FILE = os.path.join(DATA_DIR, "sniper_signal.json")
STATE_FILE = os.path.join(DATA_DIR, "manager_state.json")
os.makedirs(DATA_DIR, exist_ok=True)

# Import all scrapers
from . import houthi_telegram
from . import iran_media
from . import saudi_media
from . import russian_energy
from . import opec_monitor
from . import oil_twitter
from . import ship_tracker
from . import libya_nigeria
from . import china_demand
from . import hurricane_monitor
from . import eia_prerelease
from . import satellite_thermal

# New scrapers (wrapping collectors)
from . import crack_spread_scraper
from . import cross_commodity_scraper
from . import spreads_scraper
from . import demand_advanced_scraper
from . import floating_storage_scraper
from . import etf_flows_scraper

# Tier definitions
TIER_1 = {
    "houthi_telegram": houthi_telegram,
    "iran_media": iran_media,
    "satellite_thermal": satellite_thermal,
    "ship_tracker": ship_tracker,
}
TIER_1_INTERVAL = 300  # 5 minutes

TIER_2 = {
    "saudi_media": saudi_media,
    "opec_monitor": opec_monitor,
    "oil_twitter": oil_twitter,
    "libya_nigeria": libya_nigeria,
    "hurricane_monitor": hurricane_monitor,
    # New Tier 2 scrapers (counter-check factors)
    "crack_spread": crack_spread_scraper,
    "cross_commodity": cross_commodity_scraper,
    "spreads": spreads_scraper,
    "demand_advanced": demand_advanced_scraper,
}
TIER_2_INTERVAL = 900  # 15 minutes

TIER_3 = {
    "russian_energy": russian_energy,
    "china_demand": china_demand,
    "eia_prerelease": eia_prerelease,
    # New Tier 3 scrapers (counter-check factors)
    "floating_storage": floating_storage_scraper,
    "etf_flows": etf_flows_scraper,
}
TIER_3_INTERVAL = 1800  # 30 minutes

ALL_SCRAPERS = {**TIER_1, **TIER_2, **TIER_3}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SniperManager:
    def __init__(self):
        self.running = False
        self.results: Dict[str, Dict] = {}  # latest result per scraper
        self.last_run: Dict[str, float] = {}  # last run timestamp per scraper
        self.signal_history: List[Dict] = []  # rolling history of signals
        self.lock = threading.Lock()
        self._load_state()

    def _load_state(self):
        """Load persisted state."""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                self.results = state.get("results", {})
                self.last_run = {k: v for k, v in state.get("last_run", {}).items()}
                log.info(f"Loaded state: {len(self.results)} cached results")
            except:
                pass

    def _save_state(self):
        """Persist state to disk."""
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({
                    "results": self.results,
                    "last_run": self.last_run,
                    "saved_at": now_iso(),
                }, f, indent=2)
        except:
            pass

    def run_scraper(self, name: str, module) -> Dict:
        """Run a single scraper and store result."""
        try:
            result = module.run()
            with self.lock:
                self.results[name] = result
                self.last_run[name] = time.time()
            score = result.get("score", 0)
            signals = result.get("signals", [])
            level = "CRITICAL" if score >= 8 else "HIGH" if score >= 6 else "INFO"
            log.info(f"[{name}] score={score} confidence={result.get('confidence', 0):.2f} signals={len(signals)} [{level}]")
            if score >= 8:
                log.warning(f"[{name}] HIGH SCORE {score}: {signals[:3]}")
            return result
        except Exception as e:
            log.error(f"[{name}] FAILED: {e}")
            return {"score": 0, "confidence": 0, "signals": [f"ERROR: {e}"], "timestamp": now_iso()}

    def run_tier(self, tier: Dict, tier_name: str):
        """Run all scrapers in a tier."""
        log.info(f"--- Running {tier_name} ({len(tier)} scrapers) ---")
        threads = []
        for name, module in tier.items():
            t = threading.Thread(target=self.run_scraper, args=(name, module), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=30)  # 30s max per scraper

    def evaluate_sniper_signal(self) -> Dict:
        """
        Core sniper logic.
        Returns signal dict written to sniper_signal.json.
        """
        with self.lock:
            results = dict(self.results)

        scores = {}
        for name, r in results.items():
            scores[name] = r.get("score", 0)

        # Count high scores
        count_8_plus = sum(1 for s in scores.values() if s >= 8)
        count_7_plus = sum(1 for s in scores.values() if s >= 7)
        count_6_plus = sum(1 for s in scores.values() if s >= 6)

        # Identify which scrapers are firing
        firing_scrapers_8 = [n for n, s in scores.items() if s >= 8]
        firing_scrapers_7 = [n for n, s in scores.items() if s >= 7]

        # SNIPER LOGIC
        sniper_buy = False
        reason = "NO_SIGNAL"

        if count_8_plus >= 3:
            sniper_buy = True
            reason = f"RULE_1: {count_8_plus} scrapers >= 8 ({', '.join(firing_scrapers_8)})"
        elif count_7_plus >= 5:
            sniper_buy = True
            reason = f"RULE_2: {count_7_plus} scrapers >= 7 ({', '.join(firing_scrapers_7)})"

        # Composite score: weighted average
        weights = {
            "houthi_telegram": 2.0,  # direct attack intel
            "iran_media": 1.5,
            "satellite_thermal": 1.5,
            "ship_tracker": 1.5,
            "saudi_media": 1.2,
            "opec_monitor": 1.0,
            "oil_twitter": 0.8,
            "libya_nigeria": 1.0,
            "hurricane_monitor": 1.0,
            "russian_energy": 0.8,
            "china_demand": 0.7,
            "eia_prerelease": 0.8,
            # New counter-check factors
            "crack_spread": 1.2,       # refining margins directly affect crude demand
            "cross_commodity": 0.8,    # confirmation signal
            "spreads": 1.2,            # market structure
            "demand_advanced": 1.2,    # gasoline demand + refinery util
            "floating_storage": 0.6,   # background signal
            "etf_flows": 0.6,          # institutional flow tracking
        }
        weighted_sum = sum(scores.get(n, 0) * weights.get(n, 1.0) for n in ALL_SCRAPERS)
        total_weight = sum(weights.get(n, 1.0) for n in ALL_SCRAPERS if n in scores)
        composite = weighted_sum / total_weight if total_weight > 0 else 0

        # Average confidence
        confidences = [results[n].get("confidence", 0) for n in results]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        # Collect all signals from firing scrapers
        all_signals = []
        for name in sorted(scores, key=lambda n: scores[n], reverse=True):
            if scores[name] >= 5:
                sigs = results[name].get("signals", [])[:5]
                for s in sigs:
                    all_signals.append(f"[{name}:{scores[name]}] {s}")

        signal = {
            "sniper_buy": sniper_buy,
            "reason": reason,
            "composite_score": round(composite, 2),
            "avg_confidence": round(avg_confidence, 2),
            "individual_scores": scores,
            "count_8_plus": count_8_plus,
            "count_7_plus": count_7_plus,
            "count_6_plus": count_6_plus,
            "firing_scrapers": firing_scrapers_8 if count_8_plus >= 3 else firing_scrapers_7,
            "top_signals": all_signals[:30],
            "timestamp": now_iso(),
            "scrapers_reporting": len(scores),
        }

        # Write signal file
        try:
            with open(SIGNAL_FILE, "w") as f:
                json.dump(signal, f, indent=2)
        except Exception as e:
            log.error(f"Failed to write signal file: {e}")

        # Log
        if sniper_buy:
            log.warning(f"****** SNIPER BUY SIGNAL ****** {reason}")
            log.warning(f"Composite: {composite:.2f} | Confidence: {avg_confidence:.2f}")
        else:
            log.info(f"Signal: composite={composite:.2f} | 8+:{count_8_plus} 7+:{count_7_plus} 6+:{count_6_plus}")

        # Add to history
        self.signal_history.append(signal)
        self.signal_history = self.signal_history[-1000:]  # keep last 1000

        return signal

    def run_once(self) -> Dict:
        """Run all scrapers once and evaluate. For testing."""
        log.info("=== SINGLE RUN: All scrapers ===")
        self.run_tier(TIER_1, "Tier 1")
        self.run_tier(TIER_2, "Tier 2")
        self.run_tier(TIER_3, "Tier 3")
        signal = self.evaluate_sniper_signal()
        self._save_state()
        return signal

    def start(self):
        """Start continuous monitoring with tiered scheduling."""
        if self.running:
            log.warning("Manager already running")
            return
        self.running = True
        log.info("=" * 60)
        log.info("MADEYE SNIPER MODE — STARTING")
        log.info(f"Tier 1 ({len(TIER_1)} scrapers): every {TIER_1_INTERVAL}s")
        log.info(f"Tier 2 ({len(TIER_2)} scrapers): every {TIER_2_INTERVAL}s")
        log.info(f"Tier 3 ({len(TIER_3)} scrapers): every {TIER_3_INTERVAL}s")
        log.info("=" * 60)

        # Initial run: all tiers
        self.run_tier(TIER_1, "Tier 1")
        self.run_tier(TIER_2, "Tier 2")
        self.run_tier(TIER_3, "Tier 3")
        self.evaluate_sniper_signal()
        self._save_state()

        # Start tier threads
        t1 = threading.Thread(target=self._tier_loop, args=(TIER_1, "Tier 1", TIER_1_INTERVAL), daemon=True)
        t2 = threading.Thread(target=self._tier_loop, args=(TIER_2, "Tier 2", TIER_2_INTERVAL), daemon=True)
        t3 = threading.Thread(target=self._tier_loop, args=(TIER_3, "Tier 3", TIER_3_INTERVAL), daemon=True)

        t1.start()
        t2.start()
        t3.start()

        log.info("All tier threads started. Manager running.")

        # Main loop: evaluate signal every 60 seconds
        try:
            while self.running:
                time.sleep(60)
                self.evaluate_sniper_signal()
                self._save_state()
        except KeyboardInterrupt:
            log.info("Keyboard interrupt — stopping")
            self.running = False

    def _tier_loop(self, tier: Dict, tier_name: str, interval: int):
        """Loop for a single tier."""
        while self.running:
            time.sleep(interval)
            if not self.running:
                break
            self.run_tier(tier, tier_name)

    def stop(self):
        """Stop the manager."""
        self.running = False
        self._save_state()
        log.info("Manager stopped.")

    def get_status(self) -> Dict:
        """Return current status for dashboard."""
        with self.lock:
            scores = {n: r.get("score", 0) for n, r in self.results.items()}

        signal_path = SIGNAL_FILE
        current_signal = None
        if os.path.exists(signal_path):
            try:
                with open(signal_path, "r") as f:
                    current_signal = json.load(f)
            except:
                pass

        return {
            "running": self.running,
            "scrapers_active": len(self.results),
            "scores": scores,
            "current_signal": current_signal,
            "timestamp": now_iso(),
        }


# Module-level singleton
manager = SniperManager()


def main():
    """CLI entry point."""
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        signal = manager.run_once()
        print(json.dumps(signal, indent=2))
    else:
        manager.start()


if __name__ == "__main__":
    main()
