#!/usr/bin/env bash
# Publish plugins/ subtree → standalone plugins-origin repo.
#
# Run from monorepo root. This is what makes new plugin work available
# to users who install via `sam plugin catalog`. Daily commits land in
# the monorepo without publishing; run this script when you're ready
# to release a new state of plugins to the catalog.
#
# Usage:
#   ./scripts/publish-plugins.sh                # default: plugins-origin, main
#   REMOTE=plugins-origin BRANCH=main ./scripts/publish-plugins.sh

set -euo pipefail

BRANCH="${BRANCH:-main}"
REMOTE="${REMOTE:-plugins-origin}"

# Refuse if root has uncommitted changes — publishing a half-state
# breaks archeology (you'd push content that doesn't match any root SHA).
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree dirty. Commit (or stash) before publishing." >&2
  exit 1
fi

# Verify the remote exists.
if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "Remote '$REMOTE' not configured. Add it with:" >&2
  echo "  git remote add $REMOTE <plugins-repo-URL>" >&2
  exit 1
fi

ROOT_SHA=$(git rev-parse --short HEAD)
echo "Publishing plugins/ subtree from monorepo @ $ROOT_SHA"
echo "  remote: $(git remote get-url "$REMOTE")"
echo "  branch: $BRANCH"

git subtree push --prefix=plugins "$REMOTE" "$BRANCH"
echo "Published. $REMOTE/$BRANCH updated."
