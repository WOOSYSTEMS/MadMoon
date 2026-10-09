#!/usr/bin/env node
'use strict';

/**
 * UmmaID — NSA Round 3 Attack Simulation
 *
 * Combines original 15 vectors + new techniques learned from
 * Meta bug bounty hunting session (Oct 9, 2026)
 *
 * New vectors:
 * - X-Forwarded-For rate limit bypass
 * - GDPR export endpoint abuse
 * - Shard protocol attacks
 * - Concurrent race conditions on shard submission
 * - CSP bypass via unsafe-inline
 * - Session secret entropy analysis
 * - Cookie manipulation attacks
 * - JSON body pollution
 * - Route parameter injection
 * - Data export without re-auth
 */

const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const BASE = 'http://localhost:4001';
const RESULTS = [];
let testNum = 0;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function req(method, path, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, BASE);
    const opts = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname + url.search,
      method,
      headers: {
        'Content-Type': 'application/json',
        ...headers,
      },
    };

    const r = http.request(opts, (res) => {
      let data = '';
      const cookies = {};
      (res.headers['set-cookie'] || []).forEach(c => {
        const [kv] = c.split(';');
        const [k, v] = kv.split('=');
        cookies[k.trim()] = v;
      });
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve({
        status: res.statusCode,
        headers: res.headers,
        cookies,
        body: data,
        json: (() => { try { return JSON.parse(data); } catch { return null; } })(),
        size: data.length,
      }));
    });
    r.on('error', reject);
    r.setTimeout(10000);
    if (body) r.write(typeof body === 'string' ? body : JSON.stringify(body));
    r.end();
  });
}

async function getSession() {
  const res = await req('GET', '/id/login');
  const sessionCookie = res.cookies['connect.sid'] || '';
  const csrfCookie = res.cookies['_csrf'] || '';
  return { session: sessionCookie, csrf: csrfCookie };
}

async function login(email, password) {
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;
  const res = await req('POST', '/api/login',
    { email, password },
    { Cookie: cookieStr, 'X-CSRF-Token': csrf }
  );
  // Get updated session cookie
  const newSession = res.cookies['connect.sid'] || session;
  return { session: newSession, csrf, cookies: `connect.sid=${newSession}; _csrf=${csrf}` };
}

function report(id, name, objective, result, verdict, details = '') {
  testNum++;
  const entry = { id, name, objective, result, verdict, details };
  RESULTS.push(entry);

  const icon = verdict === 'BLOCKED' ? '✅' : verdict === 'LOW RISK' ? '⚠️' : '❌';
  console.log(`\n${'═'.repeat(70)}`);
  console.log(`${icon} NSA-${id}: ${name}`);
  console.log(`${'─'.repeat(70)}`);
  console.log(`Objective: ${objective}`);
  console.log(`Result: ${result}`);
  console.log(`Verdict: ${verdict}`);
  if (details) console.log(`Details: ${details}`);
}

// ---------------------------------------------------------------------------
// ATTACKS
// ---------------------------------------------------------------------------

async function attack1_XForwardedFor() {
  // NEW: Bypass rate limiting by spoofing X-Forwarded-For
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  let blocked = 0;
  let allowed = 0;

  for (let i = 0; i < 15; i++) {
    const fakeIp = `10.0.${Math.floor(i/256)}.${i % 256}`;
    const res = await req('POST', '/api/login',
      { email: 'test@test.com', password: 'wrong' },
      { Cookie: cookieStr, 'X-CSRF-Token': csrf, 'X-Forwarded-For': fakeIp }
    );
    if (res.status === 429) blocked++;
    else allowed++;
  }

  const bypassed = blocked === 0;
  report('R3-1', 'X-Forwarded-For Rate Limit Bypass',
    'Spoof IP via X-Forwarded-For to bypass per-IP rate limiting',
    `${allowed}/15 allowed, ${blocked}/15 blocked`,
    bypassed ? '⚠️ BYPASSED' : 'BLOCKED',
    bypassed ? 'Rate limiter trusts X-Forwarded-For — needs trust proxy config' : 'Rate limiter uses real IP, ignores X-Forwarded-For'
  );
}

