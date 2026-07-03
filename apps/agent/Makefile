VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
LDFLAGS  = -ldflags "-s -w -X main.version=$(VERSION)"
BINARY   = adminhelper-agent

.PHONY: build build-linux build-windows clean tidy deb rpm all

build: build-linux

# CGO_ENABLED=0 → a fully static binary that runs on any glibc (the agent is pure-Go:
# gopsutil reads /proc, no cgo). Without it the binary dynamically links the build
# host's glibc and won't start on older distros (e.g. the .rpm on RHEL/Rocky 8).
build-linux:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o bin/$(BINARY) ./cmd/adminhelper-agent

build-windows:
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o bin/$(BINARY).exe ./cmd/adminhelper-agent

deb: build-linux
	cd ../.. && VERSION=$(VERSION) bash apps/agent/build-deb.sh

rpm: build-linux
	cd ../.. && VERSION=$(VERSION) bash apps/agent/build-rpm.sh

clean:
	rm -rf bin/ build-deb/ build-rpm/

tidy:
	go mod tidy

all: build-linux build-windows
