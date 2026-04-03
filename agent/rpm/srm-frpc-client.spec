Name:           srm-frpc-client
Version:        __VERSION__
Release:        1%{?dist}
Summary:        SRM FRP Client with auto-sync
License:        Proprietary
URL:            https://gitlab.local/srm/simpleremotemanager

Source0:        %{name}-%{version}.tar.gz

Requires:       systemd
Requires:       curl
Requires:       coreutils

%description
FRP Client (frpc) bundled with an automatic config sync agent.
Managed by Simple Remote Manager (SRM). Includes systemd units
for frpc daemon and periodic config synchronization.

%prep
%setup -q

%install
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/usr/local/bin
mkdir -p %{buildroot}/etc/systemd/system
mkdir -p %{buildroot}/etc/frp/pki

cp usr/bin/frpc %{buildroot}/usr/bin/frpc
cp usr/local/bin/srm-frpc-sync %{buildroot}/usr/local/bin/srm-frpc-sync

cp etc/systemd/system/frpc.service %{buildroot}/etc/systemd/system/
cp etc/systemd/system/srm-frpc-sync.service %{buildroot}/etc/systemd/system/
cp etc/systemd/system/srm-frpc-sync.timer %{buildroot}/etc/systemd/system/

%files
%attr(755,root,root) /usr/bin/frpc
%attr(755,root,root) /usr/local/bin/srm-frpc-sync
/etc/systemd/system/frpc.service
/etc/systemd/system/srm-frpc-sync.service
/etc/systemd/system/srm-frpc-sync.timer
%dir %attr(700,root,root) /etc/frp
%dir %attr(700,root,root) /etc/frp/pki

%post
systemctl daemon-reload
echo "srm-frpc-client installiert."
echo "Einrichtung: sudo srm-frpc-sync --init --url <SRM_URL> --token <TOKEN> --server-id <ID>"

%preun
systemctl stop srm-frpc-sync.timer 2>/dev/null || true
systemctl stop frpc.service 2>/dev/null || true
systemctl disable srm-frpc-sync.timer 2>/dev/null || true
systemctl disable frpc.service 2>/dev/null || true

%postun
systemctl daemon-reload
