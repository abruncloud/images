# Generated from immutable inputs. Preserve the official MySQL startup contract.
# Rebuild the same gosu source with a patched compiler; only artifacts enter runtime.
FROM --platform=$BUILDPLATFORM docker.io/library/golang:1.27.3-trixie@sha256:af1bfc2614ebb1dbd31af514b78740fd678850e76498762b425ecee4c5c6ea80 AS gosu-build
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

FROM docker.io/library/mysql:8.4.13-oraclelinux9@sha256:a81d043930e51745522bd5c430961cf8286f0a23f0a9a2a6e0108f7ea71b0902 AS runtime
COPY --from=gosu-build /out/gosu /usr/local/bin/gosu
COPY --from=gosu-build /out/LICENSE /usr/local/share/licenses/gosu/LICENSE
RUN gosu --version && gosu nobody true && mysqld --version
