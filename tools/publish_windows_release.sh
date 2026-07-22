#!/usr/bin/env bash
# Commit the current VFX Texture Lab release, build Windows packages on GitHub,
# and publish the resulting draft release after a final confirmation.

set -Eeuo pipefail

WORKFLOW_FILE="windows-release.yml"
BRANCH="main"
AUTO_YES=0
OPEN_BROWSER=1

usage() {
  cat <<'USAGE'
Usage: ./tools/publish_windows_release.sh [options]

Options:
  -y, --yes        Skip confirmations and publish automatically after a successful build.
      --no-browser Do not open the published GitHub Release in a browser.
  -h, --help       Show this help.

Before running, update:
  - project.version in pyproject.toml
  - __version__ in vfx_texture_lab/__init__.py
  - the matching "## <version>" section in CHANGELOG.md

With no options, the script shows what will be committed and asks before the
commit and again before publishing the successfully built draft release.
USAGE
}

while (($#)); do
  case "$1" in
    -y|--yes)
      AUTO_YES=1
      shift
      ;;
    --no-browser)
      OPEN_BROWSER=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

fail() {
  echo >&2
  echo "ERROR: $*" >&2
  exit 1
}

confirm() {
  local prompt="$1"
  if ((AUTO_YES)); then
    return 0
  fi
  local reply
  read -r -p "$prompt [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

command -v git >/dev/null 2>&1 || fail "git is not installed."
command -v gh >/dev/null 2>&1 || fail "GitHub CLI (gh) is not installed."
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed."

gh auth status >/dev/null 2>&1 || fail "GitHub CLI is not logged in. Run: gh auth login"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "Run this inside the VFXTextureLab Git repository."
cd "$REPO_ROOT"

CURRENT_BRANCH="$(git branch --show-current)"
[[ "$CURRENT_BRANCH" == "$BRANCH" ]] || fail "Release from '$BRANCH', not '$CURRENT_BRANCH'."

[[ -f tools/windows_release.py ]] || fail "tools/windows_release.py is missing."
[[ -f .github/workflows/$WORKFLOW_FILE ]] || fail ".github/workflows/$WORKFLOW_FILE is missing."
[[ -f CHANGELOG.md ]] || fail "CHANGELOG.md is missing."

git diff --check || fail "Git found whitespace/conflict-marker errors."

METADATA="$(python3 tools/windows_release.py metadata)" || fail "Release metadata validation failed."
VERSION="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' <<<"$METADATA")"
TAG="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tag"])' <<<"$METADATA")"
PORTABLE="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["portable_filename"])' <<<"$METADATA")"
INSTALLER="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["installer_filename"])' <<<"$METADATA")"
CHECKSUMS="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["checksum_filename"])' <<<"$METADATA")"

python3 - "$VERSION" <<'PY' || fail "CHANGELOG.md has no matching section for version $VERSION."
from pathlib import Path
import re
import sys
version = sys.argv[1]
text = Path("CHANGELOG.md").read_text(encoding="utf-8")
if not re.search(rf"^##\s+{re.escape(version)}(?:\s|$)", text, re.MULTILINE):
    raise SystemExit(1)
PY

# Do not overwrite an already published version.
if RELEASE_DRAFT="$(gh release view "$TAG" --json isDraft --jq .isDraft 2>/dev/null)"; then
  [[ "$RELEASE_DRAFT" == "true" ]] || fail "$TAG is already published. Increase the version before making another release."
elif git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then
  fail "Remote tag $TAG already exists without an editable draft release. Increase the version or resolve the tag manually."
fi

echo
echo "Preparing VFX Texture Lab $VERSION ($TAG)"
echo "Branch: $BRANCH"
echo

git status --short

if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo
  confirm "Commit every change shown above as 'Release $VERSION'?" || fail "Release cancelled before commit."
  git add -A
  git commit -m "Release $VERSION"
else
  echo "Working tree is already clean; releasing the current commit."
fi

git push origin "$BRANCH"
HEAD_SHA="$(git rev-parse HEAD)"

echo
echo "Starting the Windows build and draft release..."
DISPATCH_OUTPUT="$(gh workflow run "$WORKFLOW_FILE" --ref "$BRANCH" -f mode=draft-release 2>&1)" || {
  echo "$DISPATCH_OUTPUT" >&2
  fail "Could not start the GitHub Actions workflow."
}
echo "$DISPATCH_OUTPUT"

RUN_URL="$(grep -Eo 'https://[^[:space:]]+/actions/runs/[0-9]+' <<<"$DISPATCH_OUTPUT" | tail -n 1 || true)"
RUN_ID="${RUN_URL##*/}"

# Some gh versions may not print a URL. Fall back to locating the new run by
# its exact commit SHA.
if [[ -z "$RUN_ID" || "$RUN_ID" == "$RUN_URL" ]]; then
  for _ in {1..20}; do
    RUN_ID="$(gh run list \
      --workflow "$WORKFLOW_FILE" \
      --event workflow_dispatch \
      --branch "$BRANCH" \
      --limit 20 \
      --json databaseId,headSha \
      --jq ".[] | select(.headSha == \"$HEAD_SHA\") | .databaseId" \
      | head -n 1)"
    [[ -n "$RUN_ID" ]] && break
    sleep 2
  done
fi

[[ -n "$RUN_ID" ]] || fail "The workflow started, but its run ID could not be found."

echo
echo "Watching GitHub Actions run $RUN_ID..."
gh run watch "$RUN_ID" --compact --exit-status || fail "Windows build failed. No release was published."

# The final workflow step creates or updates a draft release. Allow a brief
# delay for the release API to become visible.
for _ in {1..15}; do
  if RELEASE_DRAFT="$(gh release view "$TAG" --json isDraft --jq .isDraft 2>/dev/null)"; then
    break
  fi
  sleep 2
done
[[ "${RELEASE_DRAFT:-}" == "true" ]] || fail "The build passed, but draft release $TAG was not found."

ASSET_NAMES="$(gh release view "$TAG" --json assets --jq '.assets[].name')"
for expected in "$PORTABLE" "$INSTALLER" "$CHECKSUMS"; do
  grep -Fxq "$expected" <<<"$ASSET_NAMES" || fail "Draft release is missing $expected."
done

echo
echo "Windows build passed and the draft release contains:"
printf '  %s\n' "$PORTABLE" "$INSTALLER" "$CHECKSUMS"
echo

confirm "Publish $TAG publicly and mark it as the latest release?" || {
  echo "Left $TAG as a draft. Publish later with:"
  echo "  gh release edit '$TAG' --draft=false --latest"
  exit 0
}

gh release edit "$TAG" --draft=false --latest >/dev/null

echo
echo "Published VFX Texture Lab $VERSION successfully."
if ((OPEN_BROWSER)); then
  gh release view "$TAG" --web
else
  gh release view "$TAG"
fi
