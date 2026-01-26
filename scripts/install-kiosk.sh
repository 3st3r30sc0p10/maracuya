#!/bin/bash
# Install Maracuya Kiosk Mode
# Run this script once to set up auto-start on boot

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Installing Maracuya Kiosk Mode ==="

# Install unclutter to hide mouse cursor
echo "Installing unclutter..."
sudo apt-get update
sudo apt-get install -y unclutter

# Make kiosk script executable
chmod +x "$SCRIPT_DIR/kiosk.sh"

# Install systemd service for backend
echo "Installing backend service..."
sudo cp "$SCRIPT_DIR/maracuya-backend.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable maracuya-backend.service
sudo systemctl start maracuya-backend.service

# Install autostart for kiosk browser
echo "Installing kiosk autostart..."
mkdir -p ~/.config/autostart
cp "$SCRIPT_DIR/maracuya-kiosk.desktop" ~/.config/autostart/

# Disable screen blanking in lightdm (if using)
if [ -f /etc/lightdm/lightdm.conf ]; then
  echo "Configuring lightdm..."
  sudo sed -i 's/^#xserver-command=X$/xserver-command=X -s 0 -dpms/' /etc/lightdm/lightdm.conf
fi

# Disable screen blanking via raspi-config (non-interactive)
echo "Disabling screen blanking..."
sudo raspi-config nonint do_blanking 1 2>/dev/null || true

echo ""
echo "=== Installation Complete ==="
echo ""
echo "The backend will now auto-start on boot."
echo "The browser will launch in kiosk mode on login."
echo ""
echo "To check backend status:"
echo "  sudo systemctl status maracuya-backend"
echo ""
echo "To manually start kiosk browser now:"
echo "  $SCRIPT_DIR/kiosk.sh"
echo ""
echo "Reboot to test full auto-start:"
echo "  sudo reboot"
