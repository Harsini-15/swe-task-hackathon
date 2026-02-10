#!/bin/bash
set -e

REPO_URL="https://github.com/internetarchive/openlibrary.git"
TESTBED="/testbed"
BASE_COMMIT="84cc4ed5697b83a849e9106a09bfed501169cc20"
TEST_FILE_COMMIT="c4eebe6677acc4629cb541a98d5e91311444f5d4"

echo "Setting up repository in $TESTBED"

# Clean up existing testbed
rm -rf "$TESTBED"
mkdir -p "$TESTBED"

# Clone if not already cloned (though we just deleted it)
git clone "$REPO_URL" "$TESTBED"

cd "$TESTBED"

# Configure Git
git config --global --add safe.directory "$TESTBED"

# Reset to base commit
git reset --hard "$BASE_COMMIT"
git clean -fd

# Checkout the test file from the specific commit as per task requirements
git checkout "$TEST_FILE_COMMIT" -- openlibrary/tests/core/test_imports.py

echo "Repository setup complete."