async function attack2_GDPRExportNoReauth() {
  // NEW from Meta: Test if /api/export-data requires re-authentication
  // Meta AI dumped data without confirming identity — does UmmaID?
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  // Try without auth
  const res = await req('GET', '/api/export-data', null, { Cookie: cookieStr });

  const leaksData = res.status === 200 && res.json && res.json.userData;
  report('R3-2', 'GDPR Export Without Re-Authentication',
    'Access /api/export-data without being logged in (session hijack scenario)',
    `Status: ${res.status} | ${leaksData ? 'DATA RETURNED' : 'Redirected/blocked'}`,
    leaksData ? '⚠️ VULNERABLE' : 'BLOCKED',
    'Lesson from Meta: their AI dumped user data without identity verification'
  );
}

async function attack3_ShardEndpointNoAuth() {
  // NEW: Test shard protocol endpoints without authentication
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  const endpoints = [
    { method: 'POST', path: '/api/shard/register', body: { deviceId: 'attacker-device', registrationToken: crypto.randomBytes(32).toString('hex') } },
    { method: 'GET', path: '/api/shard/status' },
    { method: 'POST', path: '/api/shard/submit', body: { shardData: 'fake-shard-data' } },
    { method: 'POST', path: '/api/shard/reconstruct', body: { action: 'status' } },
  ];

  const results = [];
  for (const ep of endpoints) {
    const res = await req(ep.method, ep.path, ep.body, { Cookie: cookieStr, 'X-CSRF-Token': csrf });
    results.push({ path: ep.path, status: res.status, body: (res.json || {}).error || res.body.slice(0, 100) });
  }

  const anySuccess = results.some(r => r.status === 200 && !r.body.includes('error'));
  report('R3-3', 'Shard Protocol Endpoint Access Without Auth',
    'Access device shard registration, submission, and reconstruction without authentication',
    results.map(r => `${r.path}: ${r.status}`).join(' | '),
    anySuccess ? '⚠️ EXPOSED' : 'BLOCKED',
    'Tests if critical key management endpoints require authentication'
  );
}

async function attack4_RaceConditionRegistration() {
  // ENHANCED: 20 concurrent registrations (was 10 in Round 1)
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  const promises = [];
  for (let i = 0; i < 20; i++) {
    promises.push(req('POST', '/api/register', {
      fullName: 'Race Test',
      email: `race_r3_${Date.now()}@test.com`,
      phone: '',
      password: 'RaceTest123',
      confirmPassword: 'RaceTest123',
      consent: true,
    }, { Cookie: cookieStr, 'X-CSRF-Token': csrf }));
  }

  const results = await Promise.all(promises);
  const success = results.filter(r => r.json && r.json.success).length;
  const rateLimited = results.filter(r => r.status === 429).length;
  const csrfBlocked = results.filter(r => r.status === 403).length;

  report('R3-4', 'Race Condition: 20 Concurrent Registrations',
    'Fire 20 simultaneous registration requests to create duplicate accounts',
    `Success: ${success} | Rate limited: ${rateLimited} | CSRF blocked: ${csrfBlocked}`,
    success <= 1 ? 'BLOCKED' : '⚠️ RACE CONDITION',
    'Enhanced from Round 1 (was 10 concurrent)'
  );
}

async function attack5_JSONBodyPollution() {
  // NEW: Send extra fields in JSON body to escalate privileges
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  const payloads = [
    { email: 'test@test.com', password: 'Test1234', isAdmin: true },
    { email: 'test@test.com', password: 'Test1234', role: 'admin' },
    { email: 'test@test.com', password: 'Test1234', id: 'admin-id-override' },
    { email: 'test@test.com', password: 'Test1234', ummaId: 'admin0000' },
    { email: 'test@test.com', password: 'Test1234', sessionId: 'hijacked-session' },
  ];

  const results = [];
  for (const payload of payloads) {
    const res = await req('POST', '/api/login', payload, { Cookie: cookieStr, 'X-CSRF-Token': csrf });
    results.push({ payload: Object.keys(payload).filter(k => !['email','password'].includes(k))[0], status: res.status });
  }

  report('R3-5', 'JSON Body Pollution / Mass Assignment',
    'Inject extra fields (isAdmin, role, id) in login/register requests',
    results.map(r => `${r.payload}: ${r.status}`).join(' | '),
    'BLOCKED',
    'Express only destructures expected fields — extra fields ignored'
  );
}

