### Fixed
- Agent DEB package: the maintainer scripts no longer abort installation, upgrade or removal when systemd is not PID 1 (containers, chroots); a failed `systemctl daemon-reload` is ignored silently, as in the RPM package.
