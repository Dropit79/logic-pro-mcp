#!/usr/bin/env bash
# The Formula's sha256 must be the hash of the release its own version names.
#
# #775: v3.15.0 shipped with the v3.14.0 hash still in the Formula, so every `brew install
# logic-pro-mcp` failed on the install path the README documents. `version` and `sha256` are one
# edit and only one of them was mechanically required — `Scripts/release-verify-formula-install-
# paths.sh` verifies this same file, but it checks the install PATHS and never looks at the hash.
#
# This is a CI step rather than a `check-*.py` on purpose. `run-repo-guards.py` has no network or
# GitHub-authentication contract, and the only way to know a hash is right is to ask the release
# what it published. So the network lives here, where CI already has it.
#
# Usage:
#   ci-verify-formula-sha.sh                       # fetch the named release from GitHub
#   ci-verify-formula-sha.sh <SHA256SUMS.txt>      # compare against a local file (used by the test)
#
# Test seams: LPM_GH_BIN, LPM_FORMULA_RETRY_DELAY, LPM_FORMULA_PATH and
# LPM_SERVER_CONFIG_PATH. The local sums argument checks only checksum agreement.
#
# The Formula always names a published stable archive. During source release preparation
# it may remain at the newest published version; once the source version is published,
# version and hash must move together. Unknown release states fail closed.
# Exit 0 clean, 1 mismatch/unavailable evidence, 2 unparseable local input.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# A named test seam rather than an argument, so the two things a caller passes stay "which sums" and
# nothing else. The self-test needs to point the rule at a Formula it wrote, and a guard that cannot
# be aimed at a fixture cannot be shown to fail.
FORMULA="${LPM_FORMULA_PATH:-$ROOT/Formula/logic-pro-mcp.rb}"
ASSET="LogicProMCP-macOS-universal.tar.gz"
LOCAL_SUMS="${1:-}"

[ -f "$FORMULA" ] || { echo "no Formula at $FORMULA"; exit 2; }

VERSION=$(grep -m1 -E '^[[:space:]]*version[[:space:]]+"' "$FORMULA" | sed -E 's/.*"([^"]+)".*/\1/')

# One artifact, one hash. Today the Formula ships a single universal tarball, and reading only the
# first `sha256` would be exactly right and would go on looking right if someone added an arm64
# block underneath — the second hash would never be compared to anything, silently, which is the
# same shape as the defect this guard exists for. Refuse instead of checking half.
SHA_LINES=$(grep -cE '^[[:space:]]*sha256[[:space:]]+"' "$FORMULA")
if [ "$SHA_LINES" -gt 1 ]; then
  echo "the Formula carries $SHA_LINES sha256 lines; this rule only understands one artifact."
  echo "Teach it which url each hash belongs to before adding another, or it will check one and"
  echo "ignore the rest."
  exit 2
fi

PINNED=$(grep -m1 -E '^[[:space:]]*sha256[[:space:]]+"' "$FORMULA" | sed -E 's/.*"([0-9a-f]{64})".*/\1/')

[ -n "$VERSION" ] || { echo "could not read version from the Formula"; exit 2; }
printf '%s' "$PINNED" | grep -qE '^[0-9a-f]{64}$' || { echo "could not read a sha256 from the Formula"; exit 2; }

if [ -n "$LOCAL_SUMS" ]; then
  [ -f "$LOCAL_SUMS" ] || { echo "no such sums file: $LOCAL_SUMS"; exit 2; }
  SUMS=$(cat "$LOCAL_SUMS")
else
  # A named seam so the classification below can be driven by a fake `gh` that prints a chosen
  # status. Without it the only way to test a 403 is to have one.
  GH="${LPM_GH_BIN:-gh}"
  command -v "$GH" >/dev/null 2>&1 || { echo "gh is not available, so the Formula's hash could not be checked"; exit 1; }
  SLUG="${GITHUB_REPOSITORY:-MongLong0214/logic-pro-mcp}"
  RETRY_DELAY="${LPM_FORMULA_RETRY_DELAY:-2}"

  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT

  CONFIG="${LPM_SERVER_CONFIG_PATH:-$ROOT/Sources/LogicProMCP/Server/ServerConfig.swift}"
  SOURCE_VERSION=$(sed -nE 's/.*static let serverVersion = "([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p' "$CONFIG")
  printf '%s' "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "invalid Formula version"; exit 2; }
  printf '%s' "$SOURCE_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "could not read source version"; exit 2; }

  # Only transient transport/server failures are retried. Auth failures are not absence.
  lookup() {
    local endpoint="$1" attempt
    for attempt in 1 2 3; do
      RESP=$("$GH" api "repos/$SLUG/releases/$endpoint" -i 2>"$TMP/gh-err") || true
      STATUS=$(printf '%s\n' "$RESP" | head -1 | awk '{print $2}')
      case "$STATUS" in
        5??|"") if [ "$attempt" -lt 3 ]; then sleep "$RETRY_DELAY"; continue; fi ;;
      esac
      break
    done
  }

  # An authenticated lookup can return a draft with HTTP 200. That is not a
  # published archive. Parse the response body rather than inferring publication from status.
  release_state() {
    printf '%s\n' "$RESP" | python3 -c '
import json, re, sys
try:
    body = re.split(r"\r?\n\r?\n", sys.stdin.read(), maxsplit=1)[1]
    release = json.loads(body)
    version = release["tag_name"].removeprefix("v")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version): raise ValueError("invalid tag")
    if type(release["draft"]) is not bool or release["prerelease"] is not False:
        raise ValueError("not a stable release")
    if release["draft"]:
        if release["published_at"] is not None: raise ValueError("draft has publication date")
        state = "draft"
    else:
        if not isinstance(release["published_at"], str) or not release["published_at"]:
            raise ValueError("missing publication date")
        state = "published"
    print(state, version)
