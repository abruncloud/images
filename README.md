# Abrun Cloud Images

Reusable container images published to the `abruncloud` organization on Docker Hub.
Images work independently of the Abrun platform and preserve documented upstream
runtime conventions.

The initial image is [PostgreSQL](images/postgres/README.md), with Debian and Alpine
variants, pgvector, and backup-tool tags.

## Repository layout

- `images/<name>/`: image documentation, policy, resolved input lock, templates,
  runtime files, examples, and generated Dockerfiles.
- `tools/`: discovery, generation, and release automation.
- `.github/workflows/`: input discovery, validation, builds, and publication.
- `tests/`: integration checks that also run against locally built images.

Version and distribution differences belong in each image's metadata. New images
may be databases, language runtimes, applications, or infrastructure services.
There is no database-specific root hierarchy.

## Releases and tags

Standard upstream-style version and distribution tags are mutable aliases. An
image can be rebuilt for OS, extension, or packaging fixes without changing its
server version. Production systems requiring stable deployments should pin the
published image digest. No `-r1` suffix is required.

The release workflow must qualify all supported architectures and variants
before promoting aliases. Release records identify source commits, input versions,
and output digests. Publishing an image does not upgrade running containers.

## Local development

See the image README for build and test commands. Python 3 and Docker with Buildx
are required. Discovery needs network access; builds require registry access.

## Maintenance

Scheduled discovery checks upstream releases and image digests. Changes to
runtime contracts, major versions, extensions, or default distributions require
review. Images are scanned, with SBOM and provenance attached during publication.

See [SECURITY.md](SECURITY.md) for reporting and maintenance policy.

## GitHub Actions setup

Configure repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` with push
access to `abruncloud/postgres`. The release workflow uses the `dockerhub`
environment; add approval restrictions there if desired.

Protect `main` with the `required` CI status check before enabling routine update
merges. Discovery must be allowed to create repository pull requests. The workflow
uses the repository-scoped GitHub token and explicitly dispatches qualification
and publication, avoiding a separate long-lived GitHub personal access token.
If the repository or organization disables Actions-created pull requests,
discovery fails with an actionable error instead of bypassing the policy.

Normal server patch/base rebuilds can merge after qualification. Changes to the
pgvector source lock remain manual review. Missing credentials, failed tests,
security findings, or stale source commits prevent public alias promotion.

Publication and daily rescans retain complete runtime and backup vulnerability reports as GitHub Actions artifacts, even when a scan fails. A separate fail-closed gate blocks all HIGH/CRITICAL findings, including those without an available fix; missing or invalid reports also block promotion.
