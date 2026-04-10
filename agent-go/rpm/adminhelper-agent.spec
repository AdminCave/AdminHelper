Name:           adminhelper-agent
Version:        __VERSION__
Release:        1%{?dist}
Summary:        AdminHelper Agent — FRPC Sync + Monitoring
License:        Proprietary
URL:            https://gitlab.local/adminhelper/adminhelper

Source0:        %{name}-%{version}.tar.gz

Requires:       systemd
Obsoletes:      srm-frpc-client < %{version}
Obsoletes:      srm-monitor-agent < %{version}
Obsoletes:      srm-agent < %{version}

%description
Unified agent for AdminHelper. Combines FRP Client
(frpc) with automatic config sync and system monitoring in a single
Go binary. Replaces srm-frpc-client, srm-monitor-agent, and srm-agent packages.

%prep
%setup -q

%install
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/usr/local/bin
mkdir -p %{buildroot}/etc/systemd/system
mkdir -p %{buildroot}/etc/frp/pki
mkdir -p %{buildroot}/etc/adminhelper

cp usr/local/bin/adminhelper-agent %{buildroot}/usr/local/bin/adminhelper-agent
cp usr/bin/frpc %{buildroot}/usr/bin/frpc

cp etc/systemd/system/frpc.service %{buildroot}/etc/systemd/system/
cp etc/systemd/system/adminhelper-agent.service %{buildroot}/etc/systemd/system/
cp etc/systemd/system/adminhelper-agent.timer %{buildroot}/etc/systemd/system/

%files
%attr(755,root,root) /usr/local/bin/adminhelper-agent
%attr(755,root,root) /usr/bin/frpc
/etc/systemd/system/frpc.service
/etc/systemd/system/adminhelper-agent.service
/etc/systemd/system/adminhelper-agent.timer
%dir %attr(700,root,root) /etc/frp
%dir %attr(700,root,root) /etc/frp/pki
%dir %attr(700,root,root) /etc/adminhelper

%post
systemctl daemon-reload
# Alte Units aufraeumen
for unit in srm-frpc-sync.timer srm-frpc-sync.service srm-monitor-agent.timer srm-monitor-agent.service srm-agent.timer srm-agent.service; do
    if [ -f "/etc/systemd/system/${unit}" ]; then
        systemctl stop "${unit}" 2>/dev/null || true
        systemctl disable "${unit}" 2>/dev/null || true
        rm -f "/etc/systemd/system/${unit}"
    fi
done
systemctl daemon-reload
echo "adminhelper-agent installiert."
echo "FRPC Einrichtung:    sudo adminhelper-agent frpc init --url <ADMINHELPER_URL> --token <TOKEN> --server-id <ID>"
echo "Monitor Einrichtung: sudo adminhelper-agent monitor init --url <MONITOR_URL> --api-key <KEY> --server-id <ID>"

%preun
systemctl stop adminhelper-agent.timer 2>/dev/null || true
systemctl stop frpc.service 2>/dev/null || true
systemctl disable adminhelper-agent.timer 2>/dev/null || true
systemctl disable frpc.service 2>/dev/null || true

%postun
systemctl daemon-reload
