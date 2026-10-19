# Native image handoff · 2026-10-19

These are local, exact-source acceptance records, not published images, VPS deployment,
activation approval or a final-release claim. Documentation source
`850e78cf84df78f0ea66e2811e92aeb15a6f5d04` has byte-identical application, recipes and locks
to API `121d3dc`; that equality does not change the source identity of an existing image.
No new install, test, build, scan, service or provider call was performed for this document.

## Exact images and smoke scopes

| Local artifact | API · wrapperV8 | Backoffice · absolute-source wrapperV9 |
| --- | --- | --- |
| Source revision | `121d3dc5a04d6c12908eb96b6f891f9ff62e2cb0` | `4a77ae008735f5a9439acb768251bd67d94461ee` |
| Source tree | `c83a3b685b3bc343217904ac652e2b2a05bd3d8a` | `82ab501219d85fcff10adceb959697bf087f7ca7` |
| OCI manifest digest / local IID | `sha256:231e5a4c5d311019de746bbe886586866ebce4221c4e45f4068080875bb066ae` | `sha256:92b12770295e8330d0f5101cc739a6dd3b7971e3a50a5bf51aeebc1911bebe58` |
| OCI config digest | `sha256:9975be7362e6b86363499d597773a7c29659b365c4c9724ef2805bae1380d26b` | `sha256:f317da5c631f9f3c60b2eeb181e3e6e1be74c2b7d88ec5c6135fadb896f192c2` |
| Start → finish UTC, October19 | 02:56:05.146726 → 02:56:55.825039 | 03:07:25.341738 → 03:07:51.189744 |
| Build / smoke seconds | 5.820 / 35.715 | 6.437 / 15.495 |
| Runtime | Python3.14.8, UID65532, read-only root | Node24.22.0, Next16.4.2, React19.3.1, UID65532, read-only root |
| Recorded cgroup limits | CPU1/core0, 256MiB, pids64 | CPU1/core0, 384MiB, pids128 |

Both receipts report PASS before their deadlines and verified closure of owned processes,
ports and fixture resources. The owned builder was stopped with core0 affinity retained;
restoration of its original empty affinity is not claimed. API payload validation matched all
107 expected runtime files, importability and legal notices. Backoffice also checked legal
bytes and runtime identity. Local timings are not production latency or capacity measurements.

The API smoke used isolated SQLite and fixture HTTP/SSE; it does not prove production
PostgreSQL/GraphRAG, analytics, OAuth or public proxy behavior. The backoffice smoke used a
synthetic bootstrap PostgreSQL connection, not a production-runtime-role or OAuth session.
Earlier API wrapperV7 TIME_WAIT cleanup failure and backoffice relative-source build failure
remain failures; these later receipts do not rewrite them.

## Complete findings and SBOMs

The separate Trivy0.76.0 run started at03:24:02.543872Z and finished at03:24:30.379193Z
(27.835321s), before admission stop03:27:01.963931Z and final deadline03:28:01.963931Z.
It reused verified cached OS database metadata updated2026-10-18T13:11:41.355239553Z
(next update2026-10-19T13:11:41.355239192Z) and Java metadata updated
2026-10-18T00:58:00.305003613Z (next update2026-10-21T00:58:00.305003002Z).
No fresh database download or timeless freshness claim is made.

| Image | Critical | High | Medium | Low | Unknown | Total rows / unique advisories |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| API121 | 0 | 44 | 58 | 61 | 1 | 164 / 71 |
| BO4a77 | 0 | 0 | 23 | 8 | 0 | 31 / 25 |

The API UNKNOWN row is CVE-2026-82560 in perl-base5.40.1-6+deb13u1; UNKNOWN is retained,
not treated as a clean result. Neither image reports a FixedVersion row in this database;
that does not establish that no compatible fix exists. Every severity and finding remains.
Exit2 denotes completed analysis with advisory findings; the raw zero-finding gate remains
`BLOCKED_OR_INCOMPLETE`. Current owner policy treats CVEs as visible deployment advisories,
not an automatic release blocker. This is neither zero-CVE acceptance nor a suppression or
waiver of health, integrity, secrets, privacy, restore or deployment gates. Earlier dated
reports retain the stricter policy and findings applicable at their original cut.

API inventory contains87 OS and63 Python package PURLs; BO contains14 OS and41 Node package
PURLs. CycloneDX1.7 preserves all150/55 package PURLs, all71/25 unique advisories and all164/31
affected-package/advisory pairs respectively (151/56 components including OS metadata).
The conversion warning means conversion performs no additional scan; the findings were
matched against the full original vulnerability JSON. Third-party SBOM accuracy, Python
license metadata and vendor-severity warnings remain visible. There were no unresolved scan
execution errors or missing declared result sets. This is not proof of exhaustive discovery
of vendored, native or transitive components.

