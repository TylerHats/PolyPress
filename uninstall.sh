#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "==========================================="
echo "       PolyPress Uninstallation Script     "
echo "==========================================="
echo "This script will cleanly remove PolyPress from your system."
echo ""

# 1. Stop and remove systemd service if exists
if [ -f /etc/systemd/system/polypress.service ]; then
    echo "--> Detected systemd service. Removing (sudo required)..."
    sudo systemctl stop polypress.service || true
    sudo systemctl disable polypress.service || true
    sudo rm -f /etc/systemd/system/polypress.service
    sudo systemctl daemon-reload
    echo "--> Systemd service successfully removed."
fi

# 2. Remove python virtual environment
if [ -d venv ]; then
    echo "--> Removing virtual environment (venv)..."
    rm -rf venv
fi

# 3. Clean python bytecode caches
echo "--> Cleaning python caches..."
find . -name "*.pyc" -delete || true
find . -name "__pycache__" -type d -exec rm -rf {} + || true

# 4. Optional database and certificate wipe
read -p "Would you like to delete the database and SSL certs? This will ERASE all subscriber list data! (y/n): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "--> Wiping database and certificates..."
    rm -f backend/polypress.db || true
    rm -rf certs/ || true
    echo "--> Database and local certs deleted."
else
    echo "--> Keeping database and certificates folder."
fi

echo ""
echo "==========================================="
echo "PolyPress has been uninstalled successfully."
echo "==========================================="
