# Security

## Reporting

Report vulnerabilities through this repository's GitHub private vulnerability
reporting feature if enabled. If it is unavailable, contact the organization
maintainers privately before publishing sensitive details. Do not include
credentials in issues, test output, or build arguments.

## Maintenance policy

Only release lines listed as supported in each image's metadata receive updates.
Initial PostgreSQL support is version 18 on the documented Debian and Alpine
distributions. Upstream end-of-life software is not guaranteed security fixes.

Base images are pinned by digest and downloaded extension sources by checksum.
Scheduled discovery checks for changes; failed updates need maintainer attention.
Runtime images retain the upstream entrypoint and necessary shell support. Build
dependencies remain in build stages where possible.

CI scans each candidate and publishes SBOM/provenance and signatures. These checks
do not establish that an image is vulnerability-free or certify compliance.
Any accepted vulnerability exception must identify the affected component,
reason, owner, and expiry. No exceptions are accepted implicitly by the workflow.

Image tags can move after successful rebuilds. Pin a digest for stable deployments
and explicitly adopt a newer digest after compatibility checks. Retain images
required for existing deployments and backup recovery; do not delete referenced
release digests during cleanup.

Publishing credentials must only be available to trusted release jobs. Fork pull
requests must not receive publishing secrets or write permissions. Changes to CI
and source checksums require the same review as changes to runtime code.

Publication and daily rescans retain complete runtime and backup vulnerability reports as GitHub Actions artifacts, even when a scan fails. The gate defaults to strict HIGH/CRITICAL blocking. Publication and daily rescans explicitly select the reviewed actionable policy with `python3 tools/security_gate.py --policy images/postgres/security-policy.json scan-runtime.json scan-backup.json`: fixed HIGH findings and all CRITICAL findings block; unfixed HIGH findings remain reported as deferred risks. An unfixed CRITICAL finding can pass only through an exact, unexpired vendor assessment matching its CVE, package, installed version, OS family/major and OS package scan type. Assessments record risk acceptance, not proof that an image is safe or unaffected. Missing or invalid reports and malformed policies fail closed.
