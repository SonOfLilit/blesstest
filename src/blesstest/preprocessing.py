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
    variations: Optional[List["VariationItem"]] = None


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


def _generate_variation_name(
    base_name: CaseName,
    variation_data: VariationItem,
    variation_index: int,
    final_case_names: Set[CaseName],
    original_case_names: Set[CaseName],
) -> CaseName:
    """Generates a unique name for a variation, ensuring no collision with final/original names."""
    variation_params = variation_data.params

    if not variation_params:
        # If no params in this variation level, initial name is the base name.
        new_case_name = base_name
    else:
        # Generate name based on params
        param_str_parts = [f"{k}_{v}" for k, v in sorted(variation_params.items())]
        param_str = "__".join(param_str_parts)
        MAX_PARAM_STR_LEN = 32
        if len(param_str) <= MAX_PARAM_STR_LEN:
            new_case_name = f"{base_name}__{param_str}"
        else:
            variation_json = json.dumps(
                variation_data.model_dump(mode="json", exclude={"variations"}),
                sort_keys=True,
            )
            variation_hash = (
                base64.b64encode(hashlib.sha256(variation_json.encode()).digest())
                .rstrip(b"=")
                .decode("ascii")
            )
            hash_len = 3
            variation_hash_short = variation_hash[:hash_len]
            new_case_name = (
                f"{base_name}__{param_str[:MAX_PARAM_STR_LEN]}__{variation_hash_short}"
            )

    # Ensure uniqueness against final and original names by appending index if necessary
    original_new_case_name = new_case_name
    counter = 0
    # Check collision against the union of final generated names and original names
    collision_check_set = final_case_names.union(original_case_names)
    while new_case_name in collision_check_set:
        counter += 1
        # Use variation_index first for potentially more stable naming, then counter
        if counter == 1:
            new_case_name = f"{original_new_case_name}__{variation_index}"
        else:
            new_case_name = f"{original_new_case_name}__{variation_index}_{counter}"

        if counter > 10:  # Safety break
            raise ValueError(
                f"Could not generate unique name for variation of '{base_name}' (index {variation_index}) after {counter} attempts. Base name: {original_new_case_name}"
            )

    # Final check (should be redundant due to while loop but good for safety)
    if new_case_name in collision_check_set:
        raise ValueError(
            f"Generated variation case name '{new_case_name}' conflicts with an existing case name. "
            f"Source case: '{base_name}', variation index: {variation_index}. "
            "Potential hash collision or duplicate variation definition."
        )

    return new_case_name


def resolve_variations(
    resolved_base_cases: Dict[CaseName, VariationCaseInfo],
) -> Dict[CaseName, PreprocessedCaseInfo]:
    """Expands test cases with potentially nested 'variations' into individual cases."""
    expanded_cases: Dict[CaseName, PreprocessedCaseInfo] = {}
    original_names = set(resolved_base_cases.keys())

    def _expand_recursive(
        current_case_name: CaseName,
        current_case_info: VariationCaseInfo,
        accumulated_expanded_cases: Dict[CaseName, PreprocessedCaseInfo],
        original_input_names: Set[CaseName],
    ):
        """Recursive helper to expand variations."""
        # If no variations at this level, this is potentially a final test case
        if current_case_info.variations is None:
            # Check if a harness is defined for this leaf node
            if not current_case_info.harness:
                raise ValueError(
                    f"Test case leaf node '{current_case_name}' reached during variation expansion "
                    f"does not have a harness defined (neither directly nor inherited)."
                )

            # Convert VariationCaseInfo to PreprocessedCaseInfo before adding
            final_case_data = current_case_info.model_dump(exclude_unset=True)
            # Check for final collision before adding
            if current_case_name in accumulated_expanded_cases:
                # This check is important if we modify name generation not to add __index always
                raise ValueError(
                    f"Generated variation case name '{current_case_name}' conflicts with another expanded case name. "
                    "Potential hash collision or duplicate variation definition."
                )

            accumulated_expanded_cases[current_case_name] = PreprocessedCaseInfo(
                **final_case_data
            )
            # Do NOT add to all_names here, name uniqueness is handled within _generate_variation_name
            # all_names.add(current_case_name) # Removed
            return

        base_template_dict = current_case_info.model_dump(
            exclude={"variations"}, exclude_unset=True
        )
        base_params = current_case_info.params

        for i, variation_item in enumerate(current_case_info.variations):
            new_case_name = _generate_variation_name(
                current_case_name,
                variation_item,
                i,
                set(accumulated_expanded_cases.keys()),
                original_input_names,
            )
            # all_names.add(new_case_name) # Removed

            new_case_data = copy.deepcopy(base_template_dict)

            # Merge params: variation overrides current base
            output_params = {**base_params, **variation_item.params}
            new_case_data["params"] = output_params

            # Merge other top-level fields from variation (if any, besides params/variations)
            variation_other_data = variation_item.model_dump(
                exclude={"params", "variations"}, exclude_unset=True
            )
            new_case_data.update(variation_other_data)

            # Create the intermediate VariationCaseInfo for recursion
            next_level_case_info = VariationCaseInfo(**new_case_data)
            next_level_case_info.variations = variation_item.variations

            # Recursively expand the next level
            _expand_recursive(
                new_case_name,
                next_level_case_info,
                accumulated_expanded_cases,
                original_input_names,
            )

    # --- Main part of resolve_variations ---
    for case_name, case_info in resolved_base_cases.items():
        _expand_recursive(case_name, case_info, expanded_cases, original_names)

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
