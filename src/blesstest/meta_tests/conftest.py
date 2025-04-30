from blesstest import harness, pytest_collect_file  # noqa
import pydantic

from blesstest.preprocessing import PreprocessedTestCasesFile
from blesstest import process_file


# Function to test
def add(a, b):
    return a + b


class HarnessInput(pydantic.BaseModel):
    input: dict


class HarnessOutput(pydantic.BaseModel):
    result: PreprocessedTestCasesFile


@harness
def collect(test_input: HarnessInput) -> HarnessOutput:
    return HarnessOutput(result=process_file(test_input.input))
