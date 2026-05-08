#!/usr/bin/env bash
# Push a filtered view of main to the 'releases' (GitHub) remote.
# Strips docs/superpowers/ (internal planning docs) before pushing.
# docs/HANDOFF.md is already untracked, so it's excluded automatically.
#
# Usage: bash scripts/push_github.sh
set -euo pipefail

REMOTE="releases"
TARGET_BRANCH="main"
TEMP_BRANCH="_github_push_$$"

cleanup() {
    git checkout main 2>/dev/null || true
    git branch -D "$TEMP_BRANCH" 2>/dev/null || true
}
trap cleanup EXIT

echo "▶ Creating filtered branch $TEMP_BRANCH from main ..."
git checkout -b "$TEMP_BRANCH"

echo "▶ Removing internal planning docs from release branch ..."
git rm -r --cached --ignore-unmatch docs/superpowers/

if ! git diff --cached --quiet; then
    git commit -m "chore: strip internal planning docs for public release"
fi

echo "▶ Pushing to $REMOTE/$TARGET_BRANCH ..."
git push "$REMOTE" "$TEMP_BRANCH:$TARGET_BRANCH" --force-with-lease

echo "✓ Done."
