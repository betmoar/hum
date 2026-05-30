#!/bin/bash
# StreamTube Testing Script

set -e

echo "🧪 Running StreamTube tests..."

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found. Run ./scripts/dev-setup.sh first"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Create tests directory if it doesn't exist
if [ ! -d "tests" ]; then
    echo "📁 Creating tests directory..."
    mkdir -p tests
    touch tests/__init__.py
    echo "⚠️  No tests found. Create test files in the tests/ directory."
    exit 0
fi

# Run tests with pytest
echo "🔬 Running tests with pytest..."
if [ "$1" = "--cov" ]; then
    pytest tests/ --cov=app --cov-report=term-missing --cov-report=html
else
    pytest tests/ -v
fi

echo "✅ Tests completed!"