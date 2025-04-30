from __future__ import annotations
import json
import os
import pathlib
import pydantic
import pyjson5
from typing import Any, Iterator, cast

import pytest

from blesstest.git_utils import GitStatus, check_blessed_file_status
from blesstest.preprocessing import (
    PreprocessedCaseInfo,
    preprocess_test_cases,
    PreprocessedTestCasesFile,
)

from .decorator import harness, all_harnesses

__all__ = ["harness", "pytest_collect_file"]


def pytest_collect_file(
    parent: pytest.File, file_path: pathlib.PosixPath
) -> BlessTestFile | None:
    name = file_path.name
    if file_path.suffix == ".json" and file_path.parent.name == "blessed":
        file_path.unlink()
    if name.endswith(".blesstest.json") or name.endswith(".blesstest.jsonc"):
        return BlessTestFile.from_parent(parent, path=file_path)
    return None


def process_file(raw_content: dict) -> PreprocessedTestCasesFile:
    processed_test_cases = preprocess_test_cases(raw_content)
    validated_data = PreprocessedTestCasesFile.model_validate(processed_test_cases)
    return validated_data


class BlessTestFile(pytest.File):
    def collect(self) -> Iterator[BlessTestItem]:
        raw = pyjson5.loads(self.path.read_text())
        validated_data = process_file(raw)
        print(f"BlessTestFile collect validated_data: {validated_data}")
        test_file_name = self.path.name.removesuffix(".blesstest.json").removesuffix(
            ".blesstest.jsonc"
        )

        for test_name_from_json, test_case_info in validated_data.root.items():
            test_name = f"{test_file_name}_{test_name_from_json}"
            yield BlessTestItem.from_parent(
                self, name=test_name, path=self.path, test_case_info=test_case_info
            )


class BlessTestItem(pytest.Item):
    def __init__(
        self,
        *,
        path: pathlib.PosixPath,
        test_case_info: PreprocessedCaseInfo,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.path = path
        self.test_case_info = test_case_info

    def runtest(self) -> None:
        harness = all_harnesses[self.test_case_info.harness]
        input_data = self.test_case_info.params
        harness.input_type.model_validate(
            input_data
        )  # Don't catch errors, let them bubble up

        test_input = harness.input_type(**cast(dict[str, Any], input_data))

        result = None

        try:
            actual_output_raw = harness.func(test_input)
            try:
                validated_output = harness.output_type.model_validate(actual_output_raw)
                result = validated_output.model_dump()
            except pydantic.ValidationError as e:
                result = {"invalid_output": str(e)}
        except Exception as e:
            if os.environ.get("BLESSTEST_DEBUG"):
                raise
            result = {"exception": str(e)}

        output_dir = self.path.parent / "blessed"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file_path = output_dir / f"{self.name}.json"

        output_file_structure: dict = {
            "harness": self.test_case_info.harness,
            "params": test_input.model_dump(),
            "result": result,
        }
        json_output = json.dumps(output_file_structure, indent=2) + "\n"

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

    def reportinfo(self) -> tuple[os.PathLike[str], int | None, str]:
        return self.path, 0, f"{self.name}"  # TODO: Add the line of the test
