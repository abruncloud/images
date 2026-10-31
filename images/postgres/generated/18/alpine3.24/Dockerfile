# syntax=docker/dockerfile:1
# Rebuild the same gosu source with a patched compiler; only artifacts enter runtime.
FROM --platform=$BUILDPLATFORM docker.io/library/golang:1.27.3-trixie@sha256:c65ecfe613b539ac74c62a4c3b2c27e8f8a6076384c8f27e8a3c0f3be17cc385 AS gosu-build
ARG TARGETARCH
ENV GOTOOLCHAIN=local CGO_ENABLED=0
RUN set -eux; \
    test "$(go env GOVERSION)" = 'go1.27.3'; \
    curl --fail --show-error --location --proto '=https' --tlsv1.2 \
        'https://github.com/tianon/gosu/archive/refs/tags/1.20.tar.gz' --output /tmp/gosu.tar.gz; \
    echo '207a2045e890d3ca3326027c5f585733085960b401a49dbc00e3bb628c054cf8  /tmp/gosu.tar.gz' | sha256sum --check -; \
    mkdir /src /out; \
    tar -xzf /tmp/gosu.tar.gz -C /src --strip-components=1; \
    cd /src; \
    go mod download; \
    go mod verify; \
    go test -mod=readonly ./...; \
    GOOS=linux GOARCH="$TARGETARCH" go build -mod=readonly -trimpath -buildvcs=false -ldflags='-w' -o /out/gosu .; \
    go version -m /out/gosu; \
    cp LICENSE /out/LICENSE

# The official Alpine image retains its matching PostgreSQL headers and PGXS.
FROM docker.io/library/postgres:18.6-alpine3.24@sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5 AS extension-build

RUN set -eux; \
    apk add --no-cache build-base ca-certificates curl; \
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

FROM docker.io/library/postgres:18.6-alpine3.24@sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5
COPY --from=gosu-build /out/gosu /usr/local/bin/gosu
COPY --from=gosu-build /out/LICENSE /usr/share/doc/gosu/LICENSE
ENV GOSU_VERSION=1.20
LABEL io.abruncloud.gosu.version="1.20" io.abruncloud.gosu.go.version="1.27.3"
COPY --from=extension-build /artifact/ /
LABEL org.opencontainers.image.title="AbrunCloud PostgreSQL" \
      org.opencontainers.image.description="Official PostgreSQL with pgvector; upstream initialization and configuration conventions" \
      org.opencontainers.image.version="18.6" \
      org.opencontainers.image.source="https://github.com/abruncloud/images" \
      io.abruncloud.pgvector.version="0.8.7"
