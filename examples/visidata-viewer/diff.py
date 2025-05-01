#!/usr/bin/env python
import argparse
import re
import sys
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel

# Regex to capture file paths from `diff --git` line
_DIFF_GIT_LINE_RE = re.compile(
    r"^diff --git a/(?P<path_a>.*?) b/(?P<path_b>.*?)$", re.MULTILINE
)
# Regex to capture hunk header info: @@ -start_a,count_a +start_b,count_b @@
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<start_a>\d+)(?:,(?P<count_a>\d+))? \+(?P<start_b>\d+)(?:,(?P<count_b>\d+))? @@"
)


class TextChunk(BaseModel):
    """Represents the content and location of text in one state (before/after)."""

    file_path: str
    start_line: Optional[int] = (
        None  # 1-based line number in the original file, None if not applicable
    )
    end_line: Optional[int] = (
        None  # 1-based line number in the original file, None if not applicable
    )
    content: str


class ChunkModel(BaseModel):
    """Represents a combined chunk showing before and after states."""

    before: TextChunk
    after: TextChunk
    is_boring: bool


class LineModel(BaseModel):
    """Represents a single line from the patch body with its context."""

    type: Literal["context", "added", "removed"]
    content: str
    patch_line_index: (
        int  # 0-based index within the specific file's lines list in the patch
    )
    original_before_line_num: Optional[int] = (
        None  # 1-based line number in the 'before' file
    )
    original_after_line_num: Optional[int] = (
        None  # 1-based line number in the 'after' file
    )


class DiffOutputModel(BaseModel):
    """Top-level model holding all chunks from the patch."""

    chunks: List[ChunkModel]


