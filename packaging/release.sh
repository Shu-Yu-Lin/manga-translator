#!/bin/bash
# Ship the current branch to the pinned app: merge into main (in the stable worktree), sync deps, rebuild the .app, push main.
set -euo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"
STABLE="$HOME/manga-translator-stable"
BRANCH="$(git -C "$DEV" rev-parse --abbrev-ref HEAD)"
[ -z "$(git -C "$DEV" status --porcelain --untracked-files=no)" ] || { echo "Uncommitted changes in $BRANCH: commit first, they won't be merged."; exit 1; }
git -C "$STABLE" merge "$BRANCH"
(cd "$STABLE" && uv sync && ./packaging/build_app.sh)
git -C "$STABLE" push origin main
