# Approved actionable release policy

The user approved this actionable policy on 2026-10-11, including deferred unfixed HIGH findings and the exact expiring Debian CRITICAL assessment below. This branch implements that approved policy; publication and daily rescans select it when merged. The standalone gate remains strict unless invoked with `--policy images/postgres/security-policy.json`.

## Release gate

- Block every HIGH finding with an available fixed version.
- Block every CRITICAL finding unless an exact, documented vendor assessment applies and no fix is available.
- Retain and summarize unfixed HIGH findings as deferred risk. This deliberately accepts their presence; it does not label them false positives or safe.
- Fail closed on missing/malformed reports and policy data. Match critical assessments to CVE, operating-system family/major, package and installed version; require source, reason, owner and expiry.
- Ignore an expired or mismatched assessment. A fixed version always takes priority over an assessment.

The only critical assessment is CVE-2026-6653 for Debian 13 libxml2 `2.12.7+dfsg+really2.9.14-2.1+deb13u3`. The [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-6653) explicitly classifies trixie as `no-dsa` (Minor issue). Its assessment expires on 2026-11-10. PostgreSQL can invoke the affected XML parser; this is following the vendor risk assessment, not asserting the vulnerable code is absent.

## Effect on current candidates

The [rebuilt-candidate release run](https://github.com/abruncloud/images/actions/runs/38128166438) passed native runtime and logical/physical backup recovery checks on Debian and Alpine, on amd64 and arm64. Rebuilt gosu no longer produces HIGH/CRITICAL findings. Alpine runtime and backup reports have zero HIGH/CRITICAL findings. Debian runtime and backup each have 63 HIGH and one CRITICAL package finding, all without a reported fixed version.

Under the approved policy, all eight saved runtime and backup reports pass: Alpine has zero HIGH/CRITICAL findings; each Debian report retains 63 unfixed HIGH findings as deferred risk and applies the exact expiring vendor assessment to one CRITICAL finding. Without an explicit policy file, the four Debian reports still fail the strict gate. No image publication occurs as part of this policy implementation.

The initial OS findings represent 19 unique CVEs, repeated across packages. Debian explicitly calls eight Minor/no-DSA, defers one other through a point release and postpones one Minor issue. Nine have no trixie Minor assessment or await upstream assessment. Those nine are not claimed unaffected: they are deferred by the approved unfixed-HIGH policy. See [initial investigation](postgres-18-initial-scan.md) for the SQL/XML path and mitigation constraints.

## Maintenance

Scheduled discovery and daily rescanning continue. A newly available fix, new critical finding, changed package version, or expired assessment can block later releases. Adoption of new image digests remains deliberate; existing deployments stay pinned.
