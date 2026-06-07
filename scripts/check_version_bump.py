import pathlib
import re
import subprocess
import sys

_ROOT = pathlib.Path(__file__).parent.parent


def get_current_version() -> str:
    version_file = _ROOT / "__version__.py"
    if not version_file.exists():
        print(f"[version-gate] ERROR: {version_file} not found", file=sys.stderr)
        sys.exit(2)
    text = version_file.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not m:
        print("[version-gate] ERROR: could not parse __version__", file=sys.stderr)
        sys.exit(2)
    return m.group(1)


def get_latest_tag() -> str:
    try:
        tag = (
            subprocess.check_output(
                ["git", "describe", "--tags", "--abbrev=0"],
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            .decode("utf-8")
            .strip()
        )
        return tag.lstrip("v")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "0.0.0"


def parse_version(v: str) -> tuple:
    core = v.split("-")[0].split("+")[0]
    try:
        return tuple(int(x) for x in core.split("."))
    except ValueError:
        print(
            f"[version-gate] ERROR: cannot parse version string '{v}'", file=sys.stderr
        )
        sys.exit(2)


def main() -> None:
    current = get_current_version()
    latest = get_latest_tag()
    curr_tuple = parse_version(current)
    prev_tuple = parse_version(latest)
    if curr_tuple <= prev_tuple:
        print(
            f"[version-gate] FAIL: bump __version__.py before pushing. "
            f"latest={latest} current={current}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[version-gate] OK: {latest} -> {current}")


if __name__ == "__main__":
    main()
