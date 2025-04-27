import base64
import copy
import hashlib
import json
from typing import Any, Dict

JSON = Dict[str, Any]
CaseName = str
CaseInfo = JSON


def resolve_bases(
    raw_test_cases: Dict[CaseName, CaseInfo],
) -> Dict[CaseName, CaseInfo]:
    """Resolves 'base' references in test cases."""
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
            # Merge params: current params override base params
            base_params = base_case_info.get("params", {})
            current_params = current_case_info.get("params", {})
            output_params = copy.deepcopy(base_params)
            output_params.update(current_params)

            processed_case_info = copy.deepcopy(base_case_info)
            # Remove base key as it's resolved
            if "base" in processed_case_info:
                del processed_case_info["base"]
            processed_case_info["params"] = output_params

            # Copy other keys from the current case that weren't in the base
            for key, value in current_case_info.items():
                if key not in processed_case_info and key != "base" and key != "params":
                    processed_case_info[key] = value

            processing_stack.remove(case_name)

        processed_cases[case_name] = processed_case_info
        return processed_case_info

    for name in raw_test_cases:
        process_case(name)

    return processed_cases


def resolve_variations(
    resolved_base_cases: Dict[CaseName, CaseInfo],
) -> Dict[CaseName, CaseInfo]:
    """Expands test cases with 'variations' into individual cases."""
    expanded_cases: Dict[CaseName, CaseInfo] = {}

    for case_name, case_info in resolved_base_cases.items():
        if "variations" not in case_info:
            expanded_cases[case_name] = case_info
            continue

        variations_list = case_info["variations"]
        if not isinstance(variations_list, list):
            raise ValueError(
                f"Expected 'variations' to be a list in case '{case_name}', got {type(variations_list)}"
            )

        # Create a base template for variations by removing the 'variations' key
        base_variation_template = copy.deepcopy(case_info)
        del base_variation_template["variations"]
        base_params = base_variation_template.get("params", {})

        for i, variation_data in enumerate(variations_list):
            if not isinstance(variation_data, dict):
                raise ValueError(
                    f"Expected variation item to be a dict in case '{case_name}', index {i}, got {type(variation_data)}"
                )

            # Generate parameter string part (truncated)
            variation_params = variation_data.get("params", {})
            param_str_parts = [f"{k}_{v}" for k, v in sorted(variation_params.items())]
            param_str = "_".join(param_str_parts)
            if len(param_str) > 50:
                param_str = param_str[:50]

            # Generate hash part from the full variation data
            variation_json = json.dumps(variation_data, sort_keys=True)
            variation_hash = base64.b64encode(
                hashlib.sha256(variation_json.encode()).digest()
            )[:3].decode()

            new_case_name = f"{case_name}__{param_str}__{variation_hash}"
            if new_case_name in resolved_base_cases or new_case_name in expanded_cases:
                raise ValueError(
                    f"Generated variation case name '{new_case_name}' conflicts with an existing case name. Potential hash collision or duplicate variation definition."
                )

            new_case_info = copy.deepcopy(base_variation_template)

            # Merge params: variation params override base params
            # variation_params already extracted above
            output_params = copy.deepcopy(base_params)
            output_params.update(variation_params)
            new_case_info["params"] = output_params

            # Add/override other keys from variation_data (excluding 'params')
            for key, value in variation_data.items():
                if key != "params":
                    new_case_info[key] = value

            expanded_cases[new_case_name] = new_case_info

    return expanded_cases


def preprocess_test_cases(
    raw_test_cases: Dict[CaseName, CaseInfo],
) -> Dict[CaseName, CaseInfo]:
    """Applies all preprocessing steps: resolves bases and variations."""
    resolved_bases = resolve_bases(raw_test_cases)
    expanded_cases = resolve_variations(resolved_bases)
    return expanded_cases
