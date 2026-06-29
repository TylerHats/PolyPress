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

echo "--> PolyPress setup successfully!"
echo ""
echo "To run the application:"
echo "  source venv/bin/activate"
echo "  cd backend"
echo "  uvicorn main:app --host 0.0.0.0 --port 8000"
echo ""
echo "Once running, open http://localhost:8000/ in your browser."
echo "You will be greeted by the onboarding setup wizard."
echo "==========================================="
