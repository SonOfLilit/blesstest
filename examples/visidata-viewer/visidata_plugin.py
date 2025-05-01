from visidata import Sheet, ItemColumn, vd  # type: ignore # mypy can't find the types here

# Run with:
# uv run vd --config examples/visidata-viewer/visidata_plugin.py


def do() -> None:
    class SimpleSheet(Sheet):  # type: ignore # can't find the base Sheet type, mypy complcains, but doesn't run without inheriting from it
        columns = [
            ItemColumn("col1", 0),
            ItemColumn("col2", 1),
        ]

        def iterload(self) -> list[list[str]]:
            return [
                ["hello", "2"],
                ["3", "4"],
            ]

    vd.push(SimpleSheet())


do()
