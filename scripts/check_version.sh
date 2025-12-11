#!/usr/bin/env bash

# This script checks if the version in pyproject.toml matches the Git tag name.
# This prevents accidental releases with mismatched versions.

version=$(grep -E '^version\s*=' pyproject.toml | sed -E 's/^version\s*=\s*"([^"]+)".*/\1/')

tag="${GITHUB_REF_NAME}"

echo "Detected version in pyproject.toml: $version"
echo "Detected tag name: $tag"

# Compare them
if [ "$version" != "$tag" ]; then
  echo "❌ Tag ($tag) does not match version in pyproject.toml ($version)"
  exit 1
fi

echo "✅ Tag matches version. Proceeding with release..."
