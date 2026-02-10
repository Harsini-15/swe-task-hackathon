#!/bin/bash
set -e

# Repository Setup for SWE-bench Pro Task: internetarchive__openlibrary-c4eebe6677acc4629cb541a98d5e91311444f5d4
echo "Starting repository setup..."

# 1. Clean and Clone
rm -rf /testbed
git clone https://github.com/internetarchive/openlibrary.git /testbed
cd /testbed

# 2. Reset to the exact task commit
echo "Resetting to base commit 84cc4ed5697b83a849e9106a09bfed501169cc20..."
git reset --hard 84cc4ed5697b83a849e9106a09bfed501169cc20
git clean -fd

# 3. Checkout specific test file (which might have been introduced or modified later)
echo "Checking out task-specific tests..."
git checkout c4eebe6677acc4629cb541a98d5e91311444f5d4 -- openlibrary/tests/core/test_imports.py

# 4. Environment Readiness
echo "Installing necessary dependencies for the OpenLibrary environment..."
pip install --upgrade pip
# Install standard dependencies + AI requirement (anthropic)
pip install web.py pytest-mock pyyaml anthropic requests inflect psycopg2-binary simplejson ujson cached-property python-memcached
# Infogami installation
pip install git+https://github.com/internetarchive/infogami.git || echo "Infogami found or failed install, continuing..."

echo "Setup repository step completed successfully."
