#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
mkdir -p "$apps" "$icons"
cp "$here/kz.jobfiller.Agent.svg" "$icons/kz.jobfiller.Agent.svg"
cat > "$apps/kz.jobfiller.Agent.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Job agent
Comment=See what the job agent sent and what needs you
Exec=/usr/bin/python3 "$here/job_agent.py"
Icon=kz.jobfiller.Agent
Terminal=false
Categories=Office;
StartupNotify=true
StartupWMClass=kz.jobfiller.Agent
DESKTOP
update-desktop-database "$apps" >/dev/null 2>&1 || true
gtk-update-icon-cache -q -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
echo "Installed Job agent; find it in Activities."
