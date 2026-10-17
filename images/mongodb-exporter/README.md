# MongoDB exporter

`abruncloud/mongodb-exporter` is a generic compatibility image containing the **Percona MongoDB exporter 0.53.0 rebuilt with reviewed security fixes** plus a pinned official BusyBox runtime. It has no MongoDB server, backup tools, platform setup scripts or stored credentials.

The original Percona image uses a scratch filesystem. This image supplies `/bin/sh`, `/bin/busybox`, `nc -e`, `cat` and `sleep` so operators can mount their own secret bootstrap and perform a private bounded loopback scrape without publishing the exporter port. The feature source and upstream CLI flags are preserved; the Go compiler and four dependency families are updated explicitly to fix scanner-confirmed vulnerabilities.

Tags are `0.53.0`, `0.53`, `0.53.0-busybox` and `0.53-busybox`. Each is rebuilt only after native amd64/arm64 qualification, security scans and signing. Pin the image digest in production. The default user/group is `65535:65535`; an arbitrary nonroot UID such as `65534:65534` is also supported. Default entrypoint is `/mongodb_exporter`, listening on 9216 when configured. No port is published by the image.

```sh
docker run --rm --network databases \
  abruncloud/mongodb-exporter:0.53.0 \
  --mongodb.uri=mongodb://database:27017
```

For authentication, use an orchestrator-managed secret and an operator-owned mounted bootstrap rather than embedding a password in the image, command line or shell history. Follow upstream flags for credentials, TLS and collectors; the image supplies no default credentials or broad roles. Mount any needed CA certificate explicitly.

`versions.lock.json` pins the original Percona multiarch image and BusyBox index. Native tests record original and rebuilt executable SHA256, verify compiler/module build information, unprivileged execution and `nc -e` loopback behavior. The platform separately qualifies actual MongoDB authentication, metrics and collector transport. Discovery keeps patch updates within the reviewed exporter 0.53 and BusyBox 1.37 uclibc lines. Existing deployment digests remain pinned.

The exporter is [Apache-2.0](https://github.com/percona/mongodb_exporter/blob/v0.53.0/LICENSE); BusyBox includes GPL-2.0 components. Notices are retained in `/usr/share/licenses/`. Corresponding BusyBox sources and Docker Official Image build recipes are available from the [upstream source archive](https://busybox.net/downloads/busybox-1.37.0.tar.bz2) and [Docker Official BusyBox source/build repository](https://github.com/docker-library/busybox). We preserve the official BusyBox binary; the exporter is rebuilt as described above. Public CA roots are included, while private CAs can be mounted explicitly.

- [Percona exporter documentation and collectors](https://github.com/percona/mongodb_exporter/tree/v0.53.0)
- [Docker Official BusyBox image](https://hub.docker.com/_/busybox)

## Explicit security source rebuild

The first candidate using upstream prebuilt binaries failed the existing actionable release policy. We retain that evidence and rebuild the exact upstream feature source with pinned Go1.27.2 and the minimal compatible security module graph. We do not claim binary identity with vendor releases, and do not suppress findings or change the release policy. See [security-source.lock.json](security-source.lock.json) for exact source commit/archive SHA256, compiler digest, security overrides and CVEs, and [security-build/go.mod](security-build/go.mod) / [go.sum](security-build/go.sum) for the complete reviewed dependency graph.

The feature version and compatibility tags remain unchanged; every rebuild has a distinct immutable digest, source revision, SBOM, provenance and signed release record. Existing instances do not follow moving tags. Discovery updates exact source/module locks from the same official source repository, keeps compiler patches in the reviewed Go1.27 line and preserves minimum security floors. New feature/minor release lines require review; routine patches still require native tests and security qualification. TLS, native authentication and compression are preserved. MongoDB tools additionally retain the upstream Linux `gssapi,failpoints` build tags, CGO and PIE mode; GSSAPI links to the distribution Kerberos libraries.
