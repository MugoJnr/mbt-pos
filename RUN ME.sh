#!/bin/bash
# =====================================================
#   MBT POS SYSTEM — MugoByte Technologies
#   mugobyte.com
# =====================================================

echo ""
echo "  ====================================================="
echo "    MBT POS SYSTEM — MugoByte Technologies"
echo "    mugobyte.com"
echo "  ====================================================="
echo ""

# Go to the script's directory
cd "$(dirname "$0")"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  [ERROR] python3 not found. Install Python 3.9+ first."
    exit 1
fi

echo "  [1/3] Checking dependencies..."
python3 -m pip install flask pyjwt requests openpyxl PyQt5 werkzeug --quiet 2>/dev/null

echo "  [2/3] Starting MBT POS..."
echo ""

python3 launcher.py

if [ $? -ne 0 ]; then
    echo ""
    echo "  [ERROR] MBT POS exited with an error."
    echo "  Check logs/launcher.log for details."
    read -p "  Press Enter to close..."
fi
