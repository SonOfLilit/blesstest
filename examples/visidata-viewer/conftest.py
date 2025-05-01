from blesstest import harness, pytest_collect_file  # noqa
import pydantic
from pathlib import Path
from diff import parse_patch, DiffOutputModel


class HarnessInput(pydantic.BaseModel):
    diff_patch_path: str
    context_lines: int


@harness
def diff_parser(test_input: HarnessInput) -> DiffOutputModel:
    diff_content = (
        Path(__file__).parent.joinpath(test_input.diff_patch_path).read_text()
    )
    diff_output = parse_patch(diff_content, context_lines=test_input.context_lines)
    return diff_output
