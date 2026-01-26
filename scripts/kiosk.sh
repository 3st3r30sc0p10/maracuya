#!/bin/bash
# Maracuya Kiosk Mode Launcher
# Launches Chromium in fullscreen kiosk mode

# Wait for backend to be ready
sleep 5

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Hide mouse cursor after 1 second of inactivity
unclutter -idle 1 &

# Kill any existing Chromium instances
pkill -f chromium || true
sleep 1

# Launch Chromium in kiosk mode
chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-restore-session-state \
  --disable-translate \
  --no-first-run \
  --fast \
  --fast-start \
  --disable-features=TranslateUI \
  --check-for-update-interval=31536000 \
  --disable-component-update \
  --overscroll-history-navigation=0 \
  --disable-pinch \
  --incognito \
  http://localhost:8000
