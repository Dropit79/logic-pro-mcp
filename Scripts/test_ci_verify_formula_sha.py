#!/usr/bin/env python3
"""Prove `Scripts/ci-verify-formula-sha.sh` can fail, without a network.

The network branch IS covered now, through a fake `gh` (`LPM_GH_BIN`) that prints a chosen HTTP
status line. That branch used to classify every failure of `gh release view` as "not published yet"
and exit 0 -- an expired token, a 403, a rate limit and a 502 all read as "fine". The docstring here
said the branch was not covered, and the thing it was not covering was wrong.

What is still NOT covered, stated rather than implied by silence: the real `gh release download`
against a real release, and therefore the bytes of a real SHA256SUMS.txt. The fake stops at the
status classification and hands the sums in directly from there.

The guard exists because a hash was copied by hand and nothing compared the copy to the release it
named. A test that only ever sees the repository in its correct state would repeat that mistake one
level up, so every case below writes a Formula and a sums file and requires a specific exit code.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "ci-verify-formula-sha.sh"
ASSET = "LogicProMCP-macOS-universal.tar.gz"
GOOD = "0776b0d257606460164b3e197f6542223c9d0657501f97e96f5f9a250b994788"
OTHER = "0a0e221cadb7f61b28b77c97ade70650d41ef09cee47394914030c2a66a1a45e"


def _formula(version, sha):
    return (f'class LogicProMcp < Formula\n'
            f'  version "{version}"\n'
            f'  on_macos do\n'
            f'    sha256 "{sha}"\n'
            f'  end\n'
            f'end\n')


def _run(formula_text, sums_text, sums_name="sums.txt"):
    """Run the guard over a written Formula and sums file; return (exit code, output)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        formula = root / "logic-pro-mcp.rb"
        formula.write_text(formula_text, encoding="utf-8")
        sums = root / sums_name
        if sums_text is not None:
            sums.write_text(sums_text, encoding="utf-8")
        env = dict(os.environ, LPM_FORMULA_PATH=str(formula))
        proc = subprocess.run(["bash", str(GUARD), str(sums)],
                              capture_output=True, text=True, env=env)
        return proc.returncode, proc.stdout + proc.stderr


FAKE_GH = r"""#!/usr/bin/env bash
if [ "$1" = "api" ]; then
  if [ -n "${FAKE_STDERR:-}" ]; then printf '%s\n' "$FAKE_STDERR" >&2; fi
  status="${FAKE_STATUS:-}"
  body="$FAKE_RELEASE_BODY"
  case "${2:-}" in
    */releases/latest) status="${FAKE_LATEST_STATUS:-200}"; body="$FAKE_LATEST_BODY" ;;
    */releases/tags/v"$FAKE_SOURCE_VERSION")
      if [ "$FAKE_SOURCE_VERSION" != "$FAKE_FORMULA_VERSION" ]; then
        status="$FAKE_SOURCE_STATUS"; body="$FAKE_SOURCE_BODY"
      fi ;;
  esac
  if [ -n "$status" ]; then
    printf 'HTTP/2.0 %s Fake\ncontent-type: application/json\n\n%s\n' "$status" "$body"
  fi
  [ "$status" = "200" ] && exit 0
  exit 1
fi
if [ -n "${FAKE_SUMS:-}" ]; then
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "-O" ]; then printf '%s' "$FAKE_SUMS" > "$2"; exit 0; fi
    shift
  done
fi
exit 1
"""


def _release(tag, draft=False):
    import json
    return json.dumps({"tag_name": tag, "draft": draft, "prerelease": False,
                       "published_at": None if draft else "2026-09-28T13:26:55Z"})


