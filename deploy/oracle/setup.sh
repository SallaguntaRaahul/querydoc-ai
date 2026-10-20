#!/usr/bin/env bash
# One-time setup of QueryDoc AI on an Oracle Cloud "Always Free" Ampere VM (Ubuntu 22.04/24.04).
# Run on the VM as the default `ubuntu` user:
#   curl -fsSL https://raw.githubusercontent.com/SallaguntaRaahul/querydoc-ai/master/deploy/oracle/setup.sh -o setup.sh
#   bash setup.sh [admin@email]
# Re-running it updates the code and rebuilds. Author: Raahul Sallagunta
set -euo pipefail
ADMIN_EMAIL="${1:-}"
REPO=https://github.com/SallaguntaRaahul/querydoc-ai.git
DIR=/opt/querydoc-ai

echo "==> Packages (Docker from Ubuntu's own repositories)"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 git unattended-upgrades iptables-persistent
sudo systemctl enable --now docker
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Firewall: Oracle's Ubuntu image only allows SSH; open HTTP/HTTPS"
for port in 80 443; do
  if ! sudo iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT 5 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
  fi
done
sudo netfilter-persistent save

echo "==> Code"
if [ -d "$DIR/.git" ]; then
  sudo git -C "$DIR" pull --ff-only
else
  sudo git clone --depth 1 "$REPO" "$DIR"
fi
sudo chown -R "$USER" "$DIR"

echo "==> Configuration"
ENV_FILE="$DIR/deploy/oracle/.env"
if [ ! -f "$ENV_FILE" ]; then
  IP="$(curl -fsS https://api.ipify.org)"
  {
    echo "DOMAIN=${IP//./-}.sslip.io"
    echo "TORCH_THREADS=$(nproc)"
    if [ -n "$ADMIN_EMAIL" ]; then echo "ADMIN_EMAILS=[\"$ADMIN_EMAIL\"]"; fi
  } > "$ENV_FILE"
fi
cat "$ENV_FILE"

echo "==> Build and start (first build downloads ~4 GB of models: 15-30 min)"
cd "$DIR"
sudo docker compose -f deploy/oracle/docker-compose.yml --env-file "$ENV_FILE" up -d --build
DOMAIN="$(grep '^DOMAIN=' "$ENV_FILE" | cut -d= -f2)"
echo
echo "Started. The app becomes reachable at https://$DOMAIN once the models finish loading (1-3 min)."
echo "Logs: sudo docker compose -f $DIR/deploy/oracle/docker-compose.yml logs -f app"
