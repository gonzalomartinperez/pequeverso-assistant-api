# PostgreSQL Alpine candidate — 2026-10-18

Status: source implementation and isolated mock checks only. No image build, real database,
security scan, deployment or production acceptance has been performed for this candidate.
Previous dated Debian measurements keep their original source and image identities.

## Reason and provenance

The current Debian image includes
`libxml2 2.12.7+dfsg+really2.9.14-2.1+deb13u3`. The
[Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-6653) identifies that version
as vulnerable to CVE-2026-6653 and records the upstream fix in2.11.0. Debian's `really2.9.14`
version must not be mistaken for the later upstream2.12 code. Its minor/no-DSA assessment does
not cancel the prior scanner's NVD9.8/critical result or authorize deployment.

The official Alpine3.24 main package is
[libxml2 2.13.9-r2](https://pkgs.alpinelinux.org/packages?arch=x86_64&branch=v3.24&name=libxml2).
Its [security database](https://secdb.alpinelinux.org/v3.24/main.json) also records the
CVE-2026-6732 fix at that revision. This is a plausible compatible way to remove the affected
old upstream code while retaining XML; it is not evidence of a clean exact-image scan.

Primary metadata checked on2026-10-18:

- Official `postgres:18.6-alpine3.24` OCI index:
  `sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873`.
  The linux/amd64 child is
  `sha256:d8703cd7fba306b9fec9268ecedfa8a966846c053036a60e3635791957eb2f66`.
- [Upstream Docker recipe](https://github.com/docker-library/postgres/blob/master/18/alpine3.24/Dockerfile):
  OS user/group70, PostgreSQL18.6, `/var/lib/postgresql/18/docker`, parent volume
  `/var/lib/postgresql`, XML/ICU and SIGINT retained. The derived project image declares
  `USER 70:70`; the upstream image itself defaults to root initialization.
- [pgvector0.8.7 upstream](https://github.com/pgvector/pgvector/tree/v0.8.7) archive SHA256:
  `cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85`.
  [Its security release](https://www.postgresql.org/about/news/pgvector-087-released-3392/)
  fixes CVE-2026-103484; this change does not downgrade the extension.
- Official Alpine main/x86_64 package index confirms `build-base=0.5-r4`,
  `clang21=21.1.8-r3`, `llvm21-dev=21.1.8-r1` and `libxml2=2.13.9-r2`.
  APK verifies repository/package signatures during the future build. HTTPS metadata and
  checksums alone do not claim that a build already verified them.
- [Alpine support policy](https://www.alpinelinux.org/releases/): main support until2028-06-01;
  no invented LTS label. Compiler packages belong only to the build stage. The runtime package
  inventory and pgvector notices remain in the final image.

Portfolio API commit `f77c8d878401cc2a5bcea63716396b4bbcc1fc18` was inspected through
`git show` as a build-pattern reference. Pequeverso preserves its own image identity, SQL,
capability groups, INHERIT memberships, privacy command and health check; no Portfolio bootstrap,
roles, database names, deployment settings or HBA configuration are copied.

## Deterministic regression and limits

An initial execution of the actual PostgreSQL shell smoke with a fake Docker executable showed
that it always dispatched `--user 999:999`, even when image metadata declared70 or root.
The fake exits before starting a container. The original three-test run retained seven failing
assertions; this demonstrates a harness identity gap, not an observed privileged database run.

A shared standard-library identity validator now permits only exact `70:70` and historical
`999:999`. Both smokes use the validated user for `--user` and socket tmpfs ownership, and refuse
invalid metadata before creating a network, volume or container. Mock regression checks cover
both supported pairs, root/empty/malformed values, bounded CLI input, no rejected-value echo,
read-only root and preserved no-new-privileges flags. Mock tests do not validate Alpine binaries,
actual volumes, SQL authorization, database recovery or memory usage.

## Gates before acceptance

1. Build the exact committed image after a fresh coordinated lease. Verify UID/GID70, project
   and extension notice bytes, retained XML/ICU, pgvector0.8.7, no compiler toolchain in the final
   stage, read-only root, cap-drop/no-new-privileges and existing resource limits.
2. On new owned volumes only, execute the PostgreSQL role/index/private-state tests, logging
   privacy probes, TCP temporary-init-server barrier, dump/restore/restart and graceful stop.
3. Transfer synthetic Debian18.6 data by
   [logical dump/restore](https://www.postgresql.org/docs/18/backup-dump.html) into a fresh Alpine
   cluster. Preserve private message/session/accounting rows and unknown reservations; compare
   complete row hashes and restore roles/grants explicitly. Never use production data here.
4. Verify UTF-8, accents/case handling, lexical search, exact vector distance and XML/ICU behavior.
   [Collation behavior depends on the provider and platform](https://www.postgresql.org/docs/18/sql-createcollation.html).
   Rebuilding indexes is necessary; refreshing a collation version alone is not a compatibility proof.
5. Exercise the existing real HTTP/SSE fixture and offline index cold/reuse jobs with distinct
   non-owner capabilities. All providers remain fixtures, with no paid SDK calls or real keys.
   Revalidate the separate backoffice IAM database before accepting the common project engine.
6. Generate a fresh exact-image SBOM and scan using current verified vulnerability data; retain
   original results, compare critical/high/fixable findings and report actual byte sizes. No
   suppression, waiver or promised space/performance saving is part of this source change.
7. Run required repository checks, contracts and image smoke, obtain independent review and pass
   protected CI before integration. vps-ops owns any later deployment decision and restore plan.
