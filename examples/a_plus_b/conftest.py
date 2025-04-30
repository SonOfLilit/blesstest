from blesstest import harness, pytest_collect_file  # noqa
import pydantic


# Function to test.
def add(a, b):  # type: ignore # Demonstrating that typing is optional here
    return a + b


class HarnessInput(pydantic.BaseModel):
    a: int
    b: int


class HarnessOutput(pydantic.BaseModel):
    result: int


@harness
def my_harness(test_input: HarnessInput) -> HarnessOutput:
    return HarnessOutput(result=add(test_input.a, test_input.b))
