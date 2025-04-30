from blesstest import harness, pytest_collect_file  # noqa
import pydantic


class HarnessInput(pydantic.BaseModel):
    a: int
    b: int


@harness
def identity(test_input: HarnessInput) -> HarnessInput:
    return test_input


@harness
def identity_2(test_input: HarnessInput) -> HarnessInput:
    return test_input


@harness
def identity_3(test_input: HarnessInput) -> HarnessInput:
    return test_input
