"""Build an immutable code index from Git blobs, without executing the project.

Usage: python -m scripts.index_repository [--repo data/repos/osticket]
The manifest pins the exact commit. No downloading takes place in this command.
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.agents.repository import DEFAULT_INDEX, MANIFEST, ROOT, RepositoryIndex, extract_symbols, valid_path

EXTENSIONS = {".php", ".js", ".sql", ".md", ".txt", ".json", ".yaml", ".yml"}
SKIP_DIRS = {"vendor", "node_modules", "pear", "mpdf", "i18n", "plugins"}
MAX_FILE_BYTES = 512_000
MAX_TOTAL_BYTES = 16_000_000


def git_prefix(repo: Path) -> list[str]:
    # Narrow per-command trust for this explicitly selected local checkout only.
    return ["git", "-c", f"safe.directory={repo.as_posix()}", "-c", "core.hooksPath=", "-C", str(repo)]


def build(repo: Path, output: Path = DEFAULT_INDEX) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    repo = repo.resolve(strict=True)
    prefix = git_prefix(repo)
    commit = manifest["commit_sha"]
    # Read the exact commit tree; modified working-tree files and symlinks cannot
    # inject different content under commit-pinned GitHub citation URLs.
    tree = subprocess.run(prefix + ["ls-tree", "-rlz", commit], check=True, capture_output=True, timeout=30).stdout
    entries = []
    skipped = 0
    total = 0
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid, size = metadata.decode().split()
        path = raw_path.decode("utf-8")
        parts = Path(path).parts
        if (kind != "blob" or mode not in {"100644", "100755"} or not valid_path(path)
                or Path(path).suffix.lower() not in EXTENSIONS or set(parts) & SKIP_DIRS
                or ".min." in path or int(size) > MAX_FILE_BYTES):
            skipped += 1
            continue
        total += int(size)
        if total > MAX_TOTAL_BYTES or len(entries) >= 2000:
            raise ValueError("Repository exceeds bounded indexing budget")
        entries.append((path, oid))
    payload = b"".join(oid.encode() + b"\n" for _, oid in entries)
    batch = subprocess.run(prefix + ["cat-file", "--batch"], input=payload, capture_output=True, check=True, timeout=60).stdout
    position = 0
    files = []
    for path, oid in entries:
        end = batch.index(b"\n", position)
        actual_oid, kind, size = batch[position:end].decode().split()
        if actual_oid != oid or kind != "blob":
            raise ValueError("Unexpected Git object")
        position = end + 1
        raw = batch[position:position + int(size)]
        position += int(size) + 1
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped += 1
            continue
        if "\0" in content or not content.strip():
            skipped += 1
            continue
        lines = content.splitlines()
        if len(lines) > 50000 or any(len(line) > 2000 for line in lines):
            skipped += 1
            continue
        language = Path(path).suffix.lstrip(".").lower()
        files.append({"path": path, "language": language, "lines": lines, "symbols": extract_symbols(lines, language)})
    index = RepositoryIndex(repository=manifest["repository"], commit_sha=commit,
                            indexed_at=datetime.now(timezone.utc).isoformat(), skipped_files=skipped, files=files)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(index.model_dump_json(), encoding="utf-8")
    temporary.replace(output)
    return {"repository": index.repository, "commit_sha": commit, "indexed_files": len(files), "skipped_files": skipped,
            "bytes": output.stat().st_size, "index_path": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT / "data" / "repos" / "osticket")
    args = parser.parse_args()
    print(json.dumps(build(args.repo), ensure_ascii=True, indent=2))
