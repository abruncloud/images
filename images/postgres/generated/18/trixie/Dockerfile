# syntax=docker/dockerfile:1
# Rebuild the same gosu source with a patched compiler; only artifacts enter runtime.
FROM --platform=$BUILDPLATFORM docker.io/library/golang:1.27.3-trixie@sha256:fbb7ae40b62ff8afe31662df570d39b4f5052ac32b90dae8e60d7657a20a74f4 AS gosu-build
ARG TARGETARCH
ENV GOTOOLCHAIN=local CGO_ENABLED=0
RUN set -eux; \
    test "$(go env GOVERSION)" = 'go1.27.3'; \
    curl --fail --show-error --location --proto '=https' --tlsv1.2 \
        'https://github.com/tianon/gosu/archive/refs/tags/1.19.tar.gz' --output /tmp/gosu.tar.gz; \
    echo 'cd9719b775dbfedae53923c9b0dc792b66d42c51e0b36652ed6f747fbadc0164  /tmp/gosu.tar.gz' | sha256sum --check -; \
    mkdir /src /out; \
    tar -xzf /tmp/gosu.tar.gz -C /src --strip-components=1; \
    cd /src; \
    go mod download; \
    go mod verify; \
    go test -mod=readonly ./...; \
    GOOS=linux GOARCH="$TARGETARCH" go build -mod=readonly -trimpath -buildvcs=false -ldflags='-w' -o /out/gosu .; \
    go version -m /out/gosu; \
    cp LICENSE /out/LICENSE

# Generated from the reviewed lock file. Preserve the official runtime contract.
FROM docker.io/library/postgres:18.6-trixie@sha256:edb0c08dc33befd0262ab3b5cf1c4f3f8cfd8b09e88c05b45adee29d6761ddb6 AS extension-build

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

FROM docker.io/library/postgres:18.6-trixie@sha256:edb0c08dc33befd0262ab3b5cf1c4f3f8cfd8b09e88c05b45adee29d6761ddb6
COPY --from=gosu-build /out/gosu /usr/local/bin/gosu
COPY --from=gosu-build /out/LICENSE /usr/share/doc/gosu/LICENSE
ENV GOSU_VERSION=1.19
LABEL io.abruncloud.gosu.version="1.19" io.abruncloud.gosu.go.version="1.27.3"
COPY --from=extension-build /artifact/ /
LABEL org.opencontainers.image.title="AbrunCloud PostgreSQL" \
      org.opencontainers.image.description="Official PostgreSQL with pgvector; upstream initialization and configuration conventions" \
      org.opencontainers.image.version="18.6" \
      org.opencontainers.image.source="https://github.com/abruncloud/images" \
      io.abruncloud.pgvector.version="0.8.7"
