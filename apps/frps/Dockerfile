# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

FROM snowdreamtech/frps:0.72.0-alpine@sha256:bd1b1475d211f5349dfa496c82185ee3bf96baa7b480d1db13914df0f765e9a2

# frps under a supervisor that starts it only from a checked copy of the configuration the
# server writes (see frps-supervisor.sh). The supervisor reads frps.toml from /etc/frp, which
# holds only what the server writes. The supervisor runs as root, starts frps as the user frps
# and asks the dashboard of frps as the user frps-fetch, two UIDs no other service of the stack
# uses. root is in the group frps: without CAP_CHOWN, the supervisor gives the copy frps runs
# from to that group, so that root and frps alone read it. No program keeps a setuid or setgid
# bit, so none leads frps back to root. frps and curl, the programs that run as frps and
# frps-fetch, are root's and for anyone else to execute only (0711), so that their processes are
# not dumpable and the entries in /proc/<pid> of each are root's; a program the supervisor comes
# to start as frps or frps-fetch gets the same mode.
RUN rm -f /etc/frp/frps.toml \
    && find / -xdev -type f -perm /6000 -exec chmod u-s,g-s {} + \
    && chown root:root /usr/bin/frps /usr/bin/curl \
    && chmod 0711 /usr/bin/frps /usr/bin/curl \
    && addgroup -S -g 10002 frps \
    && adduser -S -D -H -h /nonexistent -s /sbin/nologin -u 10002 -G frps frps \
    && addgroup root frps \
    && addgroup -S -g 10003 frps-fetch \
    && adduser -S -D -H -h /nonexistent -s /sbin/nologin -u 10003 -G frps-fetch frps-fetch
COPY frps-supervisor.sh /usr/local/bin/frps-supervisor.sh

ENTRYPOINT ["/bin/sh", "/usr/local/bin/frps-supervisor.sh"]
