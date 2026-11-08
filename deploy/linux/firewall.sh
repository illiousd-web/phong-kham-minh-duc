#!/bin/sh
# Run on the clinic server as administrator, after reviewing the subnet/IP.
set -eu
: "${CLINIC_BIND_IP:?Set private server IP}"
: "${CLINIC_ALLOWED_CIDRS:?Set one clinic IPv4 CIDR}"
CLINIC_HTTPS_PORT="${CLINIC_HTTPS_PORT:-8443}"
case "$CLINIC_HTTPS_PORT" in *[!0-9]*|'') exit 2;; esac
# Keep unrelated SSH/firewall rules; DO NOT run ufw reset or silently enable it.
ufw allow in proto tcp from "$CLINIC_ALLOWED_CIDRS" to "$CLINIC_BIND_IP" port "$CLINIC_HTTPS_PORT" comment 'MinhDuc clinic LAN HTTPS'
ufw deny in proto tcp to "$CLINIC_BIND_IP" port 5432 comment 'MinhDuc database never on LAN'
ufw status numbered
printf '%s\n' 'Review existing broad allow rules; set default deny incoming and enable UFW from console only after preserving admin access.'
