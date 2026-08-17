#!/usr/bin/env bash
# راه‌اندازی یک‌باره‌ی PowerMatch روی سرور اوبونتو (۲۲.۰۴ یا ۲۴.۰۴).
# اجرا با کاربر root:   bash setup_server.sh
set -euo pipefail

APP_DIR=/opt/powermatch
APP_USER=powermatch

echo "▶ نصب پیش‌نیازها"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git tzdata

id -u "$APP_USER" &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"

echo "▶ کپی کد در $APP_DIR (اگر از قبل کپی نشده، فایل‌ها را خودتان منتقل کنید)"
[ -d "$APP_DIR/app" ] || { echo "⛔️ پوشه‌ی app در $APP_DIR نیست. اول پروژه را آپلود کنید."; exit 1; }

echo "▶ ساخت محیط مجازی و نصب کتابخانه‌ها"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "▶ تنظیم منطقه‌ی زمانی روی تهران (برای ساعت یادآوری‌ها)"
timedatectl set-timezone Asia/Tehran || true

[ -f "$APP_DIR/.env" ] || { cp "$APP_DIR/.env.example" "$APP_DIR/.env"; echo "⚠️ .env را پر کنید."; }
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"
[ -f "$APP_DIR/google_credentials.json" ] && chmod 600 "$APP_DIR/google_credentials.json"

echo "▶ نصب سرویس systemd"
cp "$APP_DIR/deploy/powermatch.service" /etc/systemd/system/powermatch.service
systemctl daemon-reload
systemctl enable --now powermatch

echo "✅ انجام شد. وضعیت:"
systemctl --no-pager status powermatch || true
echo "لاگ زنده:  journalctl -u powermatch -f"
