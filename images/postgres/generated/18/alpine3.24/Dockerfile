# syntax=docker/dockerfile:1
# The official Alpine image retains its matching PostgreSQL headers and PGXS.
FROM docker.io/library/postgres:18.6-alpine3.24@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873 AS extension-build

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

FROM docker.io/library/postgres:18.6-alpine3.24@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873
COPY --from=extension-build /artifact/ /
LABEL org.opencontainers.image.title="AbrunCloud PostgreSQL" \
      org.opencontainers.image.description="Official PostgreSQL with pgvector; upstream initialization and configuration conventions" \
      org.opencontainers.image.version="18.6" \
      org.opencontainers.image.source="https://github.com/abruncloud/images" \
      io.abruncloud.pgvector.version="0.8.7"
