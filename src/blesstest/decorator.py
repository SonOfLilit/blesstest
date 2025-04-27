import sys
import inspect
import json
import pathlib
import pydantic
import subprocess
import enum
from typing import Any, Dict

from .preprocessing import preprocess_test_cases


class GitStatus(enum.Enum):
    MATCH = 1
    CHANGED = 2
    NEEDS_STAGING = 3


def _check_blessed_file_status(output_file_path: pathlib.Path) -> GitStatus:
    """Checks the Git status of the blessed file using porcelain format.

    Uses `git status --porcelain -- <file>` to check the status against the index.
    Does not catch subprocess errors (FileNotFoundError, CalledProcessError).

    Returns:
        The GitStatus enum.

    Raises:
        FileNotFoundError: If 'git' command is not found.
        subprocess.CalledProcessError: If git status command fails.
        ValueError: If the git status output is unexpected.
    """
    relative_path = str(output_file_path.relative_to(pathlib.Path.cwd()))

    # Check the status using porcelain format for the specific file
    command = ["git", "status", "--porcelain", "--", relative_path]
    # Run the command, letting exceptions (FileNotFoundError, CalledProcessError) bubble up
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,  # Will raise CalledProcessError on non-zero exit
        encoding="utf-8",
    )

    output = result.stdout

    # The first column is the staging area, the second is the working tree.
    # M = Modified
    # A = Added
    # ? = Untracked

    if output.startswith("A "):
        # Added to index, and working tree matches index. This is fine.
        return GitStatus.MATCH
    elif not output or output[1] == " ":
        # Empty output means file is tracked and matches the index
        # empty second column means working tree matches index
        return GitStatus.MATCH
    elif output[1] == "M":
        return GitStatus.CHANGED
    elif output[1] == "?":
        # File is untracked
        return GitStatus.NEEDS_STAGING
    else:
        # Any other output is unexpected for a single file check after writing it
        raise ValueError(
            f"Unexpected git status output for {relative_path}: '{output}'"
        )


class TestCaseInfo(pydantic.BaseModel):
    params: Dict[str, Any]


class TestCasesFile(pydantic.RootModel):
    root: Dict[str, TestCaseInfo]


def harness(file_path: str):
    def decorator(func):
        # Get the module object where the decorated function is defined
        module_name = func.__module__
        if module_name not in sys.modules:
            raise RuntimeError(
                f"Module '{module_name}' not found in sys.modules. This might happen if the test file is not imported correctly."
            )
        module = sys.modules[module_name]

        # Get the input and output type hints from the decorated function
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        if not params:
            raise TypeError(
                f"Decorated function {func.__name__} must accept at least one argument (the input model)."
            )
        input_param = params[0]
        InputType = input_param.annotation
        OutputType = sig.return_annotation

        if InputType is inspect.Parameter.empty:
            raise TypeError(
                f"Decorated function {func.__name__} must have a type annotation for its input parameter."
            )
        if OutputType is inspect.Parameter.empty:
            raise TypeError(
                f"Decorated function {func.__name__} must have a return type annotation."
            )

        # Determine the absolute path to the JSON file
        if module.__file__ is None:
            raise RuntimeError(
                f"Could not determine the file path for module {module_name}."
            )
        module_path = pathlib.Path(module.__file__)
        absolute_file_path = module_path.parent / file_path

        # Load and validate the JSON test cases file
        try:
            with open(absolute_file_path, "r") as f:
                json_data = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Test cases file not found: {absolute_file_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {absolute_file_path}: {e}")

        processed_test_cases = preprocess_test_cases(json_data)
        validated_data = TestCasesFile.model_validate(processed_test_cases)

        # Generate tests dynamically in the module's global scope
        for test_name_from_json, test_case_info in validated_data.root.items():
            input_data = test_case_info.params
            test_name = f"test_{func.__name__}_{test_name_from_json}"

            InputType.model_validate(
                input_data
            )  # Don't catch errors, let them bubble up

            def create_test_function(
                input_vals,
                InputModel,
                OutputModel,
                original_func,
                test_name_str,
                module_file_path,
            ):
                def test_func():
                    # breakpoint()
                    test_input = InputModel(**input_vals)
                    actual_output_raw = original_func(test_input)
                    validated_output = OutputModel.model_validate(actual_output_raw)
                    output_dir = module_file_path.parent / "blessed"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_file_path = output_dir / f"{test_name_str}.json"
                    json_output = validated_output.model_dump_json(indent=2) + "\n"

                    # Write the current output FIRST
                    output_file_path.write_text(json_output)

                    # Check Git status AFTER writing
                    # Exceptions (FileNotFoundError, CalledProcessError, ValueError) will bubble up
                    status = _check_blessed_file_status(output_file_path)

                    # Get relative path for messages
                    relative_path_for_msg = str(
                        output_file_path.relative_to(pathlib.Path.cwd())
                    )

                    # Assert based on status
                    if status == GitStatus.NEEDS_STAGING:
                        error = f"{relative_path_for_msg}: New blessed file created. Stage it if you bless it."
                        print(error)
                        raise AssertionError(error)
                    elif status == GitStatus.CHANGED:
                        error = f"{relative_path_for_msg}: Changes found, stage them if you bless them."
                        print(error)
                        raise AssertionError(error)
                    # If status == GitStatus.MATCH, the test passes this check implicitly

                return test_func

            test_func = create_test_function(
                input_data, InputType, OutputType, func, test_name, module_path
            )  # Use module_path
            setattr(module, test_name, test_func)  # Add test to the module's namespace

        return func

    return decorator
