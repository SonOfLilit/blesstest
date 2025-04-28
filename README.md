# blesstest

`blesstest` is a gold testing framework for Python based on pytest. Define scenarios that exercise your logic, run them with blessed, then look at the outputs and "bless" them. Next time the tests run, if the result differs from blessed output, it will fail and you will need to re-bless it.

## Core Concepts

1.  **Harness Function:** A Python function decorated with `@blesstest.harness`. This function takes a Pydantic model instance as input (which defines the scenario to be tested) and returns a Pydantic model instance as output (which defines the assertions to be made). Aim for a single harness that captures most/all complexity in your project with a minimal interface.
3.  **Test Definition Files (`.blesstest.json`):** JSON files that define individual test cases or variations. Each top-level key in the JSON represents a test case.

## How to Use

1.  **Install:**
    ```bash
    pip install blesstest
    ```

2.  **Define the Function to Test:**
    Write the core Python function you want to test.
    ```python
    # Example: functions.py
    def add(a: int, b: int) -> int:
        return a + b
    ```

3.  **Create the Harness Function:**
    In a `conftest.py` file (or another file imported by `conftest.py`), define the harness function using the `@blesstest.harness` decorator. This function accepts a pydantic model and returns a pydantic model.
    ```python
    # Example: conftest.py
    from blesstest import harness
    import pydantic
    from .functions import add

    class AddInput(pydantic.BaseModel):
        a: int
        b: int

    class AddOutput(pydantic.BaseModel):
        result: int

    @harness
    def addition_harness(test_input: AddInput) -> AddOutput:
        result = add(test_input.a, test_input.b)
        return AddOutput(result=result)
    ```

5.  **Enable Pytest Collection:**
    Also in your root `conftest.py`, import `pytest_collect_file` from `blesstest` to allow `pytest` to find your `.blesstest.json` files.
    ```python
    # Example: conftest.py (add this line)
    from blesstest import harness, pytest_collect_file # noqa

    # ... (rest of conftest.py including harness definition)
    ```

6.  **Create Test Definition File (`.blesstest.json`):**
    Create a JSON file (e.g., `tests/test_addition.blesstest.json`) defining your test cases.
    ```json
    {
      "add_simple": {
        "harness": "addition_harness",
        "params": {
          "a": 1,
          "b": 2
        }
      },
      "add_large_numbers": {
        "harness": "addition_harness",
        "params": {
          "a": 1000000,
          "b": 2000000
        }
      },
      "with_inheritance": {
        "base": "add_simple",
        "params": {
          "b": 5
        }
      },
      "with_variations": {
         "harness": "addition_harness",
         "params": { "a": 10 },
         "variations": [
           { "params": { "b": 1 } },
           { "params": { "b": 2 } }
         ]
      }
    }
    ```

7.  **Run Tests:**
    Execute `pytest` from your project's root directory.
    ```bash
    pytest
    ```
8. **Bless Test Results:**
    After manually examining `blessed/add_simple.json`, run:
    Execute `pytest` from your project's root directory.
    ```bash
    $ git status blessed/
    [..]
    Untracked files:
    (use "git add <file>..." to include in what will be committed)
            blessed/add_simple.json
            blessed/add_large_numbers.json
            blessed/with_inheritance.json
            blessed/with_variations__b_1.json
            blessed/with_variations__b_2.json
    $ less blessed/add_simple.json  # manually inspect output
    $ git add blessed/add_simple.json
    ```
