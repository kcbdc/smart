# v6 Security / Integration Acceptance Report

| Domain | Implemented / testable in this build | Not yet established |
|---|---|---|
| OIDC SSO | Code+PKCE, state/nonce, JWKS signature, issuer, audience, exp validation, roles | Live IdP keys, logout propagation, issuer-specific claim calibration |
| MFA | Fail closed if `amr`/approved `acr` does not confirm MFA | Real IdP MFA enrollment/challenge tests, step-up |
| HTTPS | Nginx TLS example, localhost-bound backend, forwarded HTTPS check, Secure cookie, HSTS | Certificate issuance, production firewall/WAF/renewals |
| Sessions & CSRF | SHA-256 DB token hashes, idle/absolute limits, token revocation, CSRF header | Enterprise multi-node session management and SOC alerts |
| Attendance | Effective versioned rules, immutable policy version per session, recognition uses DB | Real regulation approved, human watch verification, exceptions and appeal workflow |
| SIS | Signed HMAC webhook, freshness/idempotency, student and enrollment mapping, outbound queue | University SIS handshake, bidirectional reconciliation and production schema |
| Security review | Unit + HTTP regression tests and basic browser rendering | Pen test, complete ASVS audit, load/DR/backup test, privacy approval |

**Decision:** Ready for *controlled integration/UAT in an isolated environment*, **not approved for public production**.

Recommended benchmark: OWASP ASVS v5.0.0, TLS configuration per institutional information security policy. Secrets must live outside source code. The mock campus name/data and sample users are synthetic.
