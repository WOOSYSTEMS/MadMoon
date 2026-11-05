# GCash Security Dossier
## Prepared for MadMoon Security Pitch — October 27, 2026
### Classification: Public-Source Intelligence Only

---

## EXECUTIVE SUMMARY

GCash (operated by G-Xchange, Inc., a subsidiary of Mynt/Globe Fintech Innovations) is the Philippines' dominant mobile wallet with **81 million active users** and **2.5 million merchants**. Mynt IPO'd on the Philippine Stock Exchange on **October 20, 2026** (ticker: GCASH) at a **$7B valuation**, raising a record P60.9B. The platform is built on **Ant Group/Alipay technology** with Globe Telecom and Ayala Corporation as co-owners.

Despite its scale, GCash has a documented history of critical security vulnerabilities — from OTP/MPIN bypass chains to exposed Docker credentials to static encryption keys. Their Vulnerability Disclosure Program offers **no monetary rewards**, and there is **no publicly identified CISO**. This represents a significant opportunity for MadMoon Security.

---

## 1. AUTHENTICATION FLOW

### Current Authentication Stack (as of October 2026)

| Layer | Method | Details |
|-------|--------|---------|
| Primary | **MPIN** | 4-digit numeric PIN entered on every login |
| Secondary | **In-App OTP** | Push notification OTP (replaced SMS OTP on June 22, 2026) |
| Optional | **Biometrics** | Fingerprint (Android) / Face ID (iOS) — must be enabled manually |
| Fallback | **MPIN** | After 3 failed biometric attempts |

### Authentication Flow Detail

1. User opens GCash app
2. If biometrics enabled: fingerprint/Face ID prompt
3. If biometrics fail 3x or not enabled: MPIN entry screen (4-digit PIN)
4. For sensitive transactions (transfers, bank links): In-App OTP via push notification
5. OTP delivered within the authenticated GCash app, NOT via SMS
6. Session maintained within app container

### June 2026 SMS OTP Phase-Out (Critical Change)

- **Date**: June 22, 2026
- **Mandate**: BSP Circular No. 1213 (issued June 2025), implementing Section 6 of AFASA
- **Deadline**: All Philippine financial institutions must eliminate SMS OTP by June 30, 2026
- **What changed**: OTPs now delivered as in-app push notifications, not SMS
- **Why**: SMS OTPs vulnerable to SIM swap, SS7 interception, and social engineering
- **Compliance requirement**: High-risk transactions must use phishing-resistant, device-bound alternatives (FIDO2/WebAuthn passkeys or server-side biometrics)
- **Liability impact**: Under AFASA, institutions that fail to implement adequate authentication must reimburse scam victims; compliant ones get a liability shield

### Known Authentication Vulnerabilities (Historical)

**OTP Bypass via Response Manipulation (2022-2023)**
- Researcher Joel Ilagan demonstrated OTP bypass through HTTP response manipulation
- When correct OTP entered, server returns status 201; manipulating response to 201 for any OTP bypasses verification
- Reported January 2023; GCash confirmed they had received similar reports
- Source: https://medium.com/@joelilagan/my-poc-of-gcash-vulnerability-called-otp-bypass-or-authentication-bypass-through-response-a55ed910c565

**MPIN Bypass via Chained Exploits (2022)**
- Researcher nmochea demonstrated full MPIN bypass by chaining OTP bypass with deeplink vulnerability
- Exploit allowed: transfer money, withdraw from bank accounts, connect/disconnect bank accounts
- **Arbitrary Deeplink Vulnerability** enabled launching arbitrary URLs, UXSS attacks, file access, host validation bypass
- Reported September 4, 2022; patched October 10, 2022
- Source: https://nmochea.medium.com/gcash-vulnerability-walkthrough-c7c938163dfb

