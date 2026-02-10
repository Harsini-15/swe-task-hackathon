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

# CRITICAL: Install all missing dependencies required by OpenLibrary conftest.py
echo "Installing base dependencies..."
pip install --upgrade pip
pip install web.py pytest-mock pyyaml anthropic requests inflect psycopg2-binary
# Infogami is an Internet Archive library, we install it from the repository directly if possible or via PyPI
pip install infogami 

# Sometimes dependencies are in the vendor folder or need to be installed from requirements
if [ -f requirements.txt ]; then
    pip install -r requirements.txt || echo "Some requirements failed to install, proceeding..."
fi

echo "Setup complete."
