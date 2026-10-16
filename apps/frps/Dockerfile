# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

FROM snowdreamtech/frps:0.69.1@sha256:a615a3e42f174050fbd902a989f9c21eed2dc0b016932d10ab599743cca0e41a

# frps under a supervisor that starts it only from a checked copy of the configuration the
# server writes (see frps-supervisor.sh). The supervisor manages the configuration alone, so
# the sample configuration the base image ships goes.
RUN rm -f /etc/frp/frps.toml
COPY frps-supervisor.sh /usr/local/bin/frps-supervisor.sh

ENTRYPOINT ["/bin/sh", "/usr/local/bin/frps-supervisor.sh"]
