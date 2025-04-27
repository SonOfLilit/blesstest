import copy
from typing import Any, Dict

JSON = Dict[str, Any]
CaseName = str
CaseInfo = JSON


def preprocess_test_cases(
    raw_test_cases: Dict[CaseName, CaseInfo],
) -> Dict[CaseName, CaseInfo]:
    processed_cases: Dict[CaseName, CaseInfo] = {}
    processing_stack: set = set()

    def process_case(case_name: CaseName) -> CaseInfo:
        if case_name in processed_cases:
            return processed_cases[case_name]
        if case_name not in raw_test_cases:
            raise ValueError(f"Base case '{case_name}' not found.")
        if case_name in processing_stack:
            raise ValueError(
                f"Circular dependency detected involving '{case_name}'. stack: {processing_stack}"
            )

        current_case_info = raw_test_cases[case_name]
        processed_case_info: CaseInfo
        if "base" not in current_case_info:
            processed_case_info = current_case_info
        else:
            processing_stack.add(case_name)

            base_name = current_case_info["base"]
            base_case_info = process_case(base_name)
            base_params = base_case_info.get("params", {})
            current_params = current_case_info.get("params", {})
            output_params = copy.deepcopy(base_params)
            output_params.update(current_params)

            processed_case_info = copy.deepcopy(base_case_info)
            processed_case_info["params"] = output_params
            processing_stack.remove(case_name)

        processed_cases[case_name] = processed_case_info
        return processed_case_info

    for name in raw_test_cases:
        process_case(name)

    return processed_cases
