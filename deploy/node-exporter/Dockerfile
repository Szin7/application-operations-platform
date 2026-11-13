FROM golang@sha256:87c65a688975c0b1d4585d204874c45ca78354670e3a5f11368c5a492303d696 AS build

ENV GOTOOLCHAIN=local CGO_ENABLED=0 GOMAXPROCS=2
WORKDIR /src

# Download the tagged source through Go's checksum-verified module proxy.
RUN go mod download -json github.com/prometheus/node_exporter@v1.12.1 > /tmp/source.json \
    && cp -R /go/pkg/mod/github.com/prometheus/node_exporter@v1.12.1/. . \
    && chmod -R u+w .

COPY go.mod go.sum ./
COPY wsl_mountinfo_test.go ./
RUN go mod download \
    && go mod verify \
    && go test -tags nonvme -mod=readonly -count=1 -run '^TestWSLMountinfo$' . \
    && go test -tags nonvme -mod=readonly -count=1 -run 'Filesystem' ./collector \
    && mkdir -p /out/metadata \
    && go build -tags nonvme -mod=readonly -trimpath -buildvcs=false \
       -ldflags='-s -w -X github.com/prometheus/common/version.Version=1.12.1-wsl.1 -X github.com/prometheus/common/version.Revision=6044da783597cc3b57aef7580ddcdcff58a4ee99 -X github.com/prometheus/common/version.Branch=local-procfs-0.23.0' \
       -o /out/node_exporter . \
    && go version -m /out/node_exporter > /out/metadata/build-info.txt \
    && cp go.mod go.sum LICENSE NOTICE /out/metadata/ \
    && cp /tmp/source.json /out/metadata/source.json

FROM quay.io/prometheus/node-exporter@sha256:1b4e4438faca4dd7e001dd445d161a4a2091b0fededa84093b3a8dfeae1f1be0
LABEL org.opencontainers.image.title="Node Exporter for the WSL application lab" \
      org.opencontainers.image.version="1.12.1-wsl.1" \
      org.opencontainers.image.description="Local Node Exporter 1.12.1 build using procfs 0.23.0 for WSL mount parsing" \
      org.opencontainers.image.source="https://github.com/Szin7/application-operations-platform"
COPY --from=build /out/node_exporter /bin/node_exporter
COPY --from=build /out/metadata/ /usr/share/node-exporter-build/
USER 65534:65534