def process_file_diff(
    file_path_a: str, file_path_b: str, lines: List[LineModel], context_lines: int
) -> List[ChunkModel]:
    """
    Processes the enriched lines of a single file's diff section into ChunkModel objects.
    Grouping is based on consecutive changes allowing gaps of up to `context_lines`.
    """
    if not lines:
        return []

    n = len(lines)
    is_changed = [line.type in ("added", "removed") for line in lines]
    change_indices = [i for i, changed in enumerate(is_changed) if changed]

    # Handle case with no changes
    if not change_indices:
        content = "".join(line.content for line in lines)
        start_line_a = min(
            (
                line.original_before_line_num
                for line in lines
                if line.original_before_line_num is not None
            ),
            default=None,
        )
        end_line_a = max(
            (
                line.original_before_line_num
                for line in lines
                if line.original_before_line_num is not None
            ),
            default=None,
        )
        start_line_b = min(
            (
                line.original_after_line_num
                for line in lines
                if line.original_after_line_num is not None
            ),
            default=None,
        )
        end_line_b = max(
            (
                line.original_after_line_num
                for line in lines
                if line.original_after_line_num is not None
            ),
            default=None,
        )

        text_chunk_before = TextChunk(
            file_path=file_path_a,
            start_line=start_line_a,
            end_line=end_line_a,
            content=content,
        )
        text_chunk_after = TextChunk(
            file_path=file_path_b,
            start_line=start_line_b,
            end_line=end_line_b,
            content=content,
        )
        return [
            ChunkModel(before=text_chunk_before, after=text_chunk_after, is_boring=True)
        ]

    # --- Grouping and chunk creation logic (similar to before, but outputs new models) ---
    is_part_of_diff_chunk = [False] * n

    def count_context_lines_between(start_idx: int, end_idx: int) -> int:
        count = 0
        for i in range(start_idx + 1, end_idx):
            if lines[i].type == "context":
                count += 1
        return count

    groups = []
    if change_indices:
        current_group = [change_indices[0]]
        for i in range(1, len(change_indices)):
            prev_change_idx = change_indices[i - 1]
            curr_change_idx = change_indices[i]
            if (
                count_context_lines_between(prev_change_idx, curr_change_idx)
                <= context_lines
            ):
                current_group.append(curr_change_idx)
            else:
                groups.append(current_group)
                current_group = [curr_change_idx]
        groups.append(current_group)

    for group in groups:
        group_indices_to_mark = set()
        first_change_idx_in_group = group[0]
        last_change_idx_in_group = group[-1]

        for i in range(first_change_idx_in_group, last_change_idx_in_group + 1):
            group_indices_to_mark.add(i)

        context_found_before = 0
        idx = first_change_idx_in_group - 1
        context_indices_before = []
        while idx >= 0 and context_found_before < context_lines:
            if lines[idx].type == "context":
                context_indices_before.append(idx)
                context_found_before += 1
            elif is_changed[idx]:
                break
            idx -= 1
        group_indices_to_mark.update(reversed(context_indices_before))

        context_found_after = 0
        idx = last_change_idx_in_group + 1
        context_indices_after = []
        while idx < n and context_found_after < context_lines:
            if lines[idx].type == "context":
                context_indices_after.append(idx)
                context_found_after += 1
            elif is_changed[idx]:
                break
            idx += 1
        group_indices_to_mark.update(context_indices_after)

        for i in group_indices_to_mark:
            if 0 <= i < n:
                is_part_of_diff_chunk[i] = True

    # --- Generate final ChunkModel list using the new structure ---
    final_chunks: List[ChunkModel] = []
    current_chunk_lines: List[LineModel] = []
    current_chunk_is_diff: bool | None = None

    for i in range(n):
        is_diff_line = is_part_of_diff_chunk[i]
        line = lines[i]

        if current_chunk_is_diff is None:
            current_chunk_is_diff = is_diff_line
            current_chunk_lines.append(line)
        elif is_diff_line == current_chunk_is_diff:
            current_chunk_lines.append(line)
        else:
            if current_chunk_lines:
                # Finalize previous chunk
                before_content = "".join(
                    line.content for line in current_chunk_lines if line.type != "added"
                )
                after_content = "".join(
                    line.content
                    for line in current_chunk_lines
                    if line.type != "removed"
                )

                before_lines = [
                    line.original_before_line_num
                    for line in current_chunk_lines
                    if line.original_before_line_num is not None
                    and line.type != "added"
                ]
                after_lines = [
                    line.original_after_line_num
                    for line in current_chunk_lines
                    if line.original_after_line_num is not None
                    and line.type != "removed"
                ]

                before_start = min(before_lines) if before_lines else None
                before_end = max(before_lines) if before_lines else None
                after_start = min(after_lines) if after_lines else None
                after_end = max(after_lines) if after_lines else None

                text_chunk_before = TextChunk(
                    file_path=file_path_a,
                    start_line=before_start,
                    end_line=before_end,
                    content=before_content,
                )
                text_chunk_after = TextChunk(
                    file_path=file_path_b,
                    start_line=after_start,
                    end_line=after_end,
                    content=after_content,
                )

                final_chunks.append(
                    ChunkModel(
                        before=text_chunk_before,
                        after=text_chunk_after,
                        is_boring=not current_chunk_is_diff,
                    )
                )

            # Start new chunk
            current_chunk_is_diff = is_diff_line
            current_chunk_lines = [line]

    # Finalize the last chunk
    if current_chunk_lines:
        before_content = "".join(
            line.content for line in current_chunk_lines if line.type != "added"
        )
        after_content = "".join(
            line.content for line in current_chunk_lines if line.type != "removed"
        )

        before_lines = [
            line.original_before_line_num
            for line in current_chunk_lines
            if line.original_before_line_num is not None and line.type != "added"
        ]
        after_lines = [
            line.original_after_line_num
            for line in current_chunk_lines
            if line.original_after_line_num is not None and line.type != "removed"
        ]

        before_start = min(before_lines) if before_lines else None
        before_end = max(before_lines) if before_lines else None
        after_start = min(after_lines) if after_lines else None
        after_end = max(after_lines) if after_lines else None

        text_chunk_before = TextChunk(
            file_path=file_path_a,
            start_line=before_start,
            end_line=before_end,
            content=before_content,
        )
        text_chunk_after = TextChunk(
            file_path=file_path_b,
            start_line=after_start,
            end_line=after_end,
            content=after_content,
        )

        final_chunks.append(
            ChunkModel(
                before=text_chunk_before,
                after=text_chunk_after,
                is_boring=not current_chunk_is_diff,
            )
        )

    return final_chunks