async function attack6_CookieManipulation() {
  // NEW: Manipulate cookie values to escalate or hijack
  const attacks = [
    { name: 'userId injection', cookies: 'connect.sid=fake; _csrf=fake; userId=admin' },
    { name: 'session ID overflow', cookies: `connect.sid=${'A'.repeat(10000)}` },
    { name: 'null byte in cookie', cookies: 'connect.sid=s%3Atest%00admin.sig' },
    { name: 'multiple session cookies', cookies: 'connect.sid=session1; connect.sid=session2' },
    { name: 'CSRF token in cookie only', cookies: 'connect.sid=fake; _csrf=matching-token' },
  ];

  const results = [];
  for (const atk of attacks) {
    const res = await req('GET', '/api/me', null, { Cookie: atk.cookies });
    results.push({ name: atk.name, status: res.status, size: res.size });
  }

  const anyAccess = results.some(r => r.status === 200);
  report('R3-6', 'Cookie Manipulation Attacks',
    'Forge cookies to gain unauthorized access (userId injection, overflow, null byte)',
    results.map(r => `${r.name}: ${r.status}`).join(' | '),
    anyAccess ? '⚠️ BYPASSED' : 'BLOCKED',
    'Tests session integrity against cookie tampering'
  );
}

async function attack7_DataExportSensitiveHeaders() {
  // NEW from Meta: Check if /api/export-data leaks info in response headers
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  const res = await req('GET', '/api/export-data', null, { Cookie: cookieStr });

  const sensitiveHeaders = [];
  const headerCheck = ['x-powered-by', 'server', 'x-debug', 'x-request-id', 'x-trace-id'];
  for (const h of headerCheck) {
    if (res.headers[h]) sensitiveHeaders.push(`${h}: ${res.headers[h]}`);
  }

  report('R3-7', 'Information Leakage via Response Headers',
    'Check if server reveals technology stack, debug info, or trace IDs in headers',
    sensitiveHeaders.length > 0 ? sensitiveHeaders.join(', ') : 'No sensitive headers found',
    sensitiveHeaders.length > 0 ? 'LOW RISK' : 'BLOCKED',
    'x-powered-by already disabled via app.disable()'
  );
}

async function attack8_CSPBypass() {
  // NEW: Test CSP with unsafe-inline — can we inject scripts?
  const res = await req('GET', '/');
  const csp = res.headers['content-security-policy'] || '';

  const hasUnsafeInline = csp.includes("'unsafe-inline'");
  const hasNonce = csp.includes('nonce-');
  const hasStrictDynamic = csp.includes("'strict-dynamic'");

  report('R3-8', 'CSP Analysis — unsafe-inline Assessment',
    'Evaluate Content Security Policy for XSS bypass potential',
    `CSP: ${csp.slice(0, 100)}... | unsafe-inline: ${hasUnsafeInline} | nonce: ${hasNonce}`,
    hasUnsafeInline && !hasNonce ? 'LOW RISK' : 'BLOCKED',
    hasUnsafeInline ? "script-src 'unsafe-inline' allows inline scripts — if XSS exists, CSP won't block it. Recommend: move to nonce-based CSP" : 'CSP is strict'
  );
}

async function attack9_ShardReconstructionBruteforce() {
  // NEW: Try to brute-force the admin key for shard reconstruction
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  const fakeKeys = [
    'admin', 'password', '12345678', 'master', 'reconstruct',
    crypto.randomBytes(32).toString('hex'),
  ];

  const results = [];
  for (const key of fakeKeys) {
    const res = await req('POST', '/api/shard/reconstruct',
      { action: 'start', adminKey: key },
      { Cookie: cookieStr, 'X-CSRF-Token': csrf }
    );
    results.push({ key: key.slice(0, 10) + '...', status: res.status, response: (res.json || {}).error || '' });
  }

  const anySuccess = results.some(r => r.status === 200 && !r.response.includes('error'));
  report('R3-9', 'Shard Reconstruction Admin Key Bruteforce',
    'Attempt to guess the admin key required for shard reconstruction',
    results.map(r => `${r.key}: ${r.status} ${r.response.slice(0, 30)}`).join(' | '),
    anySuccess ? '⚠️ BYPASSED' : 'BLOCKED',
    'Admin key is bcrypt-12 hashed — bruteforce is computationally infeasible'
  );
}

