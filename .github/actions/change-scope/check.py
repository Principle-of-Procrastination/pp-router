"""Decide what to test without trusting filenames as shell code."""
import os
import json
import re
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlsplit


def maintenance(path):
    if path.name in {"README.md", "AGENTS.md", "CONTRIBUTING.md", "CHANGELOG.md"} and len(path.parts) == 1:
        return True
    return (path.suffix.lower() == ".md" and
            (path.parts[0] == "docs" or path.parent.as_posix() == "deploy/production" or
             path.as_posix() in {"deploy/README.md", "dev/README.md", "deploy/apps/README.md",
                                 "STANDARDS.md", "UI-UX-STANDARD.md", "deploy/release/README.md",
                                 "pp/README.md", "pp/DEVELOPMENT.md", "pp/RELEASING.md"}))


def verified_base():
    workflow = os.environ["GITHUB_WORKFLOW_REF"].split("@", 1)[0].rsplit("/", 1)[1]
    query = urlencode({"branch": os.environ["GITHUB_REF_NAME"], "event": "push", "status": "success", "per_page": 30})
    url = (os.environ["GITHUB_API_URL"] + "/repos/" + os.environ["GITHUB_REPOSITORY"]
           + "/actions/workflows/" + quote(workflow, safe="") + "/runs?" + query)
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                                                 "Accept": "application/vnd.github+json", "User-Agent": "pp-ci"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            runs = json.load(response)["workflow_runs"]
    except (OSError, ValueError, KeyError):
        return ""
    for run in runs:
        sha = run["head_sha"]
        if (str(run["id"]) != os.environ["GITHUB_RUN_ID"] and re.fullmatch("[0-9a-f]{40}", sha)
                and subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"], capture_output=True).returncode == 0):
            return sha
    return ""


def changed(base):
    raw = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "-z", base, "HEAD"])
    return [Path(os.fsdecode(name)) for name in raw.split(b"\0") if name]


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
    event_base = os.environ.get("BASE_SHA", "")
    base = verified_base() if os.environ.get("GITHUB_EVENT_NAME") == "push" else event_base
    valid = re.fullmatch("[0-9a-f]{40}", base) and base != "0" * 40
    paths = changed(base) if valid else []
    links = paths
    if not valid and re.fullmatch("[0-9a-f]{40}", event_base) and event_base != "0"*40:
        links = changed(event_base)
    if os.environ.get("CHECK_LINKS", "true") == "true":
        for path in links:
            if maintenance(path) and path.is_file():
                check_links(path)
    runtime = not valid or any(not maintenance(path) for path in paths)
    with open(os.environ["GITHUB_OUTPUT"], "a") as out:
        print("base=" + (base if valid else ""), file=out)
        print("runtime=" + str(runtime).lower(), file=out)


if __name__ == "__main__":
    main()
