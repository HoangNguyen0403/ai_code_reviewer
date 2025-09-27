import fnmatch
import re
from typing import Dict, List


class DiffProcessor:
    """Handles unified diff parsing and filtering operations."""

    def __init__(self, exclude_patterns: List[str] = None):
        self.exclude_patterns = exclude_patterns or []

    def filter_diff(self, diff: str) -> str:
        """Filter diff content based on exclude patterns."""
        filtered = []
        current_file = None
        exclude = False

        for line in diff.splitlines(keepends=True):
            if line.startswith("diff --git"):
                parts = line.split(" b/")
                if len(parts) > 1:
                    current_file = parts[1].strip()
                    exclude = any(
                        fnmatch.fnmatch(current_file, pat.strip())
                        for pat in self.exclude_patterns
                    )
                else:
                    current_file = None
                    exclude = False
            if not exclude:
                filtered.append(line)
        return "".join(filtered)

    def split_unified_diff(self, diff_text: str) -> List[Dict]:
        """Split unified diff into hunks per file."""
        files = []
        current_file = None
        hunk_header = None
        hunk_lines = []

        file_pattern = re.compile(r"^diff --git a/(.+?) b/(.+)$")
        hunk_pattern = re.compile(r"^@@\s+[-+@0-9, ]+@@")

        # If input looks like Azure JSON (contains braces and 'changes'), try to convert
        if diff_text.strip().startswith("{") and '"changes"' in diff_text:
            try:
                import json
                data = json.loads(diff_text)
                changes = data.get("changes") or data.get("changeEntries") or []
                unified_chunks = []
                for ch in changes:
                    old_path = ch.get("item", {}).get("path") or ch.get("oldPath") or ch.get("originalPath") or ch.get("path")
                    new_path = ch.get("newPath") or old_path
                    diff = ch.get("diff") or ch.get("content") or ""
                    if old_path and new_path and diff:
                        unified_chunks.append(f"diff --git a/{old_path.lstrip('/')} b/{new_path.lstrip('/')}\n{diff}")
                diff_text = "\n".join(unified_chunks) if unified_chunks else diff_text
            except Exception:
                pass

        for line in diff_text.splitlines():
            file_match = file_pattern.match(line)
            if file_match:
                if current_file and hunk_header and hunk_lines:
                    files.append(
                        {
                            "file": current_file,
                            "hunk_header": hunk_header,
                            "hunk_lines": hunk_lines,
                        }
                    )
                current_file = file_match.group(2)
                hunk_header = None
                hunk_lines = []
                continue

            if hunk_pattern.match(line):
                if hunk_header and hunk_lines:
                    files.append(
                        {
                            "file": current_file,
                            "hunk_header": hunk_header,
                            "hunk_lines": hunk_lines,
                        }
                    )
                hunk_header = line
                hunk_lines = []
                continue

            if hunk_header is not None:
                hunk_lines.append(line)

        # Add the last hunk
        if current_file and hunk_header and hunk_lines:
            files.append(
                {
                    "file": current_file,
                    "hunk_header": hunk_header,
                    "hunk_lines": hunk_lines,
                }
            )

        return files
