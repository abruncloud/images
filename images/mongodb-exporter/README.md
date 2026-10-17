# MongoDB exporter

`abruncloud/mongodb-exporter` is a generic compatibility image containing the **unchanged Percona MongoDB exporter 0.53.0** plus a pinned official BusyBox runtime. It has no MongoDB server, backup tools, platform setup scripts or stored credentials.

The original Percona image uses a scratch filesystem. This image supplies `/bin/sh`, `/bin/busybox`, `nc -e`, `cat` and `sleep` so operators can mount their own secret bootstrap and perform a private bounded loopback scrape without publishing the exporter port. Exporter behavior and upstream CLI flags remain unchanged.

Tags are `0.53.0`, `0.53`, `0.53.0-busybox` and `0.53-busybox`. Each is rebuilt only after native amd64/arm64 qualification, security scans and signing. Pin the image digest in production. The default user/group is `65535:65535`; an arbitrary nonroot UID such as `65534:65534` is also supported. Default entrypoint is `/mongodb_exporter`, listening on 9216 when configured. No port is published by the image.

```sh
docker run --rm --network databases \
  abruncloud/mongodb-exporter:0.53.0 \
  --mongodb.uri=mongodb://database:27017
```

For authentication, use an orchestrator-managed secret and an operator-owned mounted bootstrap rather than embedding a password in the image, command line or shell history. Follow upstream flags for credentials, TLS and collectors; the image supplies no default credentials or broad roles. Mount any needed CA certificate explicitly.

`versions.lock.json` pins the original Percona multiarch image and BusyBox index. Native tests compare SHA256 of the vendor executable byte for byte, verify unprivileged execution and `nc -e` loopback behavior. The platform separately qualifies actual MongoDB authentication, metrics and collector transport. Discovery keeps patch updates within the reviewed exporter 0.53 and BusyBox 1.37 uclibc lines. Existing deployment digests remain pinned.

The exporter is [Apache-2.0](https://github.com/percona/mongodb_exporter/blob/v0.53.0/LICENSE); BusyBox includes GPL-2.0 components. Notices are retained in `/usr/share/licenses/`. Corresponding BusyBox sources and Docker Official Image build recipes are available from the [upstream source archive](https://busybox.net/downloads/busybox-1.37.0.tar.bz2) and [Docker Official BusyBox source/build repository](https://github.com/docker-library/busybox). We do not modify or rebuild those upstream binaries.

- [Percona exporter documentation and collectors](https://github.com/percona/mongodb_exporter/tree/v0.53.0)
- [Docker Official BusyBox image](https://hub.docker.com/_/busybox)
