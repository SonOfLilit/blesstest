from blesstest import harness
import pydantic

# Function to test
def add(a, b):
    return a + b

class TestInput(pydantic.BaseModel):
    a: int
    b: int

class TestOutput(pydantic.BaseModel):
    result: int

harness_test_cases = [
    {"a": 1, "b": 2, "expected": {"result": 3}, "name": "positive_numbers"},
    {"a": -1, "b": 1, "expected": {"result": 0}, "name": "negative_and_positive"},
    {"a": 0, "b": 0, "expected": {"result": 0}, "name": "zeros"},
    {"a": -5, "b": -3, "expected": {"result": -8}, "name": "negative_numbers"},
]

@harness(test_cases=harness_test_cases)
def my_harness(test_input: TestInput) -> TestOutput:
    return TestOutput(result=add(test_input.a, test_input.b))
