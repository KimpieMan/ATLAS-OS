#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) == 0 ]]; then
  echo 'Start dit script als je gewone Pi-gebruiker, zonder sudo.' >&2
  exit 1
fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$project_dir"
atlas_user=$(id -un)
atlas_home=$(getent passwd "$atlas_user" | cut -d: -f6)
atlas_data="$atlas_home/.local/share/atlas"
# systemd directives need escaping for unusual paths. Fail clearly rather than generating an unsafe unit.
if [[ ! "$project_dir" =~ ^/[a-zA-Z0-9_./-]+$ || ! "$atlas_home" =~ ^/[a-zA-Z0-9_./-]+$ || ! "$atlas_user" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo 'Plaats ATLAS in een pad zonder spaties of speciale tekens, bijvoorbeeld ~/atlas-os.' >&2
  exit 1
fi
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip chromium
python3 -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/python" -m pip install -r "$project_dir/requirements.txt"
"$project_dir/.venv/bin/python" -m unittest discover -s "$project_dir/tests" -v
mkdir -p "$atlas_data" "$atlas_home/.config/autostart"
chmod 700 "$atlas_data"
unit_file=$(mktemp)
trap 'rm -f -- "$unit_file"' EXIT
cat > "$unit_file" <<EOF
[Unit]
Description=ATLAS OS local assistant
After=network.target

[Service]
Type=simple
User=$atlas_user
WorkingDirectory=$project_dir
Environment=HOME=$atlas_home
Environment=ATLAS_DATA=$atlas_data
Environment=ATLAS_PORT=8080
ExecStart=$project_dir/.venv/bin/python $project_dir/run.py
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$atlas_data
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 644 "$unit_file" /etc/systemd/system/atlas-os.service
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-os.service
cat > "$atlas_home/.config/autostart/atlas-os.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ATLAS OS
Exec=$project_dir/.venv/bin/python $project_dir/kiosk.py
Terminal=false
EOF
echo 'ATLAS is geïnstalleerd: http://127.0.0.1:8080'
echo 'Het dashboard opent fullscreen bij de volgende desktop-login.'
echo 'Activeer desktop auto-login via Raspberry Pi Configuration als je direct naar ATLAS wilt opstarten.'