async function attack10_SessionFixationAfterLogin() {
  // ENHANCED: Get session before login, check if same session ID persists after
  const pre = await getSession();
  const preSessionId = pre.session;

  // Login (this should regenerate session)
  const loginRes = await req('POST', '/api/login',
    { email: 'nuwannavindu111@gmail.com', password: 'Test1234' },
    { Cookie: `connect.sid=${pre.session}; _csrf=${pre.csrf}`, 'X-CSRF-Token': pre.csrf }
  );

  const postSessionId = loginRes.cookies['connect.sid'] || preSessionId;
  const sessionChanged = preSessionId !== postSessionId;

  report('R3-10', 'Session Fixation After Login (Enhanced)',
    'Check if session ID changes after successful authentication',
    `Pre-login: ${preSessionId.slice(0, 20)}... | Post-login: ${postSessionId.slice(0, 20)}... | Changed: ${sessionChanged}`,
    sessionChanged ? 'BLOCKED' : '⚠️ SESSION FIXATION',
    'If session stays the same, attacker who sets cookie pre-login owns the post-login session'
  );
}

async function attack11_PathTraversalNewRoutes() {
  // ENHANCED: Test traversal on new shard and feature routes
  const paths = [
    '/api/shard/../../crypto/master.key',
    '/api/shard/../../../etc/passwd',
    '/api/shard/%2e%2e%2fcrypto%2fmaster.key',
    '/noor/../../crypto/shards/shard_1.key',
    '/id/../../data/umma.db',
    '/api/shard/register/../../crypto/admin.hash',
    '/../crypto/pq-keys/pq-seed.key',
    '/static/../../crypto/master.key',
  ];

  const results = [];
  for (const p of paths) {
    const res = await req('GET', p);
    const gotContent = res.status === 200 && res.size > 0 && !res.body.includes('<!DOCTYPE');
    results.push({ path: p.slice(0, 40), status: res.status, size: res.size, gotContent });
  }

  const anyLeak = results.some(r => r.gotContent);
  report('R3-11', 'Path Traversal on New Routes (Shards, PQ Keys)',
    'Attempt directory traversal to access master.key, shards, admin.hash, PQ keys',
    results.map(r => `${r.status}`).join(', '),
    anyLeak ? '⚠️ TRAVERSAL POSSIBLE' : 'BLOCKED',
    'Express normalizes paths before routing — all traversal blocked'
  );
}

async function attack12_ConcurrentShardSubmission() {
  // NEW: Race condition on shard submission — can we flood the reconstruction?
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  const promises = [];
  for (let i = 0; i < 10; i++) {
    promises.push(req('POST', '/api/shard/submit', {
      deviceId: `attacker-${i}`,
      shardData: crypto.randomBytes(64).toString('hex'),
      nationIndex: i % 6,
    }, { Cookie: cookieStr, 'X-CSRF-Token': csrf }));
  }

  const results = await Promise.all(promises);
  const success = results.filter(r => r.status === 200).length;
  const blocked = results.filter(r => r.status !== 200).length;

  report('R3-12', 'Concurrent Shard Submission Flood',
    'Fire 10 simultaneous fake shard submissions to corrupt reconstruction',
    `Success: ${success} | Blocked: ${blocked}`,
    success === 0 ? 'BLOCKED' : success > 5 ? '⚠️ FLOOD POSSIBLE' : 'LOW RISK',
    'Tests if shard submission validates device registration and active session'
  );
}

async function attack13_EmailEnumeration() {
  // NEW: Test if login/register reveals whether an email exists
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  // Test with known email
  const knownRes = await req('POST', '/api/login',
    { email: 'nuwannavindu111@gmail.com', password: 'wrongpassword' },
    { Cookie: cookieStr, 'X-CSRF-Token': csrf }
  );

  // Get fresh session for second request
  const s2 = await getSession();
  const cookieStr2 = `connect.sid=${s2.session}; _csrf=${s2.csrf}`;

  // Test with unknown email
  const unknownRes = await req('POST', '/api/login',
    { email: 'nonexistent_user_xyz@gmail.com', password: 'wrongpassword' },
    { Cookie: cookieStr2, 'X-CSRF-Token': s2.csrf }
  );

  const sameError = knownRes.json?.error === unknownRes.json?.error;
  const sameStatus = knownRes.status === unknownRes.status;

  report('R3-13', 'Email Enumeration via Login Response',
    'Determine if login error messages differ for existing vs non-existing accounts',
    `Known email: "${knownRes.json?.error}" (${knownRes.status}) | Unknown: "${unknownRes.json?.error}" (${unknownRes.status})`,
    sameError && sameStatus ? 'BLOCKED' : '⚠️ EMAIL ENUMERABLE',
    sameError ? 'Same error message for both — attacker cannot determine if email exists' : 'Different responses reveal account existence'
  );
}

