"""Atomic publication and preservation of unrelated KDE configuration."""

import os
from pathlib import Path
import tempfile
import re


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def merge_groups(content: str, entries: dict[str, dict[str, str]]) -> str:
    """Update simple KConfig groups; preserve comments and nested groups verbatim."""
    out = []
    group = None
    found = set()
    written = {name: set() for name in entries}

    def finish():
        if group in entries:
            for key, value in entries[group].items():
                if key not in written[group]:
                    out.append(f"{key}={value}\n")
                    written[group].add(key)

    for line in content.splitlines(keepends=True):
        # Nested and flagged headers are boundaries, never part of the preceding
        # simple group. Do not modify immutable/localized KConfig entries.
        if re.fullmatch(r"\s*(?:\[[^\]\r\n]+\])+\s*", line):
            finish()
            header = line.strip()
            group = header[1:-1] if header.count("[") == 1 else None
            found.add(group)
        elif group in entries and not line.lstrip().startswith(("#", ";")):
            key, equals, _ = line.partition("=")
            if equals and key.strip() in entries[group]:
                name = key.strip()
                line = f"{key}={entries[group][name]}\n"
                written[group].add(name)
        out.append(line if line.endswith("\n") else line + "\n")
    finish()
    for name, values in entries.items():
        if name not in found:
            out.append(f"\n[{name}]\n")
            out.extend(f"{key}={value}\n" for key, value in values.items())
    return "".join(out)
