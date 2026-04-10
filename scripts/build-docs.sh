#!/bin/bash
set -e

# Build Documentation Script
# Usage: ./scripts/build-docs.sh 

# Set BASE_URL for GitHub Pages
export BASE_URL=$REPOSITORY_NAME/docs

# Clean deployment directory
OUTPUT_DIR="${1:-.build/docs}"
rm -rf "$OUTPUT_DIR" && mkdir -p "$OUTPUT_DIR"

echo "🔨 Building Jupyter Book..."
cd docs && jupyter-book build --html
cd ..

# Copy custom index.html
cp -r docs/_index/* "$OUTPUT_DIR"

# Copy jupyter book output to docs subdirectory
cp -r docs/_build/html "$OUTPUT_DIR/docs"

touch "$OUTPUT_DIR/.nojekyll"

echo "✅ Documentation built successfully!"
