Name:           srm-monitor-agent
Version:        __VERSION__
Release:        1%{?dist}
Summary:        SRM Monitoring Agent
License:        Proprietary
URL:            https://gitlab.local/srm/simpleremotemanager
BuildArch:      noarch

Source0:        %{name}-%{version}.tar.gz

Requires:       systemd
Requires:       python3 >= 3.7
Requires:       python3-psutil

%description
Collects system metrics (CPU, RAM, disk, load, services) and pushes
them to the SRM Monitoring Service. Includes systemd timer for
periodic reporting (every 60 seconds).

%prep
%setup -q

%install
mkdir -p %{buildroot}/usr/local/bin
mkdir -p %{buildroot}/etc/systemd/system
mkdir -p %{buildroot}/etc/srm

cp usr/local/bin/srm-monitor-agent %{buildroot}/usr/local/bin/srm-monitor-agent

cp etc/systemd/system/srm-monitor-agent.service %{buildroot}/etc/systemd/system/
cp etc/systemd/system/srm-monitor-agent.timer %{buildroot}/etc/systemd/system/

%files
%attr(755,root,root) /usr/local/bin/srm-monitor-agent
/etc/systemd/system/srm-monitor-agent.service
/etc/systemd/system/srm-monitor-agent.timer
%dir %attr(700,root,root) /etc/srm

%post
systemctl daemon-reload
echo "srm-monitor-agent installiert."
echo "Einrichtung: sudo srm-monitor-agent --init --url <MONITOR_URL> --api-key <KEY> --server-id <ID>"

%preun
systemctl stop srm-monitor-agent.timer 2>/dev/null || true
systemctl disable srm-monitor-agent.timer 2>/dev/null || true

%postun
systemctl daemon-reload
