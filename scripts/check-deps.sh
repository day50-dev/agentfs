#!/bin/bash
# Check StackedFS dependencies
# This script verifies that all required dependencies are installed

set -e

echo "Checking StackedFS dependencies..."

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
echo "Python version: $PYTHON_VERSION"
if [[ ! "$PYTHON_VERSION" =~ ^3\.[8-9] ]] && [[ ! "$PYTHON_VERSION" =~ ^3\.1[0-9] ]]; then
    echo "⚠ Warning: StackedFS requires Python 3.8+"
fi

# Check if FUSE is available
if ! command -v pkg-config &> /dev/null; then
    echo "✗ pkg-config not found"
    exit 1
fi

if ! pkg-config --exists fuse3; then
    echo "✗ fuse3 not found"
    echo "  Linux: sudo apt-get install libfuse3-dev"
    echo "  macOS: brew install macfuse"
    exit 1
else
    echo "✓ fuse3 found"
fi

# Check if pyfuse3 is installed
if ! python3 -c "import fuse" 2>/dev/null; then
    echo "✗ pyfuse3 not installed"
    echo "  pip install pyfuse3"
    exit 1
else
    echo "✓ pyfuse3 installed"
fi

echo ""
echo "All dependencies satisfied!"
