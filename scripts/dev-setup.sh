#!/bin/bash
# StreamTube Development Environment Setup Script

set -e

echo "🚀 Setting up StreamTube development environment..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "⚠️  uv not found. Installing uv..."
    if command -v brew &> /dev/null; then
        brew install uv
    elif command -v curl &> /dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source $HOME/.cargo/env
    else
        echo "❌ Cannot install uv automatically. Please install uv first: https://docs.astral.sh/uv/"
        exit 1
    fi
fi

# Create virtual environment with uv
echo "📦 Creating virtual environment with uv..."
uv venv

# Install development dependencies
echo "📚 Installing dependencies with uv..."
if [ -f "pyproject.toml" ]; then
    uv pip install -e ".[dev,test]"
else
    # Fallback to requirements files
    uv pip install -r requirements.txt
    if [ -f "requirements-dev.txt" ]; then
        uv pip install -r requirements-dev.txt
    fi
fi

# Copy environment file if it doesn't exist
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "📋 Copying environment file..."
    cp .env.example .env
    echo "⚠️  Please review and update .env with your configuration"
fi

# Install pre-commit hooks if available
if command -v pre-commit &> /dev/null; then
    echo "🪝 Installing pre-commit hooks..."
    pre-commit install
fi

echo "✨ Development environment setup complete!"
echo ""
echo "Next steps:"
echo "  1. Review and update .env configuration"
echo "  2. Run: source .venv/bin/activate"
echo "  3. Run: ./scripts/dev-start.sh"