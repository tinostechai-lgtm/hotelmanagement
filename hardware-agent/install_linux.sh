#!/usr/bin/env bash
# Servora Hardware Agent installer for Linux / Raspberry Pi (systemd).
# Usage:  sudo ./install_linux.sh            (asks for your device key)
#         sudo SERVORA_DEVICE_KEY=dev_xxx ./install_linux.sh
set -euo pipefail

INSTALL_DIR=/opt/servora-agent
SERVICE=servora-agent
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo:  sudo $0"; exit 1
fi

PY=$(command -v python3 || true)
if [ -z "$PY" ]; then
  echo "Installing Python 3 ..."
  if command -v apt-get >/dev/null; then apt-get update -qq && apt-get install -y -qq python3 python3-venv
  elif command -v dnf >/dev/null; then dnf install -y python3
  else echo "Please install Python 3.9+ and run again."; exit 1; fi
  PY=$(command -v python3)
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "Python 3.9+ is required."; exit 1; }

echo "==> Copying agent to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
install -m 0755 "$SRC/servora_agent.py" "$INSTALL_DIR/servora_agent.py"
install -m 0644 "$SRC/requirements-optional.txt" "$INSTALL_DIR/requirements-optional.txt"

echo "==> Installing optional drivers (USB + serial) in a private environment"
RUN_PY="$PY"
if "$PY" -m venv "$INSTALL_DIR/venv" >/dev/null 2>&1; then
  RUN_PY="$INSTALL_DIR/venv/bin/python"
  "$RUN_PY" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
  "$RUN_PY" -m pip install -q pyusb pyserial || echo "   (optional drivers not installed - network printers still work)"
else
  echo "   python3-venv missing; skipping optional drivers (network printers still work)"
fi
# libusb is needed by pyusb
command -v apt-get >/dev/null && apt-get install -y -qq libusb-1.0-0 >/dev/null 2>&1 || true

if [ ! -f "$INSTALL_DIR/config.json" ]; then
  if [ -n "${SERVORA_DEVICE_KEY:-}" ]; then
    cat > "$INSTALL_DIR/config.json" <<JSON
{
  "server_url": "${SERVORA_SERVER_URL:-https://servora.vercel.app}",
  "device_key": "${SERVORA_DEVICE_KEY}",
  "poll_interval": 2
}
JSON
  else
    "$RUN_PY" "$INSTALL_DIR/servora_agent.py" --config "$INSTALL_DIR/config.json" setup
  fi
fi
chmod 600 "$INSTALL_DIR/config.json"

# The service runs as root so it can open USB, serial and Bluetooth devices
# without extra udev rules. Set SERVORA_USER=<name> to run as another user
# (that user then needs the dialout / lp groups and a udev rule for USB).
RUN_USER="${SERVORA_USER:-root}"
if [ "$RUN_USER" != "root" ]; then
  for g in dialout lp plugdev bluetooth; do getent group $g >/dev/null && usermod -aG $g "$RUN_USER" || true; done
  chown -R "$RUN_USER" "$INSTALL_DIR"
fi

echo "==> Registering systemd service '$SERVICE'"
sed -e "s#@INSTALL_DIR@#$INSTALL_DIR#g" -e "s#@PYTHON@#$RUN_PY#g" -e "s#@USER@#$RUN_USER#g" \
  "$SRC/servora-agent.service" > /etc/systemd/system/$SERVICE.service
systemctl daemon-reload
systemctl enable --now $SERVICE
sleep 2
systemctl --no-pager --lines=5 status $SERVICE || true

cat <<MSG

Done! The Servora Hardware Agent is running and will start automatically on boot.
  Live log     : journalctl -u $SERVICE -f
  Log file     : $INSTALL_DIR/servora-agent.log
  Find printers: $RUN_PY $INSTALL_DIR/servora_agent.py discover
  Test printer : $RUN_PY $INSTALL_DIR/servora_agent.py test --address 192.168.1.50
  Restart      : sudo systemctl restart $SERVICE
MSG
