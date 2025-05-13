# Run with:
# uv run examples/visidata-viewer/visidata_plugin.py

from itertools import zip_longest
from visidata import Sheet, ItemColumn, vd, DisplayWrapper, iterchunks  # type: ignore # mypy can't find the types here
from pathlib import Path
from diff import parse_patch
from typing import Generator
import difflib


def do() -> None:
    diff_file_path = Path(__file__).parent.joinpath("diff.patch")
    diff_content = diff_file_path.read_text()

    diffs = parse_patch(
        diff_content,
        context_lines=1,
    )

    class FileColumn(ItemColumn):  # type: ignore
        def display(
            self, dw: DisplayWrapper, width: int | None = None
        ) -> Generator[tuple[list, str], None, None]:
            """Shorten a path by replacing each directory with its first letter + ellipsis."""
            text = dw.text
            if width and len(text) > width:
                parts = Path(dw.text).parts

                # Process all parts except the last one (filename)
                shortened_dirs = [f"{p[0]}…" for p in parts[:-1]]

                # Get filename without extension
                filename = Path(parts[-1]).stem

                # Join everything with slashes

                text = "/".join(shortened_dirs + [filename])

            yield from iterchunks(text)

    class SimpleSheet(Sheet):  # type: ignore # can't find the base Sheet type, mypy complcains, but doesn't run without inheriting from it
        columns = [
            FileColumn("file", 0),
            ItemColumn("chunk_index", 1),
            ItemColumn("before_line"),
            ItemColumn("before_content", 3, displayer="full"),
            ItemColumn("after_line"),
            ItemColumn("after_content", 5, displayer="full"),
        ]

        def iterload(
            self,
        ) -> Generator[tuple[str, int, int | None, str, int | None, str], None, None]:
            for i, row in enumerate(diffs.chunks):
                for j, (before_line, after_line) in enumerate(
                    zip_longest(
                        row.before.content.splitlines(),
                        row.after.content.splitlines(),
                        fillvalue="",
                    )
                ):
                    # Use difflib to get the differences
                    matcher = difflib.SequenceMatcher(None, before_line, after_line)
                    before_colored = []
                    after_colored = []

                    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                        if tag == "equal":
                            before_colored.append(before_line[i1:i2])
                            after_colored.append(after_line[j1:j2])
                        elif tag == "replace":
                            before_colored.append(f"[:red]{before_line[i1:i2]}[/]")
                            after_colored.append(f"[:green]{after_line[j1:j2]}[/]")
                        elif tag == "delete":
                            before_colored.append(f"[:red]{before_line[i1:i2]}[/]")
                            after_colored.append("[:green] [/]")
                        elif tag == "insert":
                            before_colored.append("[:red] [/]")
                            after_colored.append(f"[:green]{after_line[j1:j2]}[/]")

                    yield (
                        row.after.file_path,
                        i,
                        row.before.start_line + j
                        if row.before.start_line is not None and before_line
                        else None,
                        "".join(before_colored),
                        row.after.start_line + j
                        if row.after.start_line is not None and after_line
                        else None,
                        "".join(after_colored),
                    )

    vd.push(SimpleSheet())
    vd.run()


if __name__ == "__main__":
    do()
