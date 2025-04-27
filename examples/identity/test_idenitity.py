from blesstest import harness
import pydantic


class HarnessInput(pydantic.BaseModel):
    a: int
    b: int


@harness(file_path="test_identity_cases.blesstest.json")
def my_harness(test_input: HarnessInput) -> HarnessInput:
    return test_input
