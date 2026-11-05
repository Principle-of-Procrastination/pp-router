"""Build a production bundle from an explicit allowlist; never include local secrets/data."""

import argparse
import hashlib
from pathlib import Path
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=".local/deploy/pp-router.tar.gz")
    args = parser.parse_args()
    subprocess.run(["npm", "run", "build", "--prefix", "frontend"], cwd=ROOT, check=True)
    subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-header",
         "--output-file", "deploy/requirements.lock"],
        cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
    )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [ROOT / name for name in
             ("pyproject.toml", "uv.lock", "alembic.ini", "Dockerfile", ".dockerignore")]
    files.extend((ROOT / "pprouter").rglob("*.py"))
    files.extend((ROOT / "migrations").rglob("*.py"))
    files.extend((ROOT / "migrations").rglob("*.mako"))
    files.extend(path for path in (ROOT / "frontend/dist").rglob("*") if path.is_file())
    files.extend(path for path in (ROOT / "deploy").rglob("*") if path.is_file())
    with tarfile.open(output, "w:gz") as archive:
        # Preserve readable directories even when the server extracts with umask 077.
        directories = {
            parent
            for path in files
            for parent in path.relative_to(ROOT).parents
            if parent != Path(".")
        }
        for directory in sorted(directories, key=lambda p: (len(p.parts), str(p))):
            entry = tarfile.TarInfo(str(directory))
            entry.type, entry.mode = tarfile.DIRTYPE, 0o755
            archive.addfile(entry)
        for path in sorted(files):
            if path.is_symlink():
                raise SystemExit(f"Refusing release symlink: {path.relative_to(ROOT)}")
            archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
    output.chmod(0o600)
    print(f"Release: {output}\nSHA256: {hashlib.sha256(output.read_bytes()).hexdigest()}")
    print(f"Files: {len(files)}; bytes: {output.stat().st_size}")


if __name__ == "__main__":
    main()
