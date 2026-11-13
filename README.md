# SMART CYBER UNIVERSITY — Campus OS v6

**Status: integration/security verification build, NOT authorized for live institutional records or public launch.**

v5 visual system and role-based LMS workflows have been retained. v6 introduces infrastructure-ready components and testable integration contracts for OIDC SSO, MFA assurance, HTTPS deployment, attendance-policy versioning, SIS signed webhooks/outbox, CSRF/session protections, and regression testing.

## 1. Run local demonstration

Python 3.11+:

```bash
python server.py
```

Open `http://127.0.0.1:8765`. Only in `SCU_MODE=demo`: student/student123!, professor/professor123!, admin/admin123!. All demo credentials, course data, academic status, and video are synthetic. **Never run demo mode publicly.**

```bash
python -m unittest test_v5 test_v6 -v
```

## 2. SSO / MFA: configured enterprise IdP required

Production requires an institution-owned OIDC Identity Provider using *authorization code + PKCE S256*. `/auth/start` initiates an OIDC login; `/auth/callback` validates a one-use, browser-bound state, nonce, issuer, audience, signature via JWKS, token expiry, authorized campus role, and IdP MFA assertion (`amr` or campus-approved `acr`). Missing/weak MFA assurance is rejected; no local fallback login exists in production. Allowed role claim values: `student`, `professor`, `admin`. `iss|sub` is the internal immutable identity; SIS should map this identifier to a student identifier rather than rely on a display name.

Install requirements and configure a secure reverse proxy as in deployment files:

```bash
python -m pip install -r requirements-production.txt
# Export production.env.example values through secret manager; do not execute placeholder config.
python server.py
```

The server only binds `127.0.0.1`. Direct HTTP in production is denied, and requests must arrive through the trusted localhost TLS terminator setting `X-Forwarded-Proto: https`. **Production fails at startup** without HTTPS public URL, IdP issuer/client ID, explicit proxy trust flag, persistent CSRF secret, and runtime auth dependencies. Proxy sample is not a substitute for infrastructure penetration testing or certificate issuance.

The sample is a single-machine Python stdlib server + SQLite. For multi-node or large-enrollment operation, replace this service and DB with hardened app server, shared session store, managed HA database, queue processing, observability and backups.

## 3. Session and request security

- Random 256-bit login tokens stored as SHA-256 digests in SQLite (not plaintext); logout revokes DB session.
- Session absolute expiry 4 hours, inactivity expiry 30 minutes.
- Production `__Host-` Secure HttpOnly SameSite=Lax cookie, HSTS and response protections.
- CSRF token from `/api/me` or login, sent by browser as `X-CSRF-Token` for state-changing APIs. SIS webhook uses independent HMAC signature/timestamp instead.
- Local password login disabled in production. Demo password auth remains strictly local and for testing only.
- OIDC MFA verification depends on actual institution IdP's documented `amr` / `acr` semantics; must be tested against live test users, including MFA failure cases.
- **Known gaps:** no enterprise user lifecycle / SCIM deprovisioning, central secret rotation, enterprise SOC logging, tamper-evident audit storage, IP-level network rate limits for all endpoints, complete WebAuthn step-up, or security certification. No production claim should be inferred.

## 4. Attendance standards: per-term and per-course policy

`attendance_policies` stores term, course or `*`, rule JSON, version, effective time, approver. In demo a synthetic `DEMO-1` policy permits 12/15 seconds and 80% threshold. Production does **not** seed any attendance rules. Requests to start a lesson without an approved policy are rejected. Rule is snapshotted at the beginning of a video session to avoid retroactive silent changes, and recognized attendance stores a policy version.

Authorized admin can publish a policy via `POST /api/v6/policy`:

```json
{"term":"2026-2","course":"AI101","version":"REG-2026-2-01","rule":{"min_watch_ratio":0.9,"min_watch_seconds":14,"require_ended":true,"heartbeat_grace_seconds":0.5,"max_speed":1.0}}
```

Rules are **examples only**, not an interpretation of a real university's academic regulations. Real policy review must address lesson lengths, make-up classes, exceptions, holidays, accessibility accommodations, clock accuracy, appeal/override auditing, and the legal basis for tracking. Browser video-heartbeat evidence cannot conclusively establish a human watched the lecture, so official attendance requires additional anti-abuse controls and/or institutional acceptance.

## 5. SIS integration contract (NOT a live SIS integration)

`POST /api/sis/webhook`: independent signed payload `X-SIS-Timestamp` (Unix seconds) and `X-SIS-Signature: sha256=<hex>` where HMAC-SHA256 covers `timestamp + '.' + raw_body`. Rejects replayed timestamps more than 5 minutes away, changes to duplicate event IDs, unauthorized signatures, invalid terms/rosters. Event examples:

```json
{"event_id":"evt-2026-0001","event_type":"student.upsert","data":{"subject":"https://sso.example.edu/realms/campus|123","student_id":"S123456","program":"ICT","standing":"enrolled"}}
```
```json
{"event_id":"evt-2026-0002","event_type":"enrollment.upsert","data":{"subject":"https://sso.example.edu/realms/campus|123","student_id":"S123456","term":"2026-2","course":"AI101","enrolled":true}}
```

Event types: `student.upsert`, `student.status`, `enrollment.upsert`. SIS is authoritative for student roster and standing in the intended deployment. This pilot accepts only demonstration term `2026-2` and currently configured courses; real schema and mapping will need to be agreed with university SIS owners. Administrator academic decisions are saved to `sis_outbox` for reliable delivery, **not applied to an authoritative SIS until the SIS confirms them**. `python sis_worker.py` attempts signed HTTPS delivery to preconfigured endpoint. Production needs a scheduled worker, retry/dead-letter policy, acknowledgments, and reconciliation dashboard. Never use demonstration identifiers as real student data.

## 6. Security acceptance tasks before any public launch

1. Obtain and test actual IdP discovery URL, MFA claims, authorization scopes, logout/deprovisioning, and role-assignment governance.
2. Issue valid public TLS certificates and verify end-to-end HTTPS, proxy restrictions, HSTS and certificate renewal.
3. Receive signed regulator/institution-approved attendance policy and perform exception/appeal tests.
4. Sign and test SIS API schema with owners: enrollment changes, student status, idempotency, retries, errors and reconciliation.
5. Independent penetration testing and OWASP ASVS-based review (authorization/IDOR, CSRF, XSS, SSRF, injection, replay, rate limiting), data protection impact review, backups/restores, disaster recovery, load tests.
6. Replace demonstration runtime before scale; log operational events to tamper-resistant centralized logging; secure PII and retention rules.

## 7. Source map

- `server.py`: API gateway/auth routing and role checks
- `security.py`: OIDC verification, session/cookie/CSRF safeguards
- `attendance_rules.py` + `academic.py`: versioned attendance and video session evidence
- `sis.py`, `sis_worker.py`: signed inbound SIS updates and outbound retry queue
- `operations.py`: professor content and admin workflows
- `deployment/nginx.example.conf`, `deployment/production.env.example`: TLS and IdP provisioning templates
- `test_v5.py`, `test_v6.py`: functional and security regression tests
- `assets/`: original v5 responsive UI and training video

### Important operational note

This is a working reference implementation with explicit external integration boundaries. It is **not yet a compliant, accredited, secure production university platform**: the institutional IdP, SIS, privacy/records policies, and hosting infrastructure must be jointly configured and validated by university operators.
