import sys
import inspect
import pydantic
from typing import Any, Callable, TypeVar


class Harness(pydantic.BaseModel):
    input_type: type[pydantic.BaseModel]
    output_type: type[pydantic.BaseModel]
    func: Callable[[Any], Any]


all_harnesses: dict[str, Harness] = {}


TCallable = TypeVar("TCallable", bound=Callable[[Any], Any])


def harness(func: TCallable) -> TCallable:
    # Get the module object where the decorated function is defined
    module_name = func.__module__
    if module_name not in sys.modules:
        raise RuntimeError(
            f"Module '{module_name}' not found in sys.modules. This might happen if the test file is not imported correctly."
        )

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

    if func.__name__ in all_harnesses:
        if all_harnesses[func.__name__].func != func:
            raise ValueError(
                f"Can't have two different harnesses with the same name: {func.__name__}"
            )
    else:
        all_harnesses[func.__name__] = Harness(
            input_type=InputType, output_type=OutputType, func=func
        )

    return func
