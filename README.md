# blesstest

A gold (snapshot) testing framework for Python based on pytest.

## Installation

```bash
pip install git+https://github.com/SonOfLilit/blesstest@main
```

## Basic usage

### Define a function to test

```python
def sum(a: int, b: int) -> int:
    return a + b
```

### Define the harness

This tells blesstest about the input and output types of `sum`, and lets tests refer to it as `sum_harness`.

```python
# conftest.py
from blesstest import harness, pytest_collect_file # noqa

import pydantic
from .functions import sum

class SumInput(pydantic.BaseModel):
    a: int
    b: int

class SumOutput(pydantic.BaseModel):
    result: int

@harness
def sum_harness(test_input: SumInput) -> SumOutput:
    result = sum(test_input.a, test_input.b)
    return SumOutput(result=result)
```

### Create a test definition file

We only define the inputs of each test case

```jsonc
// tests/test_sum.blesstest.jsonc
{
  "sum_simple": {
    // This will test the case `sum(a=1, b=2)`
    "harness": "sum_harness",
    "params": {
      "a": 1,
      "b": 2
    }
  },
  "sum_large_numbers": {
    "harness": "sum_harness",
    "params": {
      "a": 1000000,
      "b": 2000000
    }
  },
  "with_inheritance": {
    "base": "sum_simple",
    "params": {
      "b": 5
    }
  },
  "with_variations": {
    // This will run 2 tests: `sum(a=10, b=1)` and `sum(a=10, b=2)`
    "harness": "sum_harness",
    "params": {
      "a": 10
    },
    "variations": [
      {
        "params": {
          "b": 1
        }
      },
      {
        "params": {
          "b": 2
        }
      }
    ]
  }
}
```

### Run Tests

```bash
pytest
```

### Check the results

#### Check what files changed

Each file contains the result of one test case.

```bash
$ git status blessed/
[..]
Untracked files:
(use "git add <file>..." to include in what will be committed)
        blessed/sum_simple.json
        blessed/sum_large_numbers.json
        blessed/with_inheritance.json
        blessed/with_variations__b_1.json
        blessed/with_variations__b_2.json
```

#### Check if the file looks good

```bash
$ cat blessed/sum_simple.json
```

```json
{
  "harness": "my_harness",
  "params": {
    "a": 1,
    "b": 2
  },
  "result": {
    "result": 3
  }
}
```

#### Add the golden (snapshot) files to git

```bash
$ git add blessed/sum_simple.json
```

Congrats, you've blessed your first test!

Now `pytest` will show you that the test passed. If the results will ever differ from those snapshots, the tests will fail again.

## Some nice things we get

### Adding tests is easy

To add a new test case, we only need the INPUT parameters for it. We don't need to consider what exactly to assert or what the output would be. We can even use it to check the output of a new feature we added, view the output as a file, and if it looks good - commit it and we have a test.

### Changes that affect many tests are less painful

Imagine we'd update `sum` to return a float instead of an int. Instead of editing lots of asserts, blesstest will show us everything that changed (e.g `2` becomes `2.0`) as a git diff, ready to be committed (blessed) if it looks good.
