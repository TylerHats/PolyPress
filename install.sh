#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "==========================================="
echo "       PolyPress Installation Script       "
echo "==========================================="

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed. Please install Python 3.8+."
    exit 1
fi

echo "--> Setting up Python Virtual Environment (venv)..."
python3 -m venv venv
source venv/bin/activate

echo "--> Installing dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "--> PolyPress dependencies setup successfully!"

# Systemd Service Creation Option
echo ""
read -p "Would you like to configure PolyPress as a systemd background service? (y/n): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    CURR_USER=$(whoami)
    PROJ_ROOT=$(pwd)
    UVICORN_PATH="$PROJ_ROOT/venv/bin/uvicorn"
    WORKING_DIR="$PROJ_ROOT/backend"
    
    echo "--> Generating polypress.service config..."
    cat <<EOF > polypress.service
[Unit]
Description=PolyPress Newsletter Platform
After=network.target

[Service]
Type=simple
User=$CURR_USER
WorkingDirectory=$WORKING_DIR
ExecStart=$UVICORN_PATH main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

    echo "--> Installing service unit to systemd (sudo permission required)..."
    sudo cp polypress.service /etc/systemd/system/polypress.service
    sudo systemctl daemon-reload
    sudo systemctl enable polypress.service
    sudo systemctl start polypress.service
    rm -f polypress.service
    
    echo "--> PolyPress systemd service is active and enabled on boot!"
else
    echo "--> Skipping systemd service setup."
fi

echo ""
echo "==========================================="
echo "PolyPress setup completed successfully!"
echo "If systemd service was installed, the app is running."
echo "Otherwise, launch it manually with:"
echo "  source venv/bin/activate"
echo "  cd backend"
echo "  uvicorn main:app --host 0.0.0.0 --port 8000"
echo ""
echo "Open http://localhost:8000/ in your browser to begin onboarding."
echo "==========================================="