Each of four scanner/conversion containers used core2, CPU1, hard1GiB memory/swap, pids128,
UID1000, read-only root, networknone, dropped capabilities and no-new-privileges, without a
Docker socket. All four exited0 without OOM, were removed, and all39 owned CLI groups drained;
saved final readbacks show zero owned containers/processes. RAM emergency containment was
not exercised in this successful run; its separate fault tests must not be presented as an
actual ENOSPC incident handled here.

Saved-archive verification bound OCI manifests, config digests and every ordered layer to the
Docker legacy layer graph; scanner ImageID/ArtifactID denotes the **config**, not the manifest
IID above. Docker29 rawSize (API78,554,762; BO71,344,503 bytes), saved tar size (78,571,520;
71,376,896) and Trivy Metadata.Size (258,512,896;209,802,240) are different recorded fields,
not interchangeable download, disk-reclamation or memory measurements.

## Evidence custody and hashes

The retained evidence set is `container-security/final121-4a77-actual-v2` in the continuation
report archive. No private paths, credentials, answers or database dumps are included here.
The artifact manifest covers89 original runtime artifacts, including both saved image tars,
all39 CLI stdout/stderr pairs, identities, full vulnerability JSON, SBOMs, ownership and empty
ignore file. Audit outputs are explicitly excluded. Earlier audit metadata, including its
self-inventory error, remains retained; V2 is the authoritative artifact inventory.

| Artifact | SHA256 |
| --- | --- |
| API V8 smoke receipt | `84b58a2c571c7c1b15422aa952b921f059612440c5d511b2e06e0e65eff8ce3b` |
| BO absoluteV9 smoke receipt | `5b2ca5e938a3a4362102b5c321f9263859513eeb0c63b7d6f69c16e2ba7569ad` |
| Scan RUN-RECEIPT.json | `20090d5ebb2b1b53573fc7d505a1b6c638b8bd4a646350871894998731828de4` |
| API full vulnerability JSON | `180aba20f7bffcf3082ee6239dea2be9cb289f84c9a75e46c040fe252e7dd917` |
| BO full vulnerability JSON | `90721ee67866a7c36beade50895674d3288ac63872a649beb974a09e599e506d` |
| API CycloneDX SBOM | `66e09cb6f023be9cc27bd710b3f65acff328e19d418b8e4dc68f63bf45331fc8` |
| BO CycloneDX SBOM | `6ba8d6fbe5cb2e078dfd09b0da0654614e86217ebbfea72401b28b8eacf425aa` |
| INDEPENDENT-ARTIFACT-HASHES-V2.json | `478d049772bb632e2e290ff38efeac81c90f6105416772cf4f1567609f754f2e` |
| INDEPENDENT-READONLY-AUDIT-V2.json | `36e2894de08fd2af8dd33d8a8f9a4512cef21affc439831206477164d258b9e8` |

The read-only agent audit is independent of Root's scan operation, not human review and not
independent of prior authorship of scanner helpers. It did not run new scans or services.

## Remaining acceptance boundaries

[October18 PG/Neo evidence](postgres-alpine-2026-10-18.md) retains exact patched PostgreSQL
`sha256:df480978a6e0294fca333996ad51874b72afebffdf458a89dc5c260f383d9a9e`
and Neo4j historical scan/runtime scopes. PG's UID70:70 requires new volumes and logical
transfer from historical999:999 clusters; never chown or attach a shared physical cluster.
The [three-test analytics restore](api-evidence-2026-10-18.md) covers its original nonempty
fixture, not a restore of migration006. **Migration006 restore remains pending.**
Neo server effective usage-reporting assertions and driver retry/telemetry configuration are
distinct evidence scopes; source flags alone are not proof of an executing server setting.

Native API→PG→BO pairs V17 and V18 failed the browser response-completion check; their
original failures are preserved. These image receipts establish no paired-browser acceptance,
new gallery, live OAuth, external TLS/proxy, VPS capacity or activation. Subsequent integration
evidence must identify its own immutable sources and actual result.
Optional [analytics and country trust](../product-analytics.md) remain OFF by default, with
independent operator edge proof required. Published frontend assistant builds stay OFF.

Use the existing [clean-checkout fixture commands](../../README.md#quick-start-clean-checkout-no-credentials),
[verification commands](../../README.md#verify), [operator jobs and capability roles](../knowledge-operations.md)
and [vps-ops handoff](../handoffs/vps-ops.md). Those instructions are not a new execution,
publishing, deployment or paid-call authorization.
