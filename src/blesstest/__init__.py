from __future__ import annotations
import json
import pathlib

import pytest

from blesstest.git_utils import GitStatus, check_blessed_file_status
from blesstest.preprocessing import preprocess_test_cases, PreprocessedTestCasesFile

from .decorator import harness, all_harnesses

__all__ = ["harness", "pytest_collect_file"]


def pytest_collect_file(parent, file_path: pathlib.PosixPath):
    if file_path.name.endswith(".blesstest.json"):
        return BlessTestFile.from_parent(parent, path=file_path)


# class TestCaseInfo(pydantic.BaseModel):
#     harness: str
#     params: dict[str, Any]


# class TestCasesFile(pydantic.RootModel):
#     root: dict[str, TestCaseInfo]


class BlessTestFile(pytest.File):
    def collect(self):
        raw = json.loads(self.path.read_text())

        processed_test_cases = preprocess_test_cases(raw)
        print(f"processed_test_cases: {processed_test_cases}")
        validated_data = PreprocessedTestCasesFile.model_validate(processed_test_cases)
        print(f"BlessTestFile collect validated_data: {validated_data}")
        test_file_name = self.path.name.removesuffix(".blesstest.json")

        for test_name_from_json, test_case_info in validated_data.root.items():
            test_name = f"{test_file_name}_{test_name_from_json}"
            yield BlessTestItem.from_parent(
                self, name=test_name, path=self.path, test_case_info=test_case_info
            )


class BlessTestItem(pytest.Item):
    def __init__(self, *, path, test_case_info, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.test_case_info = test_case_info

    def runtest(self):
        harness = all_harnesses[self.test_case_info.harness]
        input_data = self.test_case_info.params
        harness.input_type.model_validate(
            input_data
        )  # Don't catch errors, let them bubble up

        test_input = harness.input_type(**input_data)
        actual_output_raw = harness.func(test_input)
        validated_output = harness.output_type.model_validate(actual_output_raw)
        output_dir = self.path.parent / "blessed"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file_path = output_dir / f"{self.name}.json"
        json_output = validated_output.model_dump_json(indent=2) + "\n"

        # Write the current output FIRST
        output_file_path.write_text(json_output)

        # Check Git status AFTER writing
        # Exceptions (FileNotFoundError, CalledProcessError, ValueError) will bubble up
        status = check_blessed_file_status(output_file_path)

        # Get relative path for messages
        relative_path_for_msg = str(output_file_path.relative_to(pathlib.Path.cwd()))

        # Assert based on status
        if status == GitStatus.NEEDS_STAGING:
            error = f"{relative_path_for_msg}: New blessed file created. Stage it if you bless it."
            print(error)
            raise AssertionError(error)
        elif status == GitStatus.CHANGED:
            error = (
                f"{relative_path_for_msg}: Changes found, stage them if you bless them."
            )
            print(error)
            raise AssertionError(error)
        # If status == GitStatus.MATCH, the test passes this check implicitly

    # def repr_failure(self, excinfo):
    #     """Called when self.runtest() raises an exception."""
    #     return super().repr_failure(excinfo)

    def reportinfo(self):
        return self.path, 0, f"{self.name}"  # TODO: Add the line of the test
