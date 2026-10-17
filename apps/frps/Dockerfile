# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

FROM snowdreamtech/frps:0.69.1@sha256:a615a3e42f174050fbd902a989f9c21eed2dc0b016932d10ab599743cca0e41a

# frps under a supervisor that starts it only from a checked copy of the configuration the
# server writes (see frps-supervisor.sh). The supervisor reads frps.toml from /etc/frp, which
# holds only what the server writes. The supervisor runs as root and starts frps as the user
# frps, whose UID no other service of the stack uses. No program keeps a setuid or setgid bit,
# so none leads frps back to root.
RUN rm -f /etc/frp/frps.toml \
    && find / -xdev -type f -perm /6000 -exec chmod u-s,g-s {} + \
    && addgroup -S -g 10002 frps \
    && adduser -S -D -H -h /nonexistent -s /sbin/nologin -u 10002 -G frps frps
COPY frps-supervisor.sh /usr/local/bin/frps-supervisor.sh

ENTRYPOINT ["/bin/sh", "/usr/local/bin/frps-supervisor.sh"]
