#!/usr/bin/env bash
# Route this host's DNS through public resolvers (Cloudflare + Google)
# instead of the local Pi-hole / AdGuard / router that poisons
# libgen / annas-archive / z-lib hostnames. Makes Grabarr behave like
# Shelfmark-in-Docker, which uses its own internal resolver.
#
# Usage:
#   sudo ./use-public-dns.sh             # apply (Cloudflare + Google)
#   sudo ./use-public-dns.sh --restore   # undo
#   ./use-public-dns.sh --status         # show current DNS (no sudo)

set -e

DROPIN=/etc/systemd/resolved.conf.d/99-grabarr-public-dns.conf

say() { printf '[dns] %s\n' "$1"; }

show_status() {
    say "resolved status:"
    resolvectl status 2>/dev/null | grep -E "Current DNS|DNS Servers" | head -4 | sed 's/^/  /'
    printf '\n'
    say "test lookups (want real IPs, not 127.0.0.1):"
    for h in libgen.la libgen.bz libgen.gl annas-archive.gl; do
        ip=$(getent hosts "$h" 2>/dev/null | awk '{print $1}' | head -1)
        printf '  %-20s %s\n' "$h" "${ip:-(no answer)}"
    done
}

case "${1:-apply}" in
    --status|status)
        show_status
        exit 0
        ;;
    --restore|restore)
        if [ "$EUID" -ne 0 ]; then
            say "need root. re-run with: sudo $0 --restore"
            exit 1
        fi
        if [ -f "$DROPIN" ]; then
            rm -f "$DROPIN"
            say "removed $DROPIN"
            systemctl restart systemd-resolved
            resolvectl flush-caches
            say "restored system DNS — showing new state:"
            show_status
        else
            say "no drop-in found; nothing to restore"
            show_status
        fi
        exit 0
        ;;
    --apply|apply|"")
        : # fall through
        ;;
    *)
        printf 'usage: %s [--apply | --restore | --status]\n' "$0" >&2
        exit 1
        ;;
esac

if [ "$EUID" -ne 0 ]; then
    say "need root. re-run with: sudo $0"
    exit 1
fi

if ! systemctl is-active --quiet systemd-resolved; then
    say "systemd-resolved isn't active; aborting (edit /etc/resolv.conf by hand instead)"
    exit 1
fi

mkdir -p "$(dirname "$DROPIN")"
cat > "$DROPIN" <<'EOF'
# Managed by Grabarr's use-public-dns.sh. Remove with --restore.
#
# Routes every DNS lookup on this host through Cloudflare + Google.
# Disables the local DNS link servers so Pi-hole / router DNS
# (which may poison libgen/annas-archive/z-lib) can't override.
[Resolve]
DNS=1.1.1.1 8.8.8.8 9.9.9.9
FallbackDNS=
Domains=~.
DNSStubListener=yes
EOF

say "wrote $DROPIN:"
sed 's/^/  /' "$DROPIN"
printf '\n'

systemctl restart systemd-resolved
resolvectl flush-caches

say "applied — showing new state:"
show_status