**Static Encryption Key (USENIX 2015)**
- GCash ships a static symmetric key in file "enc.key" with every APK download
- User PIN and session ID encrypted with this public key before transmission
- PIN sent in plaintext over SMS during registration
- PIN written to verbose logging facility in plaintext
- Source: USENIX Security Symposium 2015, sec15-paper-reaves-mobile

---

## 2. API ARCHITECTURE & TECH STACK

### API Gateway

- **Kong Gateway** (started Community Edition, migrated to Enterprise)
- Decentralized microservices architecture
- Kong enforces security, rate limiting, access control across all microservices
- Plugin architecture for extending functionality (authentication integration with internal identity systems)
- **Savings**: $70K/month in infrastructure costs after Kong migration
- **Team**: 40 infrastructure engineers trained on Kong (foundation + intermediate)
- Source: https://konghq.com/customer-stories/gcash

### Technology Stack (from job postings and public sources)

| Layer | Technologies |
|-------|-------------|
| **Backend Languages** | Java, Go (Golang), JavaScript |
| **Mobile (Android)** | Java, Kotlin, Android Studio |
| **Web Frontend** | JavaScript, jQuery, HTML5, CSS3 |
| **Web Servers** | Apache, Nginx, HAProxy |
| **Database** | MySQL (confirmed from Docker leak) |
| **API Protocols** | REST, SOAP/WSDL |
| **API Gateway** | Kong Enterprise |
| **Mini Programs** | Custom JS framework (Alipay-derived), AXML templating |
| **Payment Processing** | OpenFabric (Mastercard token provisioning), Alipay+ gateway |
| **Blockchain** | Alipay blockchain (cross-border remittance) |

### Core Platform Origin

GCash's technology platform was rebuilt through a **phased technical migration with Alipay+ Wallet Tech** starting 2019. The app is modeled on Alipay's super-app architecture. This means the underlying framework, mini-program runtime, and payment infrastructure share DNA with Ant Group's stack.

### Mini Program Platform

- Public developer platform: https://miniprogram.gcash.com
- JavaScript-based development
- Custom AXML markup language (Alipay-derived)
- Components: Framework, UI Components, JSAPIs, Open APIs
- Mini Program Studio IDE provided
- Developer Center for managing releases

### Merchant API Access

- **No public merchant API** — access is limited to selected partner organizations
- Merchants integrate via licensed payment gateways (PayMongo, 2C2P, HitPay, etc.)
- Direct partnership requires formal onboarding with GCash account manager
- GCash API Portal FAQ confirms restricted access

### Payment Integration Partners

- **Mastercard**: Tap n' Pay NFC contactless payments via OpenFabric token provisioning
- **Alipay+**: Cross-border payments in 55+ global markets, 10M merchants
- **OpenFabric**: Digital payment partner managing Mastercard transaction gateway
- **QRPh**: National QR code payment standard (BSP-mandated interoperability)

---

## 3. KNOWN VULNERABILITIES & SECURITY INCIDENTS

### Critical Vulnerabilities (Confirmed)

| Year | Vulnerability | Severity | Status |
|------|--------------|----------|--------|
| 2015 | Static encryption key shipped in APK (enc.key) | CRITICAL | Unknown if resolved |
| 2015 | Plaintext PIN in verbose logs | CRITICAL | Unknown if resolved |
| 2015 | PIN sent plaintext over SMS during registration | HIGH | Likely mitigated by SMS OTP phase-out |
| 2022 | OTP bypass via response manipulation | CRITICAL | Patched |
| 2022 | MPIN bypass via chained OTP bypass + deeplink | CRITICAL | Patched Oct 10, 2022 |
| 2022 | Arbitrary deeplink vulnerability (UXSS, file access) | HIGH | Patched Oct 10, 2022 |
| 2024 | Docker Hub credentials exposure (gcashsupport account) | CRITICAL | Unknown |
| 2025 | HTTP PUT method enabled on resources.gcash.com | MEDIUM | Unknown |

### Docker Hub Credential Exposure (2024) — CRITICAL

