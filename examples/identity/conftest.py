from blesstest import harness, pytest_collect_file  # noqa
import pydantic


class HarnessInput(pydantic.BaseModel):
    a: int
    b: int


class HarnessOutput(HarnessInput):
    harness_name: str


@harness
def identity(test_input: HarnessInput) -> HarnessOutput:
    test_output = HarnessOutput(
        a=test_input.a,
        b=test_input.b,
        harness_name="identity",
    )
    return test_output


@harness
def identity_2(test_input: HarnessInput) -> HarnessOutput:
    test_output = HarnessOutput(
        a=test_input.a,
        b=test_input.b,
        harness_name="identity_2",
    )
    return test_output


@harness
def identity_3(test_input: HarnessInput) -> HarnessOutput:
    test_output = HarnessOutput(
        a=test_input.a,
        b=test_input.b,
        harness_name="identity_3",
    )
    return test_output
