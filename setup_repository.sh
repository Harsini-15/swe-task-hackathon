#!/bin/bash
set -e

echo "Setting up repository..."
rm -rf /testbed
git clone https://github.com/internetarchive/openlibrary.git /testbed
cd /testbed
git config --global --add safe.directory /testbed

# Specific commit requirements from task.yaml
git reset --hard 84cc4ed5697b83a849e9106a09bfed501169cc20
git clean -fd
git checkout c4eebe6677acc4629cb541a98d5e91311444f5d4 -- openlibrary/tests/core/test_imports.py

# CRITICAL: Install web.py and other dependencies needed for OpenLibrary tests
echo "Installing base dependencies..."
pip install --upgrade pip
pip install web.py pytest-mock pyyaml anthropic requests
# OpenLibrary often needs these for conftest.py
pip install inflect psycopg2-binary
echo "Setup complete."
