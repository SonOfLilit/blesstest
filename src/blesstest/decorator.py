import sys
import inspect
import json
import pathlib
import pydantic
from typing import Any, Dict

class TestCaseInfo(pydantic.BaseModel):
    params: Dict[str, Any]

class TestCasesFile(pydantic.RootModel):
    root: Dict[str, TestCaseInfo]

def harness(file_path: str):
    def decorator(func):
        # Get the module object where the decorated function is defined
        module_name = func.__module__
        if module_name not in sys.modules:
            raise RuntimeError(f"Module '{module_name}' not found in sys.modules. This might happen if the test file is not imported correctly.")
        module = sys.modules[module_name]

        # Get the input and output type hints from the decorated function
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        if not params:
             raise TypeError(f"Decorated function {func.__name__} must accept at least one argument (the input model).")
        input_param = params[0]
        InputType = input_param.annotation
        OutputType = sig.return_annotation

        if InputType is inspect.Parameter.empty:
             raise TypeError(f"Decorated function {func.__name__} must have a type annotation for its input parameter.")
        if OutputType is inspect.Parameter.empty:
             raise TypeError(f"Decorated function {func.__name__} must have a return type annotation.")

        # Determine the absolute path to the JSON file
        if module.__file__ is None:
            raise RuntimeError(f"Could not determine the file path for module {module_name}.")
        module_path = pathlib.Path(module.__file__).parent
        absolute_file_path = module_path / file_path

        # Load and validate the JSON test cases file
        try:
            with open(absolute_file_path, 'r') as f:
                json_data = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Test cases file not found: {absolute_file_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {absolute_file_path}: {e}")

        try:
            validated_data = TestCasesFile.model_validate(json_data)
        except pydantic.ValidationError as e:
            raise ValueError(f"Invalid format in test cases file {absolute_file_path}: {e}")

        # Generate tests dynamically in the module's global scope
        for test_name_from_json, test_case_info in validated_data.root.items():
            input_data = test_case_info.params
            test_name = f"test_{func.__name__}_{test_name_from_json}"

            InputType.model_validate(input_data) # Don't catch errors, let them bubble up

            def create_test_function(input_vals, InputModel, original_func):
                def test_func():
                    test_input = InputModel(**input_vals)
                    original_func(test_input)
                return test_func

            test_func = create_test_function(input_data, InputType, func)
            setattr(module, test_name, test_func) # Add test to the module's namespace

        return func
    return decorator 