def _run_network(formula_text, status, sums=None, stderr="", release_prep=False,
                 latest_tag=None, latest_status=None, source_version=None,
                 source_status=404, draft=False, source_draft=False):
    """Run the guard's NETWORK branch against a fake `gh`; return (exit code, output).

    No local sums argument, so the rule takes the branch that asks GitHub. The fake is what makes
    that branch reachable offline -- and the only way a 401/429/5xx case exists at all.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        formula = root / "logic-pro-mcp.rb"
        formula.write_text(formula_text, encoding="utf-8")
        version = re.search(r'version "([^"]+)"', formula_text).group(1)
        source_version = source_version or version
        config = root / "ServerConfig.swift"
        config.write_text(f'static let serverVersion = "{source_version}"\n', encoding="utf-8")
        fake = root / "gh"
        fake.write_text(FAKE_GH, encoding="utf-8")
        fake.chmod(0o755)
        env = dict(os.environ,
                   LPM_FORMULA_PATH=str(formula),
                   LPM_GH_BIN=str(fake),
                   LPM_SERVER_CONFIG_PATH=str(config),
                   FAKE_FORMULA_VERSION=version,
                   FAKE_SOURCE_VERSION=source_version,
                   FAKE_RELEASE_BODY=_release("v" + version, draft),
                   FAKE_SOURCE_STATUS=str(source_status),
                   FAKE_SOURCE_BODY=_release("v" + source_version, source_draft),
                   FAKE_LATEST_BODY=_release(latest_tag or "v" + version),
                   LPM_FORMULA_RETRY_DELAY="0",
                   FAKE_STATUS=str(status),
                   FAKE_STDERR=stderr)
        env.pop("FAKE_SUMS", None)
        env.pop("LPM_FORMULA_RELEASE_PREPARATION", None)
        env.pop("FAKE_LATEST_TAG", None)
        env.pop("FAKE_LATEST_STATUS", None)
        if latest_tag is not None:
            env["FAKE_LATEST_TAG"] = latest_tag
        if latest_status is not None:
            env["FAKE_LATEST_STATUS"] = str(latest_status)
        if sums is not None:
            env["FAKE_SUMS"] = sums
        if release_prep:
            env["LPM_FORMULA_RELEASE_PREPARATION"] = "1"
        proc = subprocess.run(["bash", str(GUARD)], capture_output=True, text=True, env=env)
        return proc.returncode, proc.stdout + proc.stderr


def main():
    failures = []
    checks = 0

    def check(name, condition, detail):
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(f"{name}: {detail}")

    sums = f"{GOOD}  {ASSET}\n"

    # 1. Agreement passes.
    rc, out = _run(_formula("3.15.0", GOOD), sums)
    check("agreement passes", rc == 0, f"exit {rc}: {out.strip()[:200]}")

    # 2. THE DEFECT: the previous release's hash left behind. This is #775 exactly.
    rc, out = _run(_formula("3.15.0", OTHER), sums)
    check("stale hash is caught", rc == 1, f"exit {rc}: {out.strip()[:200]}")
    check("stale hash names both hashes", OTHER in out and GOOD in out,
          f"the message must show what is pinned and what is published: {out.strip()[:200]}")

    # 3. The release publishes no such asset — the Formula names something that is not there.
    rc, out = _run(_formula("3.15.0", GOOD), f"{GOOD}  SomethingElse.tar.gz\n")
    check("missing asset is caught", rc == 1, f"exit {rc}: {out.strip()[:200]}")

    # 4. A Formula the rule cannot read is exit 2 — unparseable is not clean.
    rc, out = _run('class LogicProMcp < Formula\n  version "3.15.0"\nend\n', sums)
    check("no sha256 is exit 2", rc == 2, f"exit {rc}: {out.strip()[:200]}")

    rc, out = _run(f'class LogicProMcp < Formula\n  sha256 "{GOOD}"\nend\n', sums)
    check("no version is exit 2", rc == 2, f"exit {rc}: {out.strip()[:200]}")

    # 5. A sums file that is not there is exit 2, not a pass. "Could not ask" and "the answer was
    #    yes" being the same outcome is the shape of defect this guard exists to stop.
    rc, out = _run(_formula("3.15.0", GOOD), None)
    check("absent sums is not a pass", rc == 2, f"exit {rc}: {out.strip()[:200]}")

    # 6. A `*`-prefixed name, which shasum writes in binary mode, is the same asset.
    rc, out = _run(_formula("3.15.0", GOOD), f"{GOOD} *{ASSET}\n")
    check("binary-mode sums line is understood", rc == 0, f"exit {rc}: {out.strip()[:200]}")

    # 8. Two hashes means the rule would check one and ignore the other — refuse, do not half-check.
    two = (f'class LogicProMcp < Formula\n  version "3.15.0"\n'
           f'  on_macos do\n    sha256 "{GOOD}"\n  end\n'
           f'  on_arm do\n    sha256 "{OTHER}"\n  end\nend\n')
    rc, out = _run(two, sums)
    check("two hashes is exit 2", rc == 2, f"exit {rc}: {out.strip()[:200]}")

    # 9. The manifest names the asset twice. Taking the first is the shape this guard is about.
    rc, out = _run(_formula("3.15.0", GOOD), f"{GOOD}  {ASSET}\n{OTHER}  {ASSET}\n")
    check("a duplicated asset row is refused", rc == 1, f"exit {rc}: {out.strip()[:200]}")

    # 10. A manifest hash that is not a sha256 at all. Exit 1 alone does not prove this case:
    #     the mismatch branch below it also exits 1, so a run with the shape check removed would
    #     still be red for the wrong reason. The MESSAGE is what separates the two.
    rc, out = _run(_formula("3.15.0", GOOD), f"not-a-hash  {ASSET}\n")
    check("a malformed manifest hash is refused", rc == 1, f"exit {rc}: {out.strip()[:200]}")
    check("a malformed manifest hash is refused AS malformed", "64 hex" in out,
          f"this must not pass through the mismatch branch: {out.strip()[:200]}")

    # --- The network branch. THE defect: every one of these used to exit 0. ---
    formula = _formula("3.15.0", GOOD)
    for status in (401, 403, 429, 500, 502, 503):
        rc, out = _run_network(formula, status)
        check(f"HTTP {status} is not a pass", rc == 1, f"exit {rc}: {out.strip()[:200]}")
        check(f"HTTP {status} says it could not check",
              "could not" in out or "nothing was checked" in out,
              f"the message must say the check was not made: {out.strip()[:200]}")

    # No status line at all -- a DNS failure, a timeout, a `gh` that died before answering.
    rc, out = _run_network(formula, "", stderr="dial tcp: lookup api.github.com: no such host")
    check("no status is not a pass", rc == 1, f"exit {rc}: {out.strip()[:200]}")

    # The Formula must always name a published archive, even during release preparation.
    for version in ("3.15.0", "3.17.0"):
        for override in (False, True):
            rc, out = _run_network(_formula(version, GOOD), 404,
                                   latest_tag="v3.16.0", release_prep=override)
            check(f"missing Formula {version}, override={override} is refused", rc == 1,
                  f"exit {rc}: {out.strip()[:200]}")

    # Source preparation leaves the Formula on the newest published release.
    for latest in ("v3.15.0", "3.15.0"):
        rc, out = _run_network(formula, 200, sums=sums, source_version="3.16.0",
                               source_status=404, latest_tag=latest)
        check("published Formula survives unpublished source", rc == 0,
              f"exit {rc}: {out.strip()[:200]}")
    rc, out = _run_network(formula, 200, sums=sums, source_version="3.16.0",
                           source_status=200, source_draft=True)
    check("draft source permits published Formula", rc == 0, f"exit {rc}: {out.strip()[:200]}")
    for status in (200, 403, 502, ""):
        rc, out = _run_network(formula, 200, sums=sums, source_version="3.16.0",
                               source_status=status)
        check(f"lagging Formula with source status {status} is refused", rc == 1,
              f"exit {rc}: {out.strip()[:200]}")
    rc, out = _run_network(formula, 200, sums=sums, source_version="3.17.0",
                           latest_tag="v3.16.0")
    check("Formula older than newest published release is refused", rc == 1,
          f"exit {rc}: {out.strip()[:200]}")
    rc, out = _run_network(formula, 200, sums=sums, source_version="3.16.0",
                           latest_status=403)
    check("unreadable newest release is refused", rc == 1, f"exit {rc}: {out.strip()[:200]}")
    rc, out = _run_network(formula, 200, sums=sums, draft=True)
    check("a draft Formula release is refused", rc == 1, f"exit {rc}: {out.strip()[:200]}")
    rc, out = _run_network(formula, 200, sums=sums, source_version="3.9.0")
    check("Formula newer than source is refused numerically", rc == 1,
          f"exit {rc}: {out.strip()[:200]}")

    # 200 and the manifest agrees -- the whole path, fake `gh` and all.
    rc, out = _run_network(formula, 200, sums=f"{GOOD}  {ASSET}\n")
    check("200 with an agreeing manifest passes", rc == 0, f"exit {rc}: {out.strip()[:200]}")

    # 200 and the manifest disagrees -- #775 through the network branch.
    rc, out = _run_network(formula, 200, sums=f"{OTHER}  {ASSET}\n")
    check("200 with a stale hash fails", rc == 1, f"exit {rc}: {out.strip()[:200]}")

    # 200 but the asset is not in the manifest.
    rc, out = _run_network(formula, 200, sums=f"{GOOD}  SomethingElse.tar.gz\n")
    check("200 with no such asset fails", rc == 1, f"exit {rc}: {out.strip()[:200]}")

    # 200 but the download itself fails -- the release is there and the check could not be made.
    rc, out = _run_network(formula, 200)
    check("200 with an undownloadable manifest fails", rc == 1, f"exit {rc}: {out.strip()[:200]}")

    if failures:
        for f in failures:
            print(f"FAIL {f}")
        return 1
    print(f"{checks} checks pass: published Formula hashes and bounded source preparation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
