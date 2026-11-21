"""Decide what to test without trusting filenames as shell code."""
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


def maintenance(path):
    if path.name in {"README.md", "AGENTS.md", "CONTRIBUTING.md", "CHANGELOG.md"} and len(path.parts) == 1:
        return True
    return (path.suffix.lower() == ".md" and
            (path.parts[0] == "docs" or path.parent.as_posix() == "deploy/production" or
             path.as_posix() in {"deploy/README.md", "dev/README.md", "deploy/apps/README.md",
                                 "STANDARDS.md", "UI-UX-STANDARD.md"}))


def check_links(path):
    text = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1[^\n]*", "", path.read_text(encoding="utf-8"))
    for match in re.finditer(r"\]\((<[^>]+>|[^\s)]+)(?:\s+[\x22'][^)]*)?\)", text):
        link = urlsplit(match[1].strip("<>"))
        if link.scheme or link.netloc or not link.path or link.path.startswith("/"):
            continue
        target = path.parent / unquote(link.path)
        if not target.exists():
            raise SystemExit(f"{path}: missing link to {link.path}")


def main():
    base = os.environ.get("BASE_SHA", "")
    runtime = True
    if re.fullmatch("[0-9a-f]{40}", base) and base != "0" * 40:
        changes = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "-z", base, "HEAD"])
        paths = [Path(os.fsdecode(p)) for p in changes.split(b"\0") if p]
        for path in paths:
            if maintenance(path) and path.is_file():
                check_links(path)
        runtime = any(not maintenance(path) for path in paths)
    with open(os.environ["GITHUB_OUTPUT"], "a") as out:
        print("runtime=" + str(runtime).lower(), file=out)


if __name__ == "__main__":
    main()
