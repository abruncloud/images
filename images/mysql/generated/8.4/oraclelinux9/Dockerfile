# Generated from immutable inputs. Preserve the official MySQL startup contract.
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

FROM docker.io/library/mysql:8.4.13-oraclelinux9@sha256:76f0358884cb92d9a086d24e5671c38048d3fef40f2588703d73eb55392d6b69 AS runtime
COPY --from=gosu-build /out/gosu /usr/local/bin/gosu
COPY --from=gosu-build /out/LICENSE /usr/local/share/licenses/gosu/LICENSE
RUN gosu --version && gosu nobody true && mysqld --version
