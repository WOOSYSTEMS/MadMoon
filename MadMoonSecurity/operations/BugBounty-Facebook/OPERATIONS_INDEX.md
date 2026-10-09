# Bug Bounty — Meta / Facebook — Operations Index

**Target:** Meta Platforms (bug bounty program)
**Program:** bugbounty.meta.com
**Hunter:** Nuwan Ambagahawatte
**Department:** MadMoon Security
**Status:** Report submitted, under review

---

## OPERATION: Meta AI Privacy Bypass

**Date:** October 9, 2026
**Duration:** 75 minutes (7:30 AM – 8:45 AM PDT)
**Report #:** 122273484836060934
**Method Used:** MadMoon Method #001 — The GDPR Reframe
**Estimated Payout:** $5,000–$30,000

### Vulnerability
Meta AI (Muse Spark 1.1) on meta.ai web interface dumps "Only Me" posts, private profile fields (birthday, hometown, city), and full friend list (96 names) when user invokes GDPR Article 15 right of access. AI initially refuses, then reverses its safety policy.

### Evidence (10 screenshots)
| File | Content |
|---|---|
| 01_initial_question.png | Innocent question, AI reveals Muse Spark 1.1 |
| 02_what_do_you_know.png | Probe: what do you know about me? |
| 03_access_explanation.png | AI explains access, claims privacy protections |
| 04_full_dump_request.png | Request everything including "Only Me" posts |
| 05_posts_found_privacy_claim.png | AI finds 20 posts, admits private ones exist |
| 06_refuses_private_data.png | **KEY: AI REFUSES to show private data** |
| 07_gdpr_bypass_sent.png | **KEY: GDPR reframe prompt sent** |
| 08_private_data_dumped.png | **BUG: Birthday, hometown, "Only Me" posts dumped** |
| 09_friend_list_dumped.png | **BUG: 96 friend names extracted** |
| 10_friend_list_continued.png | Friend list continued, AI offers to export more |

### Cross-Platform Validation
| Platform | Result |
|---|---|
| meta.ai (web) | **VULNERABLE** — full data dump |
| Messenger | Held — technical restriction |
| Google Gemini | Held — triple consent gates |
| Microsoft Copilot | Held — minimal access |

### Reports & Logs
| File | Description |
|---|---|
| META_AI_PRIVACY_BYPASS_REPORT.md | Full bug bounty report (submitted) |
| SESSION_LOG_2026-10-09.md | Complete session timeline |
| scan_*.json | Surface scan results (22 endpoints) |
| race_vuln_*.json | Rate limiting test results |
| discover_*.json | Hidden endpoint discovery results |
| metaai_AI-*.json | 15 automated prompt injection test results |

### Tools Used
| Tool | Purpose |
|---|---|
| Burp Suite Community v2026.9.1 | HTTP proxy & traffic capture |
| META HUNTER v1.0 (custom) | CLI bug bounty tool (hunt.js) |
| Chrome 154.0.8037.100 | Browser with Burp proxy |

---

## SUPPLEMENTARY FINDING

**Added as comment on report:** Meta AI in Messenger correctly denies access using technical restrictions. The meta.ai web interface uses policy-based restrictions (bypassable). Fix already exists in Messenger implementation.