A security researcher discovered that GCash's Docker Hub account **gcashsupport** contained publicly accessible images with:
- **Production database credentials** in environment variables
- **SSH keys** in some images
- **GCash Mastercard and Gift Card database credentials**
- **gscore computation API endpoint**
- Multiple images with dedicated databases, each exposing different credential sets
- Image `gcashsupport/ms-login:1.0` contained login service credentials
- Image `gcashsupport/lendingeligibilitytool` contained card database credentials
- Some images were actively maintained (updates days old)

Source: https://ph-hitachi.medium.com/how-i-hacked-globe-gcash-services-and-manage-to-get-access-on-multiple-databases-including-ssh-9ca781348e8f

### HTTP PUT Method Enabled (2025)

- Researcher Evan Ricafort found HTTP PUT method enabled on `resources.gcash.com`
- Demonstrated ability to create arbitrary files on the server (test-evan.html)
- Detected via Nuclei scan
- Source: https://blog.evanricafort.com/2025/01/http-put-method-enabled-gcash.html

### Major Incidents

**May 2023 — P37M Theft Attempt**
- Hackers exploited a bug allowing fund transfers without deducting source balance
- Detected late night May 8 — pattern of small withdrawals to EastWest Bank and AUB accounts
- 1,200 user accounts suspended
- P37M recovered and returned within 7 days
- Source: https://business.inquirer.net/400030/gcash-foils-p37-m-hack-try-seized-funds-to-be-returned-to-users

**November 2024 — Organized Breach Investigation**
- CICC investigated "possible organized breach" of GCash accounts
- Unauthorized fund transfers reported by multiple users
- NPC opened investigation
- Source: https://www.rappler.com/technology/gcash-possible-organized-breach-cybercrime-investigation/

**October 2025 — Dark Web Data Leak Claims**
- User "Oversleep8351" posted on dark web claiming millions of GCash user records
- Claimed data: eKYC info, linked bank accounts, GCash numbers, employment details, Philippine IDs
- Claimed records spanning 2019 to October 2025
- GCash denied breach — said dataset doesn't match their data structures
- NPC concluded investigation: no evidence of breach, dataset inconsistent with GCash systems
- CICC determined datasets were "old and recycled"
- NPC live demonstration showed zero unauthorized access events Jan 1 - Oct 29, 2025
- Sources: https://privacy.gov.ph/npc-concludes-investigation-on-reported-gcash-data-exposure-no-breach-found/ and https://darknetsearch.com/knowledge/news/en/gcash-data-breach-2025-revealed-key-facts-risks-proof-from-the-dark-web/

---

## 4. FRAUD VECTORS (Detailed)

### The Eight Active Scam Plays (2026)

1. **Phishing SMS** — Fake GCash login pages via SMS links
2. **SIM Swap** — Port victim's number to harvest OTPs (mitigated post-June 2026)
3. **Phone-Call OTP Harvest** — Fake "GCash agent" calls requesting OTP
4. **Fake Job Placement** — Asks for OTP or registration fee
5. **Express Send Social Engineering** — "Wrong recipient" manipulation
6. **Account Takeover via Leaked OTP** — Using previously harvested OTPs
7. **Fake QR Overlay at Merchants** — Physical QR code replacement/overlay
8. **Fake Bill-Pay Merchants** — Drains wallet through fraudulent merchant accounts

### Quishing (QR Phishing) — Detailed Flow

1. Scammers create fake QR codes mimicking legitimate GCash/QRPh payment pages
2. QR codes placed in posters, emails, receipts, messages, or physical overlays at merchant locations
3. Scanning redirects to fake payment page using lookalike domains:
   - `gcash-payments.com` (fake)
   - `gcsh.payment.com` (fake)
   - vs. `payments.gcash.com` (real)
4. Fake pages display GCash/QRPh logos but with mismatched merchant names (e.g., "XJ82q" or "Merchant_123")
5. User enters credentials on fake page, which are harvested
6. **Scale**: GCash has blocked **6,700+ fraudulent merchants** using quishing since 2025, and **4,900+ merchants** specifically linked to QR phishing

### SIM Swap Attack Flow (Pre-June 2026)

1. Attacker gathers victim's personal info (name, DOB, address) via social engineering/data leaks
2. Contacts Globe Telecom (GCash's parent telco) claiming lost SIM
3. Answers security questions using gathered info
4. New SIM activated with victim's number — old SIM deactivated
5. Attacker receives SMS OTP on their device
6. Logs into GCash with harvested MPIN + intercepted OTP
7. Transfers funds out
8. **Mitigation**: In-app OTP (June 2026) significantly reduces this vector since OTP now goes to the authenticated app, not the phone number

### Phishing Site Characteristics

- Mimics official GCash UI/login screens
- Often distributed via gambling sites ("Philwin", "tapwin1.com")
- Fake links sent via SMS, Facebook, Viber
- Domains closely resemble official GCash domains
- Some use SSL certificates to appear legitimate

---

## 5. COMPLIANCE & REGULATORY FRAMEWORK

### Primary Regulators

| Regulator | Role |
|-----------|------|
| **BSP** (Bangko Sentral ng Pilipinas) | Primary financial regulator; GCash is licensed as an Electronic Money Issuer (EMI) |
| **NPC** (National Privacy Commission) | Enforces Data Privacy Act of 2012 |
| **AMLC** (Anti-Money Laundering Council) | AML/CFT compliance |
| **CICC** (Cybercrime Investigation and Coordinating Center) | Cybercrime investigation |
| **SEC** (Securities and Exchange Commission) | Post-IPO corporate governance |

### Key Regulations

**BSP Circular No. 1213 (June 2025)**
- Implements Section 6 of AFASA
- Mandates phase-out of SMS/email OTPs for high-risk transactions by June 30, 2026
- Requires: FIDO2/WebAuthn passkeys OR server-side biometrics with device attestation
- Non-compliant institutions must reimburse scam victims

**Anti-Financial Account Scamming Act (AFASA)**
- Strengthens cybersecurity safeguards
- Creates liability framework for financial institutions
- Compliant institutions get liability shield
- Non-compliant must reimburse customers for losses

**BSP Circular No. 908**
- AML/CFT regulations for BSP-supervised financial institutions
- KYC/eKYC verification standards
- Suspicious transaction reporting to AMLC
- License revocation risk for non-compliance

**Data Privacy Act of 2012 (Republic Act No. 10173)**
- Personal data collection, storage, processing requirements
- Mandatory breach notification to NPC
- GCash privacy notice at gcash.com/privacy-notice/english

### GCash Anti-Fraud Measures (Demonstrated)

- Blocked 3,200+ merchants linked to illegal gambling (with CICC/PNP-ACG, announced March 2026)
- Blocked 6,700+ illegal gambling sites using QRPh
- Blocked 4,900+ quishing/QR phishing merchants
- Proactive transaction monitoring
- Suspicious transactions reported to AMLC and CICC
- Fraudulent merchants immediately suspended

---

## 6. INFRASTRUCTURE

### Confirmed Infrastructure Components

| Component | Details |
|-----------|---------|
| **API Gateway** | Kong Enterprise (migrated from Community Edition) |
| **Web Servers** | Nginx, Apache, HAProxy (from job postings) |
| **Database** | MySQL (confirmed from Docker credential leak) |
| **Payment Gateway** | OpenFabric (Mastercard tokenization) |
| **Cross-Border** | Alipay+ global wallet gateway |
| **Mini Program Runtime** | Custom container (Alipay-derived) |
| **Docker** | Used for microservices (gcashsupport Docker Hub account) |
| **NFC Payments** | Mastercard token provisioning via OpenFabric |

### Cloud Hosting

- **Not publicly confirmed** which cloud provider(s) GCash uses
- Given Ant Group partnership, likely involvement of Alibaba Cloud infrastructure
- Docker containerization confirmed from the credential leak incident
- Microservices architecture confirmed from Kong case study

### CDN/WAF

- Public reports reference **Cloudflare** and **Imperva** as detected on GCash properties (per your prior finding)
- No official confirmation from GCash

### Security Infrastructure Gaps Identified

1. Docker Hub account (`gcashsupport`) contained production credentials in public images
2. HTTP PUT method was enabled on `resources.gcash.com` without authentication
3. No evidence of comprehensive secrets management (credentials in env vars in Docker images)
4. Multiple databases with credentials spread across different Docker images suggests fragmented secrets management

---

## 7. THIRD-PARTY INTEGRATIONS

### Banking Partners

- **EastWest Bank** — Cash-in/cash-out, linked accounts
- **AUB (Asia United Bank)** — Cash-in/cash-out
- **Multiple Philippine banks** — via InstaPay and PESONet (BSP-mandated interbank transfers)
- **BPI, BDO, UnionBank, Metrobank** — among major bank partners for fund transfers

### Payment Partners

| Partner | Integration |
|---------|------------|
| **Mastercard** | Tap n' Pay NFC contactless (via OpenFabric) |
| **Alipay+** | Cross-border payments, 55+ markets, 10M merchants |
| **OpenFabric** | Token provisioning, transaction gateway |
| **QRPh** | National QR payment standard (BSP interoperability) |
| **2C2P** | Payment gateway integration |
| **PayMongo** | Merchant payment acceptance |

### Merchant Integration Routes

1. **Direct Partnership API** — Restricted, requires formal onboarding
2. **Licensed Payment Gateways** — PayMongo, 2C2P, HitPay etc.
3. **Mini Program Platform** — In-app mini apps with JSAPIs/Open APIs

### GCash Mastercard Virtual Card

- Tap n' Pay powered by NFC technology
- Works on NFC-enabled Android smartphones
- Taps on compatible POS terminals
- OpenFabric manages Mastercard token provisioning
- Currently local transactions only; international planned

### Cross-Border Capabilities

- Alipay+ gateway: 55+ markets
- Blockchain-powered remittance (with AlipayHK)
- GCash Tap to Pay going global via Alipay+ and Mastercard collaboration

---

## 8. MOBILE APP SECURITY

### Confirmed Security Controls

| Control | Status |
|---------|--------|
| **Root/Jailbreak Detection** | YES — blocks rooted Android and jailbroken iOS devices |
| **Developer Mode Detection** | YES — blocks devices in developer mode |
| **Tamper Detection** | YES — detects method swizzling and app modifications |
| **Biometric Authentication** | YES — optional Face ID / fingerprint |
| **In-App OTP** | YES — replaced SMS OTP June 2026 |

### Known Weaknesses (Historical and Potential)

| Issue | Details | Status |
|-------|---------|--------|
| **Static encryption key** | Symmetric key (enc.key) shipped with every APK | Unknown if resolved (found 2015) |
| **Plaintext PIN logging** | PIN written to verbose log facility | Unknown if resolved (found 2015) |
| **OTP response manipulation** | HTTP response code bypass | Patched (2023) |
| **Deeplink arbitrary URL** | UXSS, file access via malicious deeplinks | Patched (2022) |
| **Certificate pinning** | No public evidence of certificate pinning implementation | Unconfirmed |
| **Code obfuscation** | Standard Android APK (easily decompilable per researchers) | Likely basic ProGuard |

### APK Analysis Surface

- GCash APK is distributed via Google Play Store and third-party sites
- Researchers have successfully decompiled and analyzed the APK using standard tools (JADX, apk-mitm)
- The Alipay-derived framework adds complexity but the core authentication logic has been reverse-engineered multiple times
- Docker images on Docker Hub provided additional attack surface for understanding internal architecture

---

## 9. COMPETITIVE LANDSCAPE

### Maya (formerly PayMaya)

| Aspect | GCash | Maya |
|--------|-------|------|
| **Users** | 81M active | ~55M registered |
| **Regulation** | EMI (BSP) | Digital Bank (BSP) |
| **Deposit Insurance** | PDIC-insured | PDIC-insured |
| **Auth: Primary** | 4-digit MPIN | 6-char alphanumeric password |
| **Auth: 2FA** | In-app OTP | OTP + biometrics |
| **Biometrics** | Fingerprint + Face ID | Fingerprint + Face ID |
| **Tech Partner** | Ant Group/Alipay | Tencent (former), Voyager (PLDT) |
| **Bug Bounty** | VDP (no rewards) | No public program found |
| **Market Position** | Dominant (#1) | Challenger (#2) |

### Security Comparison

- Maya requires a 6-character alphanumeric password vs. GCash's 4-digit MPIN — Maya's is stronger
- Both use 2FA and biometrics
- Both comply with BSP Circular 1213 (SMS OTP phase-out)
- GCash has more publicly documented vulnerabilities (likely due to larger attack surface and researcher interest)
- GCash has a formal VDP; Maya does not appear to have one

---

## 10. CORPORATE SECURITY POSTURE

### Leadership

- **No publicly identified CISO** — a significant gap for a company of this scale and public listing
- Operated by G-Xchange, Inc. (subsidiary of Mynt)
- Mynt CEO leads overall strategy; security leadership not publicly profiled
- **Miguel Geronilla** appears linked to GCash security (from LinkedIn/VDP search results) but role unconfirmed

### Vulnerability Disclosure Program

- **URL**: https://help.gcash.com/hc/en-us/articles/55399792324761-What-is-the-Vulnerability-Disclosure-Program
- **Type**: VDP (Vulnerability Disclosure Program)
- **Rewards**: NO monetary rewards
- **Platform**: Self-hosted (not on HackerOne or Bugcrowd)
- **Maturity**: Basic — no public scope definition, no safe harbor language found, no SLA commitments visible

### Security Team Indicators

- Job postings show hiring for software engineers but no dedicated security engineer roles visible in search
- 40 infrastructure engineers trained on Kong (API security)
- NPC investigation showed GCash conducted live technical demonstrations of their security monitoring
- GCash claims zero unauthorized access events to critical databases (Jan-Oct 2025)

### Contact Channels

- **Help Center**: help.gcash.com
- **Chatbot**: "Gigi" (in-app)
- **Hotline**: 2882
- **Corporate**: mynt.com.ph/newsroom
- **VDP**: Through help center

---

## 11. ATTACK SURFACE SUMMARY

### External Attack Surface

| Asset | Risk Level | Notes |
|-------|-----------|-------|
| gcash.com | HIGH | Main web property |
| resources.gcash.com | HIGH | HTTP PUT was enabled (Ricafort finding) |
| help.gcash.com | MEDIUM | Help center, potential info disclosure |
| miniprogram.gcash.com | MEDIUM | Developer platform, documented APIs |
| payments.gcash.com | CRITICAL | Payment processing |
| Docker Hub (gcashsupport) | CRITICAL | Production credentials exposed |
| GCash Android APK | HIGH | Decompilable, static key history |
| GCash iOS App | HIGH | Deeplink vulnerabilities documented |
| Kong API Gateway | MEDIUM | Enterprise version, but misconfiguration risk |
| Third-party PSP integrations | MEDIUM | Multiple gateway connections |

### Internal Risk Factors

1. **Secrets Management**: Production DB credentials found in Docker images — suggests no centralized secrets vault
2. **Legacy Code**: Migration from old platform to Alipay stack may leave orphaned endpoints
3. **Scale vs. Security**: 81M users, rapid feature expansion, IPO pressure
4. **Authentication Fundamentals**: 4-digit MPIN is weak by modern standards
5. **VDP Maturity**: No rewards = low researcher incentive to report responsibly
6. **No Public CISO**: Suggests security may not have C-suite representation

---

## 12. PITCH ANGLE RECOMMENDATIONS

### Why GCash Needs MadMoon Security

1. **Post-IPO Scrutiny**: As a publicly traded company (GCASH on PSE), security incidents now have stock price implications. The October 2025 dark web scare happened right before their IPO.

2. **Regulatory Pressure**: AFASA creates direct financial liability for security failures. BSP Circular 1213 demands phishing-resistant auth. Non-compliance = mandatory victim reimbursement.

3. **Documented Vulnerability History**: Multiple critical findings by independent researchers (OTP bypass, MPIN bypass, Docker credentials, HTTP PUT, static encryption key). Pattern suggests reactive, not proactive security.

4. **No Bug Bounty**: Their VDP offers no rewards. MadMoon could propose a managed bug bounty or penetration testing program.

5. **Scale**: 81M users, P60.9B IPO, Mastercard integration, cross-border payments in 55+ markets. The attack surface is enormous and growing.

6. **Competitive Pressure**: If Maya implements better security, GCash loses its "safe" narrative.

### Specific Service Offerings to Pitch

| Service | Justification |
|---------|--------------|
| **Penetration Testing** | Multiple public vulns found by researchers; proactive testing needed |
| **API Security Audit** | Kong gateway + microservices = complex attack surface |
| **Mobile App Security Assessment** | Historical APK weaknesses, deeplink vulns |
| **Secrets Management Consulting** | Docker credential leak shows fundamental gap |
| **Cloud Infrastructure Review** | Unknown cloud posture, containerized microservices |
| **Bug Bounty Program Design** | Current VDP is immature, no rewards, no platform |
| **Incident Response Retainer** | P37M hack, dark web leaks show need for IR capability |
| **Compliance Assessment** | AFASA/BSP 1213 compliance verification |
| **Red Team Exercise** | Full-scope attack simulation against auth flows |

---

## SOURCES

### Authentication & OTP Phase-Out
- [GCash In-App OTP Rollout - GMA Network](https://www.gmanetwork.com/news/money/companies/990983/gcash-to-roll-out-in-app-otps-starting-june-22-2026/story/)
- [GCash Ditches SMS Codes - GizGuide](https://www.gizguide.com/2026/06/gcash-in-app-otp-roll-out.html)
- [GCash Shift to In-App OTPs - BusinessWorld](https://bworldonline.com/banking-finance/2026/06/09/755221/gcash-to-shift-to-in-app-otps-for-authentication/)
- [GCash Biometrics Help](https://help.gcash.com/hc/en-us/articles/4413281262105-How-to-enable-biometrics)
- [BSP Circular 1213 - Corbado](https://www.corbado.com/blog/philippines-compliance)
- [BSP Circular 1213 - Authsignal](https://www.authsignal.com/blog/articles/bsp-circular-1213-philippine-banks-must-replace-sms-otps-by-june-2026)

### Tech Stack & Architecture
- [GCash Saves $70K/Month with Kong](https://konghq.com/customer-stories/gcash)
- [GCash Mini Program Documentation](https://miniprogram.gcash.com/docs/)
- [GCash API Integration Guide - HitPay](https://hitpayapp.com/blog/gcash-api-integration-philippines)
- [GCash Journey to Super App - Alipay+](https://www.alipayplus.com/wallet-tech/Gcash/)
- [GCash Senior Engineer Job Posting - BuiltIn](https://builtin.com/job/senior-software-engineer/4240271)
- [GCash Go Lang Engineer - LinkedIn](https://www.linkedin.com/jobs/view/4183372178/)

### Vulnerabilities & Incidents
- [GCash OTP Bypass POC - Joel Ilagan](https://medium.com/@joelilagan/my-poc-of-gcash-vulnerability-called-otp-bypass-or-authentication-bypass-through-response-a55ed910c565)
- [Hacking GCash MPIN Bypass - nmochea](https://nmochea.medium.com/gcash-vulnerability-walkthrough-c7c938163dfb)
- [Globe/GCash Docker Image Hack - ph-hitachi](https://ph-hitachi.medium.com/how-i-hacked-globe-gcash-services-and-manage-to-get-access-on-multiple-databases-including-ssh-9ca781348e8f)
- [HTTP PUT on resources.gcash.com - Evan Ricafort](https://blog.evanricafort.com/2025/01/http-put-method-enabled-gcash.html)
- [Mobile Banking Security - USENIX 2015](https://www.usenix.org/system/files/conference/usenixsecurity15/sec15-paper-reaves-mobile_0.pdf)
- [GCash Foils P37M Hack - Inquirer](https://business.inquirer.net/400030/gcash-foils-p37-m-hack-try-seized-funds-to-be-returned-to-users)
- [GCash Dark Web Data Leak - DarknetSearch](https://darknetsearch.com/knowledge/news/en/gcash-data-breach-2025-revealed-key-facts-risks-proof-from-the-dark-web/)
- [NPC Investigation Conclusion](https://privacy.gov.ph/npc-concludes-investigation-on-reported-gcash-data-exposure-no-breach-found/)

### Fraud & Scams
- [GCash Scams 2026: Eight Plays - LiveInPH](https://liveinph.com/gcash-scams-2026-prevention-refund)
- [GCash Quishing Crackdown - Manila Bulletin](https://mb.com.ph/2026/04/23/gcash-upholds-zero-tolerance-on-quishing-scam-blocks-fake-illegal-sites)
- [GCash Blocks 6700 Gambling Sites - Mynt](https://mynt.com.ph/newsroom/gcash-blocked-6700-illegal-gambling-sites-using-qrph)
- [GCash CICC Block 3200 Merchants - GMA](https://www.gmanetwork.com/news/money/companies/980363/gcash-cicc-merchants-users/story/)
- [NPC Confirms Phishing - PNA](https://www.pna.gov.ph/articles/1202151)

### Compliance & Regulation
- [AFASA Compliance Checklist](https://www.trustingsocial.ph/resources/blogs/afasa-compliance-checklist-bsp-circular-1213)
- [GCash Legal Framework - Respicio](https://www.respicio.ph/dear-attorney/understanding-the-legal-framework-and-procedures-for-verifying-a-gcash-account-in-the-philippines)
- [GCash Privacy Notice](https://gcash.com/privacy-notice/english)

### Corporate & Security Program
- [GCash VDP](https://help.gcash.com/hc/en-us/articles/55399792324761-What-is-the-Vulnerability-Disclosure-Program)
- [GCash Device Security](https://help.gcash.com/hc/en-us/articles/22448805006361-What-is-Device-Security)
- [GCash Root/Jailbreak Warning - Technobaboy](https://www.technobaboy.com/2023/10/03/gcash-blocks-access-to-rooted-and-jailbroken-devices-for-security-reasons/)
- [Mynt IPO - Rappler](https://www.rappler.com/business/gcash-mynt-stock-market-debut-pse-listing-october-20-2026/)
- [Mynt $7B Valuation - FintechFutures](https://www.fintechfutures.com/stock-exchange-ipos/mynt-gcash-ipo)
- [GCash Mastercard Tap n Pay - BusinessWorld](https://www.bworldonline.com/banking-finance/2025/04/23/667423/gcash-partners-with-mastercard-for-contactless-payments-via-app/)
- [GCash and Ant Group - Manila Times](https://www.manilatimes.net/2026/10/28/opinion/columns/gcashs-second-biggest-owner-and-tech-provider-chinas-ant-alipay-group/2455081)

---

*Dossier compiled October 27, 2026 — MadMoon Security*
*All information sourced from publicly available materials only.*
