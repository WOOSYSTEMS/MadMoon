# Meta Bug Bounty Hunting Playbook

**Hunter:** Nuwan Ambagahawatte
**Account:** Active at bugbounty.meta.com
**Date:** October 9, 2026

---

## PAYOUT TABLE

| Vulnerability | Max Payout |
|---|---|
| Mobile RCE (zero-click) | $300,000 |
| WhatsApp TEE escape/RCE | $300,000 |
| Account Takeover (0-click) | $130,000 |
| Account Takeover (1-click) | $50,000 |
| SSRF (with response) | $40,000 |
| Ads Audience PII Leak | $30,000 |
| 2FA Bypass | $20,000 |
| Account Takeover (>2-click) | $10,000 |
| XSLeak | $5,000 |
| Minimum valid bug | $500 |

---

## BIGGEST PAST PAYOUTS

- **$163,000** — Rate limiting missing on beta.facebook.com password reset
- **$111,750** — Path traversal to RCE in Messenger E2EE
- **$100,000** — Command execution on internal ad platform
- **$78,000** — IDOR exposing customer support chats via sequential case IDs
- **$27,200** — 2FA bypass via rate-limiting gap
- **$3,000** — Facebook Reels privacy misconfiguration

---

## YOUR EDGE

Your cryptographic background (AES-256-GCM, Shamir, biometric auth) gives you advantage in:
1. **WhatsApp Private Processing / TEE** ($300K ceiling) — few hunters understand this
2. **E2E encryption validation gaps** — recent CVEs are all about incomplete validation in encrypted channels
3. **Access control / IDOR** — most commonly rewarded category, maps to your authorization expertise

---

## DAY 1 METHODOLOGY

### IDOR Hunting (Highest success rate for beginners)

1. Set up 2 test accounts (A = target, B = attacker)
2. As Account A, perform actions through Burp proxy
3. Capture requests containing IDs (numeric, UUID, base64)
4. Decode base64 IDs: `echo "SW52b2ljZToxMDQy" | base64 -d` → `Invoice:1042`
5. Replay same request with Account B's cookies but Account A's IDs
6. If B gets A's data → IDOR → $5K-$78K

### GraphQL Manipulation

1. Filter Network tab by `graphql`
2. Right-click request → Copy as cURL
3. Modify node IDs in the variables
4. Add fields the UI doesn't request (use InQL to discover schema)
5. Test mutations with other users' object IDs

### Rate Limiting Bypass

Test same functionality on alternate domains:
- `m.facebook.com`
- `mbasic.facebook.com`
- `beta.facebook.com`
- `mbasic.beta.facebook.com`

The $163K bug was JUST this — rate limiting on www but not on beta.

### Privacy Bypass

1. Account A sets content to "Friends Only" or "Only Me"
2. Account B (not friends) tries to access via direct node ID queries
3. Test across: GraphQL, Graph API Explorer, mobile endpoints, alternate subdomains

---

## WHERE TO HUNT (Priority Order)

1. **Facebook Business tools** — Commerce Manager, Campaign Planner (less crowded)
2. **New features** — test privacy controls on anything recently launched
3. **Rate limiting on alternate domains** — password reset, OTP, recovery
4. **GraphQL field-level access** — request fields UI doesn't show
5. **Meta AI data leakage** — prompt injection chained with data exfil
6. **WhatsApp Web metadata** — WebSocket traffic analysis

---

## TOOLS

- **Burp Suite Community** — installed at /Applications/Burp Suite.app
- **mitmproxy** — installed at /opt/homebrew/bin/mitmproxy
- **Burp Extensions (install these):** Autorize, InQL, Param Miner, Logger++
- **Meta Tools:** FBDL, Muse Code, Graph API Explorer, WhatsApp Research Proxy
- **Clairvoyance** — GraphQL schema enumeration when introspection disabled
- **CyberChef** — base64 decode/encode node IDs

---

## REPORT TEMPLATE

```
TITLE: [Type] in [Feature] allows [Impact] via [Mechanism]

DESCRIPTION:
- What the vulnerability is
- Why it matters
- Who is affected

REPRODUCTION STEPS:
1. Log in as User A
2. [exact steps]
3. Intercept request in Burp
4. Replay with User B's session
5. Observe: unauthorized access

IMPACT:
- "As an attacker, I WAS ABLE TO [specific action]"

PROOF: Screenshots, video, HTTP request/response pairs
```

---

## RULES

- Only test on YOUR OWN accounts (use Meta whitehat test accounts)
- No DoS attacks
- No social engineering
- No automated scanning at high volume
- No public disclosure before Meta fixes it
- Must demonstrate actual impact, not theoretical
