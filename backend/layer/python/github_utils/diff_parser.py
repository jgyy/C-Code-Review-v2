"""
github/diff_parser.py — Parse unified diff format

Extracts structured information from GitHub's unified diff format.
Used to map changed lines to function boundaries for targeted analysis.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import re


@dataclass
class DiffHunk:
    """A single hunk from a unified diff."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str  # The @@ line
    lines: list[str] = field(default_factory=list)
    
    @property
    def old_end(self) -> int:
        return self.old_start + self.old_count - 1
    
    @property
    def new_end(self) -> int:
        return self.new_start + self.new_count - 1


@dataclass
class FileDiff:
    """Parsed diff for a single file."""
    old_path: str
    new_path: str
    hunks: list[DiffHunk] = field(default_factory=list)
    is_new: bool = False
    is_deleted: bool = False
    is_renamed: bool = False
    
    @property
    def changed_lines_old(self) -> set[int]:
        """Get all line numbers that changed in the old version."""
        lines = set()
        for hunk in self.hunks:
            line_num = hunk.old_start
            for line in hunk.lines:
                if line.startswith("-"):
                    lines.add(line_num)
                    line_num += 1
                elif line.startswith(" "):
                    line_num += 1
                # + lines don't exist in old version
        return lines
    
    @property
    def changed_lines_new(self) -> set[int]:
        """Get all line numbers that changed in the new version."""
        lines = set()
        for hunk in self.hunks:
            line_num = hunk.new_start
            for line in hunk.lines:
                if line.startswith("+"):
                    lines.add(line_num)
                    line_num += 1
                elif line.startswith(" "):
                    line_num += 1
                # - lines don't exist in new version
        return lines


# Regex patterns
HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)
FILE_HEADER_OLD_RE = re.compile(r"^--- (.+)$")
FILE_HEADER_NEW_RE = re.compile(r"^\+\+\+ (.+)$")


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """
    Parse a unified diff into structured FileDiff objects.
    
    Args:
        diff_text: The raw unified diff text
    
    Returns:
        List of FileDiff objects, one per file
    """
    files: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: DiffHunk | None = None
    
    lines = diff_text.split("\n")
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check for file header
        old_match = FILE_HEADER_OLD_RE.match(line)
        if old_match:
            # Start of a new file
            if current_file and current_hunk:
                current_file.hunks.append(current_hunk)
            if current_file:
                files.append(current_file)
            
            old_path = old_match.group(1)
            # Remove a/ prefix if present
            if old_path.startswith("a/"):
                old_path = old_path[2:]
            
            current_file = FileDiff(old_path=old_path, new_path="")
            current_hunk = None
            
            # Check for /dev/null (new file)
            if old_path == "/dev/null":
                current_file.is_new = True
            
            i += 1
            continue
        
        new_match = FILE_HEADER_NEW_RE.match(line)
        if new_match and current_file:
            new_path = new_match.group(1)
            # Remove b/ prefix if present
            if new_path.startswith("b/"):
                new_path = new_path[2:]
            
            current_file.new_path = new_path
            
            # Check for /dev/null (deleted file)
            if new_path == "/dev/null":
                current_file.is_deleted = True
            
            # Check for rename
            if (current_file.old_path != current_file.new_path and 
                not current_file.is_new and 
                not current_file.is_deleted):
                current_file.is_renamed = True
            
            i += 1
            continue
        
        # Check for hunk header
        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match and current_file:
            # Save previous hunk
            if current_hunk:
                current_file.hunks.append(current_hunk)
            
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or "1")
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or "1")
            header = hunk_match.group(5).strip()
            
            current_hunk = DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                header=header,
            )
            
            i += 1
            continue
        
        # Diff content line
        if current_hunk and (line.startswith("+") or line.startswith("-") or line.startswith(" ")):
            current_hunk.lines.append(line)
        
        i += 1
    
    # Save last file/hunk
    if current_file and current_hunk:
        current_file.hunks.append(current_hunk)
    if current_file:
        files.append(current_file)
    
    return files


def parse_github_patch(patch: str) -> FileDiff:
    """
    Parse a single file's patch from GitHub's PR files API.
    
    GitHub's patch format is a single-file unified diff without
    the file header lines.
    """
    file_diff = FileDiff(old_path="", new_path="")
    current_hunk: DiffHunk | None = None
    
    for line in patch.split("\n"):
        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match:
            if current_hunk:
                file_diff.hunks.append(current_hunk)
            
            current_hunk = DiffHunk(
                old_start=int(hunk_match.group(1)),
                old_count=int(hunk_match.group(2) or "1"),
                new_start=int(hunk_match.group(3)),
                new_count=int(hunk_match.group(4) or "1"),
                header=hunk_match.group(5).strip(),
            )
        elif current_hunk and (line.startswith("+") or line.startswith("-") or line.startswith(" ")):
            current_hunk.lines.append(line)
    
    if current_hunk:
        file_diff.hunks.append(current_hunk)
    
    return file_diff


def lines_in_function(
    changed_lines: set[int],
    func_start: int,
    func_end: int,
) -> bool:
    """Check if any changed lines fall within a function's bounds."""
    for line in changed_lines:
        if func_start <= line <= func_end:
            return True
    return False


def get_functions_affected_by_diff(
    file_diff: FileDiff,
    functions: dict[str, tuple[int, int]],  # name -> (start, end)
    use_new_lines: bool = True,
) -> set[str]:
    """
    Determine which functions are affected by a diff.
    
    Args:
        file_diff: Parsed diff for the file
        functions: Mapping of function name to (start_line, end_line)
        use_new_lines: If True, use new version line numbers; else use old
    
    Returns:
        Set of function names that have changes
    """
    changed = file_diff.changed_lines_new if use_new_lines else file_diff.changed_lines_old
    affected = set()
    
    for name, (start, end) in functions.items():
        if lines_in_function(changed, start, end):
            affected.add(name)
    
    return affected
