import base64
import copy
import hashlib
import json
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, ConfigDict, RootModel


CaseName = str

ModelConfig = ConfigDict(extra="allow")


class BaseCaseInfo(BaseModel):
    model_config = ModelConfig
    params: Dict[str, Any] = Field(default_factory=dict)
    harness: Optional[str] = None


class VariationItem(BaseModel):
    model_config = ModelConfig
    params: Dict[str, Any] = Field(default_factory=dict)


class VariationCaseInfo(BaseCaseInfo):
    variations: Optional[List[VariationItem]] = None


class ResolvableBaseCaseInfo(VariationCaseInfo):
    base: Optional[str] = None


class PreprocessedCaseInfo(BaseCaseInfo):
    # Harness is required in the final preprocessed case
    harness: str


class PreprocessedTestCasesFile(RootModel):
    root: dict[str, PreprocessedCaseInfo]


def resolve_bases(
    raw_test_cases: Dict[CaseName, ResolvableBaseCaseInfo],
) -> Dict[CaseName, VariationCaseInfo]:
    """Resolves 'base' references in test cases."""
    processed_cases: Dict[CaseName, VariationCaseInfo] = {}
    processing_stack: Set[CaseName] = set()

    def process_case(case_name: CaseName) -> VariationCaseInfo:
        if case_name in processed_cases:
            return processed_cases[case_name]
        if case_name not in raw_test_cases:
            raise ValueError(f"Base case '{case_name}' not found.")
        if case_name in processing_stack:
            raise ValueError(
                f"Circular dependency detected involving '{case_name}'. Stack: {processing_stack}"
            )

        current_case_info = raw_test_cases[case_name]
        processed_case_info: VariationCaseInfo

        if current_case_info.base is None:
            case_dict = current_case_info.model_dump(
                exclude={"base"}, exclude_unset=True
            )
            processed_case_info = VariationCaseInfo(**case_dict)
        else:
            processing_stack.add(case_name)
            try:
                base_name = current_case_info.base
                base_case_info = process_case(base_name)  # Returns VariationCaseInfo
                merged_data = base_case_info.model_dump(exclude_unset=True)

                current_data = current_case_info.model_dump(
                    exclude={"base"}, exclude_unset=True
                )

                # Merge top-level fields, current overrides base
                merged_data.update(current_data)

                # Special handling for 'params': deep merge, current overrides base
                base_params = base_case_info.params
                current_params = current_case_info.params
                merged_data["params"] = {**base_params, **current_params}

                # Create the final VariationCaseInfo from the merged data
                processed_case_info = VariationCaseInfo(**merged_data)

            finally:
                processing_stack.remove(case_name)  # Ensure removal even on error

        processed_cases[case_name] = processed_case_info
        return processed_case_info

    for name in raw_test_cases:
        process_case(name)

    return processed_cases


def resolve_variations(
    resolved_base_cases: Dict[CaseName, VariationCaseInfo],
) -> Dict[CaseName, PreprocessedCaseInfo]:
    """Expands test cases with 'variations' into individual cases."""
    expanded_cases: Dict[CaseName, PreprocessedCaseInfo] = {}

    for case_name, case_info in resolved_base_cases.items():
        if case_info.variations is None:
            case_dict = case_info.model_dump(exclude={"variations"}, exclude_unset=True)
            expanded_cases[case_name] = PreprocessedCaseInfo(**case_dict)
            continue

        variations_list = case_info.variations
        base_template_dict = case_info.model_dump(
            exclude={"variations"}, exclude_unset=True
        )
        base_params = case_info.params

        for i, variation_data in enumerate(variations_list):
            variation_params = variation_data.params
            param_str_parts = [f"{k}_{v}" for k, v in sorted(variation_params.items())]
            param_str = "_".join(param_str_parts)
            if len(param_str) > 50:
                param_str = param_str[:50] + "..."  # Indicate truncation

            variation_json = json.dumps(
                variation_data.model_dump(mode="json"), sort_keys=True
            )
            variation_hash = (
                base64.b64encode(hashlib.sha256(variation_json.encode()).digest())
                .rstrip(b"=")
                .decode("ascii")
            )  # Use standard b64 encoding, remove padding
            # Shorten hash if needed, ensure fixed length for predictability
            hash_len = 3
            variation_hash_short = variation_hash[:hash_len]

            new_case_name = f"{case_name}__{param_str}__{variation_hash_short}"
            if new_case_name in resolved_base_cases or new_case_name in expanded_cases:
                raise ValueError(
                    f"Generated variation case name '{new_case_name}' conflicts with an existing case name. "
                    f"Source case: '{case_name}', variation index: {i}. "
                    "Potential hash collision or duplicate variation definition."
                )

            new_case_data = copy.deepcopy(base_template_dict)  # Deep copy needed?

            output_params = {**base_params, **variation_params}
            new_case_data["params"] = output_params

            variation_other_data = variation_data.model_dump(
                exclude={"params"}, exclude_unset=True
            )
            new_case_data.update(variation_other_data)

            # Create and validate the final PreprocessedCaseInfo object
            expanded_cases[new_case_name] = PreprocessedCaseInfo(**new_case_data)

    return expanded_cases


def preprocess_test_cases(
    raw_test_cases: Dict[CaseName, Dict[str, Any]],  # Raw input is still Dict[str, Any]
) -> PreprocessedTestCasesFile:
    """Applies all preprocessing steps: resolves bases and variations."""
    parsed_cases: Dict[CaseName, ResolvableBaseCaseInfo] = {
        name: ResolvableBaseCaseInfo(**data) for name, data in raw_test_cases.items()
    }

    resolved_bases = resolve_bases(parsed_cases)

    expanded_cases = resolve_variations(resolved_bases)

    return PreprocessedTestCasesFile(root=expanded_cases)
