# syntax=docker/dockerfile:1
# Generated from the reviewed lock file. Preserve the official runtime contract.
FROM docker.io/library/postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336 AS extension-build

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl \
        "postgresql-server-dev-${PG_MAJOR}=${PG_VERSION}"; \
    curl --fail --show-error --location --proto '=https' --tlsv1.2 \
        'https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.7.tar.gz' --output /tmp/pgvector.tar.gz; \
    echo 'cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85  /tmp/pgvector.tar.gz' | sha256sum -c -; \
    mkdir /tmp/pgvector; \
    tar -xzf /tmp/pgvector.tar.gz -C /tmp/pgvector --strip-components=1; \
    cd /tmp/pgvector; \
    make -j "$(nproc)" OPTFLAGS='' with_llvm=no; \
    make install DESTDIR=/artifact OPTFLAGS='' with_llvm=no; \
    install -Dm644 LICENSE /artifact/usr/share/doc/pgvector/LICENSE; \
    install -Dm644 README.md /artifact/usr/share/doc/pgvector/README.md

FROM docker.io/library/postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336
COPY --from=extension-build /artifact/ /
LABEL org.opencontainers.image.title="AbrunCloud PostgreSQL" \
      org.opencontainers.image.description="Official PostgreSQL with pgvector; upstream initialization and configuration conventions" \
      org.opencontainers.image.version="18.6" \
      org.opencontainers.image.source="https://github.com/abruncloud/images" \
      io.abruncloud.pgvector.version="0.8.7"
