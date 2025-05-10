# Run with:
# uv run examples/visidata-viewer/visidata_plugin.py

from itertools import zip_longest
from visidata import Sheet, ItemColumn, vd  # type: ignore # mypy can't find the types here
from pathlib import Path
from diff import parse_patch
from typing import Generator


def do() -> None:
    diff_file_path = Path(__file__).parent.joinpath("diff.patch")
    diff_content = diff_file_path.read_text()

    diffs = parse_patch(
        diff_content,
        context_lines=1,
    )

    class SimpleSheet(Sheet):  # type: ignore # can't find the base Sheet type, mypy complcains, but doesn't run without inheriting from it
        columns = [
            ItemColumn("file", 0),
            ItemColumn("chunk_index", 1),
            ItemColumn("before_line", 2),
            ItemColumn("before_content", 3),
            ItemColumn("after_line", 4),
            ItemColumn("after_content", 5),
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
                    yield (
                        row.after.file_path,
                        i,
                        row.before.start_line + j
                        if row.before.start_line is not None and before_line
                        else None,
                        before_line,
                        row.after.start_line + j
                        if row.after.start_line is not None and after_line
                        else None,
                        after_line,
                    )

    vd.push(SimpleSheet())
    vd.run()


if __name__ == "__main__":
    do()
