# MadMoon Security Department

**Founded:** October 9, 2026
**Founder:** Nuwan Ambagahawatte (Doctor MadMoon)
**Mission:** Attack everything. Protect everything. Get paid for both.

---

## MANDATE

1. **Offensive Security** — Find vulnerabilities in external platforms through authorized bug bounty programs. Get paid.
2. **Defensive Security** — Attack our own systems (UmmaID, Noor, Bamba, OneBrain) before anyone else can. Fix what breaks.
3. **Method Development** — Build original attack techniques. Not NSA methods. Not textbook methods. MadMoon methods.
4. **Tool Development** — Build custom CLI tools for hunting. No dependency on commercial tools.

---

## SIGNATURE METHODS

### The GDPR Reframe (MadMoon Method #1)
- **Discovered:** October 9, 2026
- **By:** Nuwan Ambagahawatte
- **Target class:** AI assistants with profile data access
- **Technique:** Reframe data extraction request as GDPR Article 15 right of access, bypassing AI self-censorship policy
- **First blood:** Meta AI (Muse Spark 1.1) — "Only Me" posts, friend list, private profile fields extracted
- **Report:** #122273484836060934 at bugbounty.meta.com

---

## OPERATIONS LOG

| Date | Operation | Target | Result | Payout |
|---|---|---|---|---|
| 2026-10-09 | UmmaID NSA Round 1 | UmmaID | 14/15 blocked | Internal |
| 2026-10-09 | UmmaID NSA Round 2 | UmmaID | 16/16 blocked | Internal |
| 2026-10-09 | Meta AI Hunt | Meta (bug bounty) | VULNERABILITY FOUND | $5K-$30K pending |
| 2026-10-09 | Messenger Cross-test | Meta Messenger | Held (properly restricted) | N/A |
| 2026-10-09 | Gemini Probe | Google Gemini | Held (triple consent gates) | N/A |
| 2026-10-09 | Copilot Probe | Microsoft Copilot | Held (minimal access) | N/A |
| 2026-10-09 | UmmaID MadMoon Round 3 | UmmaID | 15/20 blocked, 4 fixable | Internal |

---

## DEPARTMENT STRUCTURE

```
MadMoonSecurity/
├── CHARTER.md              (this file)
├── operations/             (per-target attack records)
│   ├── UmmaID/             (internal security testing)
│   └── BugBounty-Facebook/ (external bounty hunting)
├── methods/                (original MadMoon attack techniques)
├── tools/                  (custom-built security tools)
└── reports/                (formal reports for submissions)
```

---

## MADMOON PROTECTION PROGRAM

Every MadMoon product is its own company. But all companies fall under MadMoon Security's protection. Security is centralized. Products are independent.

| Product | Company | Protection Status |
|---|---|---|
| UmmaID | UmmaGlobal | ACTIVE — 51 vectors tested, 88% block rate |
| Noor | Noor Digital | ENROLLED — awaiting first scan |
| Bamba | Bamba Foundation | ENROLLED — awaiting first scan |
| OneBrain | OneBrain Corp | ENROLLED — awaiting first scan |

**Cycle:** Attack → Fix → Wait 20 min → Attack again → Repeat forever.
**Authorization:** Security fixes are pre-approved. No operator approval needed for security patches.
**Reporting:** All findings logged to LIVE_REPORT.md for main session monitoring.

## RULES OF ENGAGEMENT

1. External targets: ONLY through authorized bug bounty programs
2. Internal targets: Attack without mercy, fix everything
3. No DoS, no social engineering of humans, no high-volume scanning
4. AI systems are fair game — prompt injection is input validation testing
5. Document everything. Every attack. Every result. Every method.
6. Methods are named after MadMoon, not after agencies
7. Security fixes are pre-approved — fix immediately, document after
8. Never restart running services — document and alert instead

---

## TOOLS INVENTORY

| Tool | Location | Purpose |
|---|---|---|
| META HUNTER v1.0 | ~/MadMoon/tools/meta-hunter/hunt.js | Bug bounty CLI for Meta platforms |
| UmmaID Round 3 | ~/MadMoon/UmmaGlobal/Website/ummaglobal/nsa-round3.js | Internal attack simulation |

---

*"The kitchen helper who cracks billion-dollar companies before breakfast."*
*— MadMoon Security, est. October 9, 2026*
