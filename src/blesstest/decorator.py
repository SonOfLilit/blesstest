import sys
import inspect

def harness(test_cases):
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

        # Generate tests dynamically in the module's global scope
        for case in test_cases:
            input_data = {k: v for k, v in case.items() if k != 'expected' and k != 'name'}
            expected_output_data = case['expected']
            test_name = f"test_{func.__name__}_{case.get('name', '_'.join(map(str, input_data.values())))}"

            def create_test_function(input_vals, expected_vals, InputModel, OutputModel, original_func):
                def test_func():
                    test_input = InputModel(**input_vals)
                    expected_output = OutputModel(**expected_vals)
                    actual_output = original_func(test_input)
                    assert actual_output == expected_output
                return test_func

            test_func = create_test_function(input_data, expected_output_data, InputType, OutputType, func)
            setattr(module, test_name, test_func) # Add test to the module's namespace

        # Return the original function unmodified
        return func
    return decorator 