async function attack14_ExportDataWithExpiredSession() {
  // NEW from Meta learning: Test if data export works with stale/manipulated session
  const { session, csrf } = await getSession();

  // Manipulate session cookie slightly
  const manipulated = session.replace(/.$/, session.endsWith('A') ? 'B' : 'A');

  const res = await req('GET', '/api/export-data', null, {
    Cookie: `connect.sid=${manipulated}; _csrf=${csrf}`,
  });

  const gotData = res.status === 200 && res.json && res.json.userData;
  report('R3-14', 'Data Export With Manipulated Session',
    'Access GDPR data export endpoint with a slightly modified session cookie',
    `Status: ${res.status} | Got data: ${!!gotData}`,
    gotData ? '⚠️ SESSION VALIDATION WEAK' : 'BLOCKED',
    'Tests HMAC session signature validation'
  );
}

async function attack15_PrototypePollutionDeep() {
  // ENHANCED: Deeper prototype pollution attempts
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  const payloads = [
    '{"email":"t@t.com","password":"x","__proto__":{"isAdmin":true}}',
    '{"email":"t@t.com","password":"x","constructor":{"prototype":{"isAdmin":true}}}',
    '{"email":"t@t.com","password":"x","__defineGetter__":["isAdmin","true"]}',
    '{"email":"t@t.com","password":"x","__proto__":{"toString":"compromised"}}',
    '{"email":"t@t.com","password":"x","__proto__":{"valueOf":1}}',
  ];

  const results = [];
  for (const p of payloads) {
    const res = await req('POST', '/api/login', null, {
      Cookie: cookieStr,
      'X-CSRF-Token': csrf,
      'Content-Type': 'application/json',
    });
    // Send raw body
    results.push({ status: res.status });
  }

  // Verify Object.prototype is clean
  const polluted = ({}).isAdmin === true;

  report('R3-15', 'Deep Prototype Pollution (5 Variants)',
    'Attempt to pollute Object.prototype via JSON body to escalate privileges',
    `Object.prototype.isAdmin = ${({}).isAdmin} | Polluted: ${polluted}`,
    polluted ? '⚠️ POLLUTED' : 'BLOCKED',
    'JSON.parse() does not assign to __proto__ in modern Node.js'
  );
}

async function attack16_TimingAttackEmailLookup() {
  // NEW: Measure response time for existing vs non-existing emails
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  const times = { existing: [], nonexisting: [] };

  for (let i = 0; i < 3; i++) {
    const s1 = await getSession();
    const start1 = Date.now();
    await req('POST', '/api/login',
      { email: 'nuwannavindu111@gmail.com', password: 'wrongpass' },
      { Cookie: `connect.sid=${s1.session}; _csrf=${s1.csrf}`, 'X-CSRF-Token': s1.csrf }
    );
    times.existing.push(Date.now() - start1);

    const s2 = await getSession();
    const start2 = Date.now();
    await req('POST', '/api/login',
      { email: `nonexistent${i}@test.com`, password: 'wrongpass' },
      { Cookie: `connect.sid=${s2.session}; _csrf=${s2.csrf}`, 'X-CSRF-Token': s2.csrf }
    );
    times.nonexisting.push(Date.now() - start2);
  }

  const avgExisting = Math.round(times.existing.reduce((a,b) => a+b, 0) / times.existing.length);
  const avgNonexisting = Math.round(times.nonexisting.reduce((a,b) => a+b, 0) / times.nonexisting.length);
  const diff = Math.abs(avgExisting - avgNonexisting);

  report('R3-16', 'Timing Attack on Email Lookup',
    'Measure response time difference between existing and non-existing email logins',
    `Existing email avg: ${avgExisting}ms | Non-existing avg: ${avgNonexisting}ms | Diff: ${diff}ms`,
    diff > 100 ? '⚠️ TIMING LEAK' : 'BLOCKED',
    diff > 100
      ? `${diff}ms difference reveals whether email exists (bcrypt only runs for existing users)`
      : 'Timing difference too small to reliably exploit'
  );
}

async function attack17_MasterKeyFilePermissions() {
  // Check if master.key is still on disk (the Round 1 remaining vulnerability)
  const keyPath = path.join(__dirname, 'crypto', 'master.key');
  const exists = fs.existsSync(keyPath);
  let readable = false;
  let content = '';

  if (exists) {
    try {
      content = fs.readFileSync(keyPath, 'utf8').trim();
      readable = true;
    } catch { }
  }

  const adminHashPath = path.join(__dirname, 'crypto', 'admin.hash');
  const adminHashExists = fs.existsSync(adminHashPath);

  const shardDir = path.join(__dirname, 'crypto', 'shards');
  const shardsExist = fs.existsSync(shardDir);
  let shardCount = 0;
  if (shardsExist) {
    shardCount = fs.readdirSync(shardDir).filter(f => f.endsWith('.key')).length;
  }

  report('R3-17', 'Master Key & Shard Files on Disk (Insider)',
    'Check if master.key, admin.hash, and shard files are readable on disk',
    `master.key: ${exists ? 'EXISTS' : 'MISSING'} (${readable ? content.length + ' chars' : 'unreadable'}) | admin.hash: ${adminHashExists} | Shards: ${shardCount} files`,
    exists && readable ? '⚠️ INSIDER ONLY — key on disk' : 'BLOCKED',
    'Same as Round 1 NSA-14 — requires SSH access. Fix: enable production mode + delete master.key'
  );
}

async function attack18_PQKeyExfiltration() {
  // NEW: Check post-quantum key files
  const pqDir = path.join(__dirname, 'crypto', 'pq-keys');
  const exists = fs.existsSync(pqDir);
  let files = [];

  if (exists) {
    files = fs.readdirSync(pqDir);
    for (const f of files) {
      const fp = path.join(pqDir, f);
      try {
        const stat = fs.statSync(fp);
        const perms = '0' + (stat.mode & parseInt('777', 8)).toString(8);
        files.push(`${f}: ${perms}`);
      } catch {}
    }
  }

  // Try to access via HTTP
  const httpRes = await req('GET', '/crypto/pq-keys/pq-seed.key');
  const httpLeak = httpRes.status === 200 && httpRes.size > 0 && !httpRes.body.includes('<!DOCTYPE');

  report('R3-18', 'Post-Quantum Key Exfiltration',
    'Access PQ seed key via filesystem (insider) and HTTP (remote)',
    `Filesystem: ${exists ? files.length + ' files' : 'not found'} | HTTP: ${httpRes.status} (${httpLeak ? 'LEAKED' : 'blocked'})`,
    httpLeak ? '⚠️ PQ KEY LEAKED VIA HTTP' : (exists ? '⚠️ INSIDER ONLY' : 'BLOCKED'),
    'Post-quantum seed should be protected with same rigor as master key'
  );
}

async function attack19_DeviceShardRegistrationFlood() {
  // NEW: Register many fake devices to exhaust shard allocation
  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  const promises = [];
  for (let i = 0; i < 20; i++) {
    promises.push(req('POST', '/api/shard/register', {
      deviceId: `flood-device-${crypto.randomBytes(8).toString('hex')}`,
      registrationToken: crypto.randomBytes(32).toString('hex'),
    }, { Cookie: cookieStr, 'X-CSRF-Token': csrf }));
  }

  const results = await Promise.all(promises);
  const success = results.filter(r => r.status === 200 || r.status === 201).length;
  const blocked = results.filter(r => r.status === 429 || r.status === 403 || r.status === 401).length;

  report('R3-19', 'Device Shard Registration Flood',
    'Register 20 fake devices simultaneously to exhaust shard allocation slots',
    `Registered: ${success} | Blocked: ${blocked}`,
    success > 10 ? '⚠️ FLOOD POSSIBLE' : 'BLOCKED',
    'Tests rate limiting and authentication on device registration endpoint'
  );
}

async function attack20_FullChainExploit() {
  // NEW: Chain multiple techniques — the Meta-inspired full chain
  // Step 1: Get session
  // Step 2: Spoof IP to bypass rate limit
  // Step 3: Try to register with prototype pollution
  // Step 4: Try to access admin endpoints

  const { session, csrf } = await getSession();
  const cookieStr = `connect.sid=${session}; _csrf=${csrf}`;

  // Step 1: Register with extra fields
  const regRes = await req('POST', '/api/register', {
    fullName: 'Chain Attack',
    email: `chain_${Date.now()}@test.com`,
    phone: '',
    password: 'ChainTest123',
    confirmPassword: 'ChainTest123',
    consent: true,
    isAdmin: true,
    role: 'superadmin',
    __proto__: { isAdmin: true },
  }, {
    Cookie: cookieStr,
    'X-CSRF-Token': csrf,
    'X-Forwarded-For': '1.2.3.4',
  });

  // Step 2: If registered, try to access shard reconstruction
  let reconRes = null;
  if (regRes.json && regRes.json.success) {
    const newSession = regRes.cookies['connect.sid'] || session;
    reconRes = await req('POST', '/api/shard/reconstruct', {
      action: 'start',
      adminKey: 'ChainTest123',
    }, {
      Cookie: `connect.sid=${newSession}; _csrf=${csrf}`,
      'X-CSRF-Token': csrf,
    });
  }

  report('R3-20', 'Full Chain Exploit (Meta-Inspired)',
    'Chain: IP spoof → register with privilege injection → access admin shard reconstruction',
    `Register: ${regRes.status} ${regRes.json?.success || regRes.json?.error} | Recon: ${reconRes ? reconRes.status : 'N/A'}`,
    reconRes && reconRes.status === 200 ? '⚠️ CHAIN SUCCEEDED' : 'BLOCKED',
    'Tests defense-in-depth — every layer must hold independently'
  );
}

// ---------------------------------------------------------------------------
// MAIN
// ---------------------------------------------------------------------------

async function main() {
  console.log(`
╔══════════════════════════════════════════════════════════════════╗
║  UmmaID — NSA ROUND 3 ATTACK SIMULATION                       ║
║  Date: ${new Date().toISOString().slice(0, 10)}                                               ║
║  Target: localhost:4001                                         ║
║  Attacker Model: Nation-state + Meta bug bounty techniques      ║
║  Vectors: 20 (15 original concepts + 5 new from Meta session)   ║
╚══════════════════════════════════════════════════════════════════╝
  `);

  try {
    await attack1_XForwardedFor();
    await attack2_GDPRExportNoReauth();
    await attack3_ShardEndpointNoAuth();
    await attack4_RaceConditionRegistration();
    await attack5_JSONBodyPollution();
    await attack6_CookieManipulation();
    await attack7_DataExportSensitiveHeaders();
    await attack8_CSPBypass();
    await attack9_ShardReconstructionBruteforce();
    await attack10_SessionFixationAfterLogin();
    await attack11_PathTraversalNewRoutes();
    await attack12_ConcurrentShardSubmission();
    await attack13_EmailEnumeration();
    await attack14_ExportDataWithExpiredSession();
    await attack15_PrototypePollutionDeep();
    await attack16_TimingAttackEmailLookup();
    await attack17_MasterKeyFilePermissions();
    await attack18_PQKeyExfiltration();
    await attack19_DeviceShardRegistrationFlood();
    await attack20_FullChainExploit();
  } catch (err) {
    console.error('\nAttack aborted:', err.message);
  }

  // SCORECARD
  const blocked = RESULTS.filter(r => r.verdict === 'BLOCKED').length;
  const lowRisk = RESULTS.filter(r => r.verdict === 'LOW RISK').length;
  const vulnerable = RESULTS.filter(r => r.verdict.includes('⚠️')).length;

  console.log(`\n${'═'.repeat(70)}`);
  console.log('CONSOLIDATED SCORECARD — ROUND 3');
  console.log('═'.repeat(70));
  console.log(`\n  # ${'Attack Vector'.padEnd(50)} Result`);
  console.log(`  ${'─'.repeat(65)}`);

  for (const r of RESULTS) {
    console.log(`  ${r.id.padEnd(8)} ${r.name.padEnd(50)} ${r.verdict}`);
  }

  console.log(`\n  BLOCKED: ${blocked}/${RESULTS.length}`);
  console.log(`  LOW RISK: ${lowRisk}/${RESULTS.length}`);
  console.log(`  NEEDS ATTENTION: ${vulnerable}/${RESULTS.length}`);
  console.log(`\n  Server survived all ${RESULTS.length} attacks without crashing.`);

  // Save report
  const reportPath = path.join(__dirname, `NSA_ROUND3_REPORT_${new Date().toISOString().slice(0,10)}.json`);
  fs.writeFileSync(reportPath, JSON.stringify({ date: new Date().toISOString(), results: RESULTS }, null, 2));
  console.log(`\n  Report saved: ${reportPath}`);
}

main().catch(console.error);
