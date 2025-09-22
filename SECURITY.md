# Security Policy

We want AGILAB to be safe for every team that experiments with it. This page explains how to
report issues and what you can expect from us when you do.

## Supported Versions

| Version / Branch | Supported |
|------------------|-----------|
| `main` (development head) | ✅ |
| Tagged releases older than 6 months | ⚠️ Fixes are best-effort |
| 1.0 and earlier | ❌ |

Security fixes are released on a rolling basis. If a vulnerability affects an unsupported version,
please upgrade to the latest release before requesting a patch.

## Reporting a Vulnerability

- Email **focus@thalesgroup.com** with the subject line **`[SECURITY] <short summary>`**.
- Include:
  - Steps to reproduce, impacted components, and any proof-of-concept material.
  - Which environments are affected (development install, packaged release, etc.).
  - A preferred way to reach you for follow-up questions.
- Do **not** attach detailed exploits directly to the email. If you require an encrypted channel,
  request a Cryptobox link in your message and we will provision it promptly.

We will acknowledge receipt within **two business days**. If you do not hear back, please resend your
message or reach out through your usual Thales representative.

## Coordinated Disclosure

1. We confirm the report and work with you to understand the impact.
2. A remediation plan is drafted. You will receive an estimated timeline (typically under 30 days
   for high-severity issues).
3. Fixes are released and security notes are published. We credit the reporter unless you request
   otherwise.

We appreciate coordinated disclosure and will keep you updated throughout the process.

## Security Updates

- Critical patches are released as soon as they are ready.
- Other fixes may be bundled into the next scheduled monthly update.
- Release notes highlight CVE identifiers or internal tracking IDs where applicable.

## Hardening Checklist

While AGILAB is open source, production-grade cluster deployments should be designed with your
organization's security requirements in mind. At minimum:

- Run behind HTTPS and limit inbound network access to trusted operators.
- Store API keys, model weights, and datasets outside of the repository, using a dedicated secrets
  manager where possible.
- Rotate credentials regularly and prefer short-lived access tokens to static passwords.
- Monitor and log execution environments; disable unused Streamlit pages or demo apps in shared
  environments.

For end-to-end secure deployments or bespoke threat modelling, please engage your Thales security
contact or submit a request via <https://cpl.thalesgroup.com/fr/contact-us>.

Thanks for helping us keep AGILAB and its community secure.
