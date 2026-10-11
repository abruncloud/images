# PostgreSQL 18 initial publication scan

Investigation date: 2026-10-11. The [initial publication run](https://github.com/abruncloud/images/actions/runs/38126322750) passed native runtime and backup/recovery qualification but failed the strict HIGH/CRITICAL vulnerability gate. Public version aliases were not promoted. This document records investigation evidence, not a vulnerability exception or a claim that the images are safe to publish.

## Observed findings

The run used PostgreSQL 18.6, pgvector 0.8.7, Debian trixie and Alpine 3.24 official PostgreSQL bases. The installed Debian libxml2 version reported by Trivy was `2.12.7+dfsg+really2.9.14-2.1+deb13u3`. The inherited `/usr/local/bin/gosu` binary carried Go standard-library build metadata for `v1.24.6`.

| Target | OS package findings | gosu Go findings |
| --- | --- | --- |
| Debian trixie | 64: 63 HIGH, 1 CRITICAL | 25: 24 HIGH, 1 CRITICAL |
| Alpine 3.24 | 0 HIGH/CRITICAL | 25: 24 HIGH, 1 CRITICAL |

These are scanner finding counts, **not counts of unique CVE identifiers**. One CVE can be repeated across packages from the same source package. Both native architectures reported these category totals. Zero Alpine OS findings means zero findings at this severity filter in this run, not absence of every possible vulnerability.

## gosu: investigate actual functionality

The [gosu security policy](https://github.com/tianon/gosu/blob/master/SECURITY.md) explains that compiler-version CVEs in interfaces the utility never invokes can be false positives, and requests verification with its `govulncheck-with-excludes.sh` wrapper. Its [source-level checker](https://github.com/tianon/gosu/blob/master/govulncheck-with-excludes.sh) is a starting point for investigating the exact pinned source and binary.

The scanner's critical example, CVE-2025-68121, concerns TLS certificate validation; gosu primarily changes user identity and executes another command. That observation and the upstream policy do **not** establish that all 25 findings are unreachable. Any exception must identify individual CVEs, the exact artifact/source, checked code paths, upstream exclusions, reviewer and expiry.

A practical mitigation is rebuilding the pinned gosu source and locked dependencies with a current security-patched Go compiler in an isolated build stage, then testing privilege dropping and the complete inherited PostgreSQL entrypoint on both architectures. Rescan the resulting binary rather than assuming the rebuild fixes every finding. The backup entrypoint does not invoke gosu, so removing that unused inherited executable from backup artifacts is another candidate reduction, subject to the documented backup contract and tests.

## Debian libxml2: an active database dependency

The [Debian CVE-2026-6653 tracker](https://security-tracker.debian.org/tracker/CVE-2026-6653) describes a use-after-free in internal-subset parsing and still marks the installed trixie package vulnerable. Debian classifies its trixie handling as a minor issue/no-DSA, whereas the scan assigns CRITICAL. This is a severity disagreement requiring review, not evidence that the vulnerable code is absent.

The [Debian CVE-2026-86138 tracker](https://security-tracker.debian.org/tracker/CVE-2026-86138) describes integer overflow and heap-buffer corruption in `xmlDictAddQString`. Its fixed source version is `2.15.4+dfsg-1` in unstable; the tracker still lists trixie's installed package as vulnerable. Switching from trixie to bookworm does not solve these findings: the cited trackers also list the current bookworm package as vulnerable.

[PostgreSQL 18 XML implementation](https://github.com/postgres/postgres/blob/REL_18_STABLE/src/backend/utils/adt/xml.c) routes SQL XML input into libxml2. The document path calls `xmlCtxtReadDoc` with `XML_PARSE_NOENT` and `XML_PARSE_DTDATTR`, and input containing a DOCTYPE can enter that path. PostgreSQL installs `xmlPgEntityLoader` to block external URL/file entity fetches. That mitigation can matter for specific external-resource attacks, but does not justify ignoring internal parser memory-corruption findings. Exact exploitability of each CVE has not been demonstrated by this investigation; the active input path is enough to reject a blanket “unused library” exception.

The [Python-binding CVE-2026-74860 tracker](https://security-tracker.debian.org/tracker/CVE-2026-74860) is a separate case: absence of the affected binding artifact and its invocation could justify an individual not-affected conclusion after artifact inspection. It does not justify excluding all libxml2 findings.

## Mitigation priority

1. Preserve failed scans and prevent public alias promotion. Generate machine-readable scan reports so each artifact, package, severity and advisory can be reviewed without relying on console tables.
2. Fix or individually assess gosu findings first; this is the common Alpine/Debian blocker and has a small, testable source surface. Independently qualify each distribution after its own complete architecture matrix passes; a blocked Debian release must not be presented as published or clean.
3. Rebuild against available updates from the same supported Debian repositories and rescan. The cited libxml2 trackers show that a normal trixie package update alone does not currently establish a fix for these two CVEs.
4. Remove genuinely unnecessary runtime tools where doing so preserves documented initialization and user-script behavior. Assess source-package findings against actual installed binaries; for example a library package finding about systemd-homed does not prove the systemd-homed executable is installed. Keep this evidence specific and reviewable.
5. For remaining active libxml2 findings, wait for a supported fixed package/base, or maintain a narrowly scoped source backport of the required patches to the exact Debian library with recorded sources, patches, ABI verification, XML regression tests and rescanning. A custom patched package may still require precise VEX evidence until vulnerability feeds recognize it; do not disguise its version to silence detection.
6. Rebuilding PostgreSQL without XML would change the public feature contract and requires separate design and qualification. Replacing its libxml2 with a newer incompatible ABI can also require rebuilding PostgreSQL and dependants. Do not mix unstable packages into the stable runtime or casually copy a newer library over the existing one.

Publication remains blocked until the selected mitigation is implemented and the configured gate passes, or precisely evidenced, expiring exceptions are reviewed under an explicit policy. Blanket ignores and hiding unfixed vulnerabilities are not mitigation.