def parse_patch(patch_content: str, context_lines: int) -> DiffOutputModel:
    """
    Parses a full patch string, including hunk headers, into a DiffOutputModel.
    """
    all_chunks: List[ChunkModel] = []
    current_file_lines: List[LineModel] = []
    current_file_path_a: str | None = None
    current_file_path_b: str | None = None
    patch_line_idx_in_file: int = 0
    # Hunk state
    hunk_start_line_a: int = 0
    hunk_start_line_b: int = 0
    current_line_in_hunk_a: int = 0
    current_line_in_hunk_b: int = 0
    state = "scan"  # scan, header, hunk_header, diff_body

    lines_iter = iter(patch_content.splitlines(keepends=True))

    while True:
        try:
            line_text = next(lines_iter)

            diff_git_match = _DIFF_GIT_LINE_RE.match(line_text)
            if diff_git_match:
                # Finalize previous file's chunks if any
                if (
                    state in ("hunk_header", "diff_body")
                    and current_file_path_a is not None
                    and current_file_path_b is not None
                ):
                    all_chunks.extend(
                        process_file_diff(
                            current_file_path_a,
                            current_file_path_b,
                            current_file_lines,
                            context_lines,
                        )
                    )
                # Reset for new file
                current_file_path_a = diff_git_match.group("path_a")
                current_file_path_b = diff_git_match.group("path_b")
                current_file_lines = []
                patch_line_idx_in_file = 0
                state = "header"
                continue

            if state == "scan":
                continue  # Skip lines before the first diff --git

            if state == "header":
                # Look for hunk header or end of header section
                if line_text.startswith("---") or line_text.startswith(
                    "+++"
                ):  # Standard header lines
                    continue
                hunk_match = _HUNK_HEADER_RE.match(line_text)
                if hunk_match:
                    hunk_start_line_a = int(hunk_match.group("start_a"))
                    hunk_start_line_b = int(hunk_match.group("start_b"))
                    current_line_in_hunk_a = hunk_start_line_a
                    current_line_in_hunk_b = hunk_start_line_b
                    state = "diff_body"  # Changed state name
                # else: could be index, mode changes, etc. - ignore for now
                continue

            # Removed hunk_header state as logic is combined with header now

            if state == "diff_body":
                line_model: Optional[LineModel] = None
                original_a = None
                original_b = None

                if line_text.startswith("+"):
                    original_b = current_line_in_hunk_b
                    line_model = LineModel(
                        type="added",
                        content=line_text[1:],
                        patch_line_index=patch_line_idx_in_file,
                        original_after_line_num=original_b,
                    )
                    current_line_in_hunk_b += 1
                elif line_text.startswith("-"):
                    original_a = current_line_in_hunk_a
                    line_model = LineModel(
                        type="removed",
                        content=line_text[1:],
                        patch_line_index=patch_line_idx_in_file,
                        original_before_line_num=original_a,
                    )
                    current_line_in_hunk_a += 1
                elif line_text.startswith(" "):
                    original_a = current_line_in_hunk_a
                    original_b = current_line_in_hunk_b
                    line_model = LineModel(
                        type="context",
                        content=line_text[1:],
                        patch_line_index=patch_line_idx_in_file,
                        original_before_line_num=original_a,
                        original_after_line_num=original_b,
                    )
                    current_line_in_hunk_a += 1
                    current_line_in_hunk_b += 1
                elif line_text.startswith("\\"):  # No newline marker
                    continue  # Ignore this line for chunking
                else:
                    # Check if it's the start of a new hunk
                    hunk_match = _HUNK_HEADER_RE.match(line_text)
                    if hunk_match:
                        hunk_start_line_a = int(hunk_match.group("start_a"))
                        hunk_start_line_b = int(hunk_match.group("start_b"))
                        current_line_in_hunk_a = hunk_start_line_a
                        current_line_in_hunk_b = hunk_start_line_b
                        # Stay in diff_body state, just reset hunk line counters
                        continue
                    else:
                        # Could be unexpected line or end of patch section for the file
                        # For simplicity, we assume well-formed patches for now
                        # or transition implicitly if a new `diff --git` is found
                        pass  # Ignore other lines for now

                if line_model:
                    current_file_lines.append(line_model)
                    patch_line_idx_in_file += 1

        except StopIteration:
            # Finalize the last file's chunks if any
            if (
                state in ("diff_body")
                and current_file_path_a is not None
                and current_file_path_b is not None
            ):
                all_chunks.extend(
                    process_file_diff(
                        current_file_path_a,
                        current_file_path_b,
                        current_file_lines,
                        context_lines,
                    )
                )
            break

    return DiffOutputModel(chunks=all_chunks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse a patch file into chunks and output as JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Parses a Git patch file and identifies chunks based on context proximity.
- Diff Chunk: Consecutive changed lines (+/-) possibly separated by up to K unchanged lines,
  plus K lines of context before and after the changed group.
- Boring Chunk: Consecutive unchanged lines that are not part of any diff chunk's context.

Output is a JSON object containing a list of chunks. Each chunk details the 'before'
and 'after' state including file path, original line numbers (1-based), and content.
""",
    )
    parser.add_argument("patch_file", type=Path, help="Path to the patch file.")
    parser.add_argument(
        "-k",
        "--context-lines",
        type=int,
        default=3,
        metavar="K",
        help="Number of context lines (K) around diffs and gap tolerance. Default=3.",
    )
    args = parser.parse_args()

    if not args.patch_file.is_file():
        print(f"Error: Patch file not found: {args.patch_file}", file=sys.stderr)
        sys.exit(1)

    if args.context_lines < 0:
        print(
            f"Error: K (context lines) cannot be negative: {args.context_lines}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        patch_content = args.patch_file.read_text()
        diff_output = parse_patch(patch_content, args.context_lines)

        # Output the result as JSON
        print(diff_output.model_dump_json(indent=2))

    except Exception as e:
        print(f"An error occurred during processing: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
