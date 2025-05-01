# Run with:
# uv run vd --config examples/visidata-viewer/visidata_plugin.py

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
            ItemColumn("before", 1),
            ItemColumn("after", 2),
        ]

        def iterload(self) -> Generator[tuple[str, str, str], None, None]:
            for row in diffs.chunks:
                yield row.after.file_path, row.before.content, row.after.content

    vd.push(SimpleSheet())
    vd.run()


if __name__ == "__main__":
    do()
