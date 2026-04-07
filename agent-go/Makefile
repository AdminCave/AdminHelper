VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
LDFLAGS  = -ldflags "-s -w -X main.version=$(VERSION)"
BINARY   = srm-agent

.PHONY: build build-linux build-windows clean tidy

build: build-linux

build-linux:
	GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o bin/$(BINARY) ./cmd/srm-agent

build-windows:
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o bin/$(BINARY).exe ./cmd/srm-agent

clean:
	rm -rf bin/

tidy:
	go mod tidy

all: build-linux build-windows
