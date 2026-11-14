# Security policy

## Supported versions

Only the latest release on the default branch receives security fixes. Older tags are not patched.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability.

1. Open the repository's **Security** tab and choose **Report a vulnerability** (GitHub private vulnerability reporting).
2. Include the affected version or commit, the impact, and the steps to reproduce.
3. Do not include real personal data or live credentials in the report.

## What to expect

| Step | Target |
|---|---|
| Acknowledgement | within 5 days |
| Triage and severity (CVSS) | within 10 days |
| Fix or mitigation for KEV, actively exploited or critical issues | 7 days or less |
| Fix for high issues | 30 days |
| Public advisory and credit (if wanted) | after the fix is released |

Secrets that reach the repository are rotated first and removed from history only after rotation.

## Scope

In scope: the code in this repository, its build and release workflows, and its published artifacts.
Out of scope: third-party services the project integrates with, social engineering, and denial of service by volume.
