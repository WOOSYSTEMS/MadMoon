"""
MadEye Sniper Mode — Scraper 1: Houthi Telegram Monitor
Scrapes public Telegram channels for pre-attack and attack claim signals.
Adapted from MadMoonSecurity Sentinel's proven 78% accuracy classifier.
"""

import re
from typing import Dict, List
from .base_scraper import (
    fetch, make_result, safe_run, HEADERS, now_iso
)

CHANNELS = ["ansarollah1", "army21ye", "alaborar_ye", "Aborar_ye"]

# Pre-attack keywords (proven 78% accuracy from Sentinel)
PRE_ATTACK_KEYWORDS = {
    'ترقبوا': ('STAY TUNED', 3),
    'بيان مهم': ('IMPORTANT STATEMENT', 3),
    'خلال الساعات': ('IN THE COMING HOURS', 4),
    'غير آمن': ('UNSAFE', 3),
    'إخلاء': ('EVACUATION', 3),
    'جهوزية': ('READINESS', 2),
    'نفير': ('MOBILIZATION', 3),
    'بعد قليل': ('SHORTLY', 2),
    'سيكون في تمام': ('WILL BE AT EXACTLY', 4),
    'تحذيرها لجميع شركات الطيران': ('WARNING ALL AIRLINES', 4),
    'بيان مرتقب': ('UPCOMING STATEMENT', 3),
}

# Attack claim keywords — indicates strike HAS happened
ATTACK_CLAIM_KEYWORDS = {
    'استهداف': ('STRUCK/TARGETED', 3),
    'إصابة دقيقة': ('PRECISE HIT', 4),
    'تدمير': ('DESTRUCTION', 3),
    'إصابة مباشرة': ('DIRECT HIT', 4),
    'اشتعال': ('FIRE/BLAZE', 3),
    'حريق': ('FIRE', 2),
    'قصف': ('BOMBARDMENT', 3),
    'ضربة': ('STRIKE', 2),
    'نفذت': ('EXECUTED', 2),
    'القوات المسلحة تستهدف': ('ARMED FORCES TARGET', 4),
    'عملية عسكرية': ('MILITARY OPERATION', 3),
    'تعطل حركة الملاحة': ('NAVIGATION DISRUPTED', 4),
}

# Escalation keywords
ESCALATION_KEYWORDS = {
    'التصعيد بالتصعيد': ('ESCALATION FOR ESCALATION', 3),
    'الرد': ('RETALIATION', 2),
    'انتقام': ('REVENGE', 2),
    'لن نتوقف': ('WE WILL NOT STOP', 3),
    'مستمرون': ('WE CONTINUE', 2),
}

# Oil/shipping specific targets
OIL_TARGETS = {
    'أرامكو': ('Aramco', 4),
    'منشأة نفطية': ('Oil Facility', 4),
    'مصفاة': ('Refinery', 3),
    'خط أنابيب': ('Pipeline', 3),
    'ميناء': ('Port/Harbor', 2),
    'ناقلة': ('Tanker', 3),
    'رأس تنورة': ('Ras Tanura', 4),
    'ينبع': ('Yanbu', 3),
    'البحر الأحمر': ('Red Sea', 3),
    'باب المندب': ('Bab al-Mandab', 4),
}


def scrape_channel(username: str) -> List[Dict]:
    """Scrape a public Telegram channel's web preview."""
    url = f"https://t.me/s/{username}"
    html = fetch(url, ttl_seconds=120)  # 2-min cache for Tier 1
    if not html:
        return []

    messages = []
    msg_blocks = re.findall(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        html, re.DOTALL
    )
    timestamps = re.findall(r'<time[^>]*datetime="([^"]+)"', html)
    msg_ids = re.findall(r'data-post="[^/]+/(\d+)"', html)

    for i, text in enumerate(msg_blocks[:50]):
        clean = re.sub(r'<[^>]+>', '', text).strip()
        clean = clean.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        if not clean:
            continue
        messages.append({
            "channel": username,
            "text": clean,
            "timestamp": timestamps[i] if i < len(timestamps) else "",
            "message_id": msg_ids[i] if i < len(msg_ids) else str(i),
        })
    return messages


def classify_message(text: str) -> tuple:
    """Classify a single message. Returns (points, signals)."""
    points = 0
    signals = []
    text_norm = text.replace('#', ' ').replace('_', ' ')

    for arabic, (english, weight) in PRE_ATTACK_KEYWORDS.items():
        if arabic in text_norm:
            points += weight
            signals.append(f"PRE-ATTACK: {english}")

    for arabic, (english, weight) in ATTACK_CLAIM_KEYWORDS.items():
        if arabic in text_norm:
            points += weight
            signals.append(f"CLAIM: {english}")

    for arabic, (english, weight) in ESCALATION_KEYWORDS.items():
        if arabic in text_norm:
            points += weight
            signals.append(f"ESCALATION: {english}")

    for arabic, (english, weight) in OIL_TARGETS.items():
        if arabic in text_norm:
            points += weight
            signals.append(f"OIL TARGET: {english}")

    return points, signals


def scrape() -> Dict:
    """Run the full Houthi Telegram scraper. Returns standard result."""
    all_signals = []
    total_points = 0
    msg_count = 0
    high_messages = []

    for channel in CHANNELS:
        messages = scrape_channel(channel)
        for msg in messages:
            msg_count += 1
            points, signals = classify_message(msg["text"])
            if points > 0:
                total_points += points
                all_signals.extend(signals)
                if points >= 6:
                    high_messages.append({
                        "channel": channel,
                        "points": points,
                        "signals": signals,
                        "text_preview": msg["text"][:200],
                        "timestamp": msg["timestamp"],
                    })

    # Score 0-10 based on total points across all channels
    # 0 points = 0, 5 points = 3, 10 = 5, 20 = 7, 30+ = 9, 40+ = 10
    if total_points >= 40:
        score = 10
    elif total_points >= 30:
        score = 9
    elif total_points >= 20:
        score = 7
    elif total_points >= 15:
        score = 6
    elif total_points >= 10:
        score = 5
    elif total_points >= 5:
        score = 3
    elif total_points >= 2:
        score = 2
    else:
        score = 0

    # Confidence based on message volume
    confidence = min(1.0, msg_count / 20) if msg_count > 0 else 0.1

    # Deduplicate signals
    unique_signals = list(dict.fromkeys(all_signals))

    result = make_result(score, confidence, unique_signals[:20], "houthi_telegram")
    result["total_points"] = total_points
    result["messages_scanned"] = msg_count
    result["high_messages"] = high_messages[:10]
    return result


def run() -> Dict:
    return safe_run("houthi_telegram", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, ensure_ascii=False))
