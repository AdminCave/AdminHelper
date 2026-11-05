# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# xrdp 0.10 with the graphics pipeline, the server of the embedded RDP live test
# (scripts/tests/desktop_e2e_rdp_embedded.sh). Test only: a fixed user e2e/e2e and a
# certificate made at every start. The session is a bare xterm, which answers a key
# with a picture.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      xrdp xorgxrdp xterm openssl \
 && rm -rf /var/lib/apt/lists/* \
 && dpkg-query -W -f='${Version}\n' xrdp | grep -q '^0\.10\.' \
 && useradd --create-home --shell /bin/sh e2e \
 && echo 'e2e:e2e' | chpasswd \
 && printf '#!/bin/sh\nexec xterm -geometry 100x30+0+0\n' > /etc/xrdp/startwm.sh \
 && chmod 755 /etc/xrdp/startwm.sh

COPY --chmod=755 entrypoint.sh /usr/local/bin/xrdp-gfx-entrypoint
EXPOSE 3389
ENTRYPOINT ["/usr/local/bin/xrdp-gfx-entrypoint"]
