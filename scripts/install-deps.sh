#!/bin/bash
# Install AgentFS dependencies
# This script checks for and installs required FUSE dependencies

set -e

echo "Checking AgentFS dependencies..."

# Check if we're on Linux or macOS
case "$(uname -s)" in
    Linux)
        echo "Detected Linux system"
        
        # Check if libfuse3-dev is installed
        if ! dpkg -l | grep -q libfuse3-dev; then
            echo "Installing libfuse3-dev and python3-dev..."
            sudo apt-get update
            sudo apt-get install -y libfuse3-dev python3-dev
        else
            echo "✓ libfuse3-dev already installed"
        fi
        
        # Check if pyfuse3 is installed
        if ! python3 -c "import fuse" 2>/dev/null; then
            echo "Installing pyfuse3..."
            pip install pyfuse3
        else
            echo "✓ pyfuse3 already installed"
        fi
        ;;
    Darwin)
        echo "Detected macOS system"
        
        # Check if macfuse is installed
        if ! pkgutil --pkg-info=com.github.macfuse.pkg.macfuse 2>/dev/null; then
            echo "macFUSE not found. Please install from https://macfuse.github.io/"
            echo "Or use: brew install macfuse"
            exit 1
        else
            echo "✓ macFUSE already installed"
        fi
        
        # Check if pyfuse3 is installed
        if ! python3 -c "import fuse" 2>/dev/null; then
            echo "Installing pyfuse3..."
            pip install pyfuse3
        else
            echo "✓ pyfuse3 already installed"
        fi
        ;;
    *)
        echo "Unsupported system: $(uname -s)"
        exit 1
        ;;
esac

echo ""
echo "Dependencies installed successfully!"
echo ""
echo "To install AgentFS:"
echo "  cd agentfs && pip install -e ."
echo ""
echo "To verify installation:"
echo "  agentfs --help"
