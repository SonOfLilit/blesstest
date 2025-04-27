from blesstest import harness
import pydantic


# Function to test
def add(a, b):
    return a + b


class HarnessInput(pydantic.BaseModel):
    a: int
    b: int


class HarnessOutput(pydantic.BaseModel):
    result: int


@harness(file_path="test_cases.blesstest.json")
def my_harness(test_input: HarnessInput) -> HarnessOutput:
    return HarnessOutput(result=add(test_input.a, test_input.b))