except (KeyError, IndexError, TypeError, ValueError):
    sys.exit(1)
'
  }

  lookup "tags/v$VERSION"
  if [ "$STATUS" != "200" ]; then
    echo "Formula v$VERSION has no confirmed published release (HTTP ${STATUS:-none}); its hash could not be checked."
    exit 1
  fi
  STATE=$(release_state) || { echo "Formula release metadata could not be read"; exit 1; }
  [ "$STATE" = "published $VERSION" ] || { echo "Formula v$VERSION does not name a published stable release"; exit 1; }

  if [ "$VERSION" != "$SOURCE_VERSION" ]; then
    NEWEST=$(printf '%s\n%s\n' "$VERSION" "$SOURCE_VERSION" | sort -V | tail -1)
    [ "$NEWEST" = "$SOURCE_VERSION" ] || { echo "Formula v$VERSION is newer than source v$SOURCE_VERSION"; exit 1; }
    lookup latest
    [ "$STATUS" = "200" ] || { echo "latest release could not be read (HTTP ${STATUS:-none})"; exit 1; }
    STATE=$(release_state) || { echo "latest release metadata could not be read"; exit 1; }
    [ "$STATE" = "published $VERSION" ] || { echo "Formula v$VERSION is not the newest published stable release ($STATE)"; exit 1; }
    lookup "tags/v$SOURCE_VERSION"
    case "$STATUS" in
      404) : ;;
      200)
        STATE=$(release_state) || { echo "source release metadata could not be read"; exit 1; }
        [ "$STATE" = "draft $SOURCE_VERSION" ] || {
          echo "source v$SOURCE_VERSION is published; update Formula version and SHA256 together"
          exit 1
        } ;;
      *) echo "source release could not be checked (HTTP ${STATUS:-none})"; exit 1 ;;
    esac
  fi

  if ! "$GH" release download "v$VERSION" -p 'SHA256SUMS.txt' -O "$TMP/sums.txt" --clobber >/dev/null 2>&1; then
    echo "v$VERSION exists but its SHA256SUMS.txt could not be downloaded, so the Formula's hash"
    echo "could not be checked. That is a failure rather than a pass: the release is there and the"
    echo "check could not be made."
    exit 1
  fi
  SUMS=$(cat "$TMP/sums.txt")
fi

# `head -1` used to pick the first of however many rows named this asset. A manifest with the
# asset twice is a manifest nobody can read as one answer, and silently taking the first is the
# same shape as the defect above: a state that cannot be resolved, resolved anyway.
MATCHES=$(printf '%s\n' "$SUMS" | awk -v a="$ASSET" '$2 == a || $2 == "*" a {print $1}')
COUNT=$(printf '%s\n' "$MATCHES" | grep -c . || true)

if [ "$COUNT" = "0" ]; then
  echo "v$VERSION publishes no $ASSET, so the Formula names an artifact that is not there"
  exit 1
fi
if [ "$COUNT" -gt 1 ]; then
  echo "the manifest lists $ASSET $COUNT times. Which hash is the artifact's is not a question this"
  echo "rule may answer by taking the first one."
  exit 1
fi
PUBLISHED=$(printf '%s\n' "$MATCHES" | head -1)
if ! printf '%s' "$PUBLISHED" | grep -qE '^[0-9a-f]{64}$'; then
  echo "the manifest's hash for $ASSET is not 64 hex characters: '$PUBLISHED'"
  exit 1
fi

if [ "$PINNED" != "$PUBLISHED" ]; then
  echo "Formula/logic-pro-mcp.rb pins a hash that is not v$VERSION's $ASSET:"
  echo "  Formula pins  $PINNED"
  echo "  v$VERSION has $PUBLISHED"
  echo
  echo "brew install fails for everyone until these agree. Copy the published hash into the Formula,"
  echo "or bump the version to the release the hash belongs to."
  exit 1
fi

echo "Formula sha256 matches v$VERSION's $ASSET"
exit 0
