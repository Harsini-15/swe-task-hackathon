#!/bin/bash
set -e

echo "Setting up repository..."
rm -rf /testbed
git clone https://github.com/internetarchive/openlibrary.git /testbed
cd /testbed
git config --global --add safe.directory /testbed

# RESET to the exact base commit to ensure a clean PRE-verification
git reset --hard 84cc4ed5697b83a849e9106a09bfed501169cc20
git clean -fd
# Checkout the specific test file for this task
git checkout c4eebe6677acc4629cb541a98d5e91311444f5d4 -- openlibrary/tests/core/test_imports.py

# Install all dependencies needed for the tests to run
echo "Installing dependencies..."
pip install --upgrade pip
pip install web.py pytest-mock pyyaml anthropic requests inflect psycopg2-binary simplejson ujson cached-property python-memcached
pip install git+https://github.com/internetarchive/infogami.git || echo "Infogami found or failed"

echo "Setup complete."
