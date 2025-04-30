import base64
import hashlib
import re
import itertools
from typing import Any, Dict, List, NewType, Optional, Set

from pydantic import BaseModel, Field, RootModel


CaseName = NewType("CaseName", str)
ParamName = NewType("ParamName", str)
ParamValue = Any


class BaseCaseInfo(BaseModel):
    abstract: bool = False
    params: Dict[ParamName, ParamValue] = Field(default_factory=dict)
    harness: Optional[str] = None


class CaseInfo(BaseCaseInfo):
    name: Optional[str] = None
    variations: Optional[List["CaseInfo"]] = None


class ResolvableBaseCaseInfo(CaseInfo):
    base: Optional[CaseName] = None


class PreprocessedCaseInfo(BaseModel):
    params: Dict[ParamName, ParamValue] = Field(default_factory=dict)
    harness: str


class PreprocessedTestCasesFile(RootModel):
    root: dict[CaseName, PreprocessedCaseInfo]


def resolve_bases(
    raw_test_cases: Dict[CaseName, ResolvableBaseCaseInfo],
) -> Dict[CaseName, CaseInfo]:
    """Resolves 'base' references in test cases."""
    processed_cases: Dict[CaseName, CaseInfo] = {}
    processing_stack: Set[CaseName] = set()

    def process_case(case_name: CaseName) -> CaseInfo:
        if case_name in processed_cases:
            return processed_cases[case_name]
        if case_name not in raw_test_cases:
            raise ValueError(f"Base case '{case_name}' not found.")
        if case_name in processing_stack:
            raise ValueError(
                f"Circular dependency detected involving '{case_name}'. Stack: {processing_stack}"
            )

        current_case_info = raw_test_cases[case_name]
        processed_case_info: CaseInfo

        if current_case_info.base is None:
            processed_case_info = current_case_info
        else:
            processing_stack.add(case_name)
            try:
                base_case_info = process_case(current_case_info.base)
            finally:
                processing_stack.remove(case_name)  # Ensure removal even on error

            processed_case_info = _merge_base_and_variation(
                base_case_info,
                current_case_info,
                preserve_abstract=False,
            )

        processed_cases[case_name] = processed_case_info
        return processed_case_info

    for name in raw_test_cases:
        process_case(name)

    return processed_cases


def _check_conflict(original_variation: CaseInfo, dont_conflict_with: CaseInfo) -> None:
    # If any of the attributes exist in both, and are different, raise an error
    if (
        original_variation.harness
        and dont_conflict_with.harness
        and original_variation.harness != dont_conflict_with.harness
    ):
        raise ValueError(
            f"Case {original_variation} conflicts with {dont_conflict_with}: Both have a harness but it is different: {original_variation.harness} != {dont_conflict_with.harness}"
        )
    for param_name, param_value in original_variation.params.items():
        if param_name in dont_conflict_with.params:
            if dont_conflict_with.params[param_name] != param_value:
                raise ValueError(
                    f"Case {original_variation} conflicts with {dont_conflict_with}: Both have a param '{param_name}' but it is different: {param_value} != {dont_conflict_with.params[param_name]}"
                )


def _expand_variations(
    original_variations: List[CaseInfo] | None,
    variations_to_add: List[CaseInfo] | None,
    dont_conflict_with: CaseInfo,
) -> List[CaseInfo] | None:
    for original_variation in original_variations or []:
        _check_conflict(original_variation, dont_conflict_with)

    if not original_variations:
        return variations_to_add
    if not variations_to_add:
        return original_variations

    edited_variations: List[CaseInfo] = []
    for original_variation in original_variations:
        some_edited_sub_variations = _expand_variations(
            variations_to_add=variations_to_add,
            original_variations=original_variation.variations,
            dont_conflict_with=dont_conflict_with,
        )
        edited_variation = original_variation.model_copy(
            update={"variations": some_edited_sub_variations}
        )
        if some_edited_sub_variations:
            edited_variations.append(edited_variation)

    if len(edited_variations) == 0:
        return None
    else:
        return edited_variations


def _merge_base_and_variation(
    base_case: CaseInfo,
    variant_case: CaseInfo,
    preserve_abstract: bool,
) -> CaseInfo:
    variant_case_variations = _expand_variations(
        original_variations=base_case.variations,
        variations_to_add=variant_case.variations,
        dont_conflict_with=variant_case,
    )

    return CaseInfo(
        abstract=variant_case.abstract or (preserve_abstract and base_case.abstract),
        name=variant_case.name,
        params={
            **base_case.params,
            **variant_case.params,
        },
        harness=variant_case.harness or base_case.harness,
        variations=variant_case_variations,
    )


def _generate_variation_name(
    base_name: CaseName,
    variation_data: CaseInfo,
) -> CaseName:
    """Generates a unique name for a variation, ensuring no collision with final/original names."""

    if variation_data.name:
        return CaseName(f"{base_name}__{variation_data.name}")

    variation_params = variation_data.params

    param_str_parts = [f"{k}_{v}" for k, v in sorted(variation_params.items())]
    if variation_data.harness:
        param_str_parts.insert(0, variation_data.harness)
    if not param_str_parts:
        new_case_name = base_name
    else:
        param_str = "__".join(param_str_parts)
        MAX_PARAM_STR_LEN = 32
        if len(param_str) <= MAX_PARAM_STR_LEN:
            new_case_name = CaseName(f"{base_name}__{param_str}")
        else:
            variation_hash = (
                base64.b64encode(hashlib.sha256(param_str.encode()).digest())
                .rstrip(b"=")
                .decode("ascii")
            )
            hash_len = 3
            variation_hash_short = variation_hash[:hash_len]
            new_case_name = CaseName(
                f"{base_name}__{param_str[:MAX_PARAM_STR_LEN]}__{variation_hash_short}"
            )

    return new_case_name


def resolve_variations(
    resolved_base_cases: Dict[CaseName, CaseInfo],
) -> Dict[CaseName, BaseCaseInfo]:
    """Expands test cases with potentially nested 'variations' into individual cases."""
    expanded_cases: Dict[CaseName, BaseCaseInfo] = {}
    original_names = set(resolved_base_cases.keys())

    def _expand_recursive(
        current_case_name: CaseName,
        current_case_info: CaseInfo,
        accumulated_expanded_cases: Dict[CaseName, BaseCaseInfo],
        original_input_names: Set[CaseName],
    ) -> None:
        """Recursive helper to expand variations."""
        if current_case_info.variations is None:
            if not current_case_info.harness and not current_case_info.abstract:
                raise ValueError(
                    f"Test case leaf node '{current_case_name}' reached during variation expansion "
                    f"does not have a harness defined (neither directly nor inherited)."
                )

            if current_case_name in accumulated_expanded_cases:
                raise ValueError(
                    f"Generated variation case name '{current_case_name}' conflicts with another expanded case name. "
                    "Potential hash collision or duplicate variation definition."
                )

            accumulated_expanded_cases[current_case_name] = current_case_info
            return

        for variation_item in current_case_info.variations:
            new_case_name = _generate_variation_name(
                current_case_name,
                variation_item,
            )

            current_case_without_variations = current_case_info.model_copy(
                update={"variations": None}
            )

            merged_case_info = _merge_base_and_variation(
                base_case=current_case_without_variations,
                variant_case=variation_item,
                preserve_abstract=True,
            )

            _expand_recursive(
                new_case_name,
                merged_case_info,
                accumulated_expanded_cases,
                original_input_names,
            )

    for case_name, case_info in resolved_base_cases.items():
        _expand_recursive(case_name, case_info, expanded_cases, original_names)

    return expanded_cases


def ensure_string(input: Any) -> str:
    if not isinstance(input, str):
        raise ValueError(f"Expected a string, got {type(input)}: {input}")
    return input


def _expand_parameter_variations(
    case_info: CaseInfo,
) -> None:
    """Recursively expands parameter variations like '[a]' and '[[a,b]]',
    computing Cartesian product if multiple exist at the same level.
    Raises error if explicit variations and param variations co-exist at the same level.
    """
    param_variation_groups: List[List[Dict[ParamName, ParamValue]]] = []
    params_to_remove: List[str] = []
    explicit_variations = case_info.variations  # Store original explicit variations
    has_param_variations = False

    # 1. Collect parameter variation specifications for the CURRENT level
    for param_key, param_value in list(case_info.params.items()):
        is_param_variation = False
        single_match = re.fullmatch(r"\[(\w+)\]", param_key)
        if single_match and isinstance(param_value, list):
            params_to_remove.append(param_key)
            param_name = ParamName(single_match.group(1))
            group = [{param_name: v} for v in param_value]
            param_variation_groups.append(group)
            is_param_variation = True
            # continue # Don't continue, need to check multi_match as well for conflict detection

        multi_match = re.fullmatch(r"\[\[(\w+(?:,\s*\w+)*)\]\]", param_key)
        if multi_match and isinstance(param_value, list):
            if is_param_variation:  # Prevent matching both [a] and [[a]] for the same key if needed? unlikely
                raise ValueError(f"Ambiguous parameter variation key '{param_key}'.")
            params_to_remove.append(param_key)
            param_names = [
                ParamName(p.strip()) for p in multi_match.group(1).split(",")
            ]
            group = []
            for value_tuple in param_value:
                if not isinstance(value_tuple, list) or len(value_tuple) != len(
                    param_names
                ):
                    raise ValueError(
                        f"Invalid value format for '{param_key}'. "
                        f"Expected list of lists with length {len(param_names)}, got {value_tuple}"
                    )
                variation_params = dict(zip(param_names, value_tuple))
                group.append(variation_params)
            param_variation_groups.append(group)
            is_param_variation = True

        if is_param_variation:
            has_param_variations = True

    # 2. Check for conflict: explicit variations AND parameter variations at the same level
    if explicit_variations and has_param_variations:
        raise ValueError(
            "Cannot define both explicit 'variations' and parameter variations (e.g., '[a]' or '[[a, b]]') at the same level."
        )

    # 3. Process parameter variations for the CURRENT level if they exist
    if param_variation_groups:
        # Remove the variation-generating keys from original params
        for key in params_to_remove:
            del case_info.params[ParamName(key)]

        # Compute Cartesian product
        combined_param_variations: List[CaseInfo] = []
        product_results = list(itertools.product(*param_variation_groups))

        for param_tuple in product_results:
            merged_params: Dict[ParamName, ParamValue] = {}
            for param_dict in param_tuple:
                overlapping_keys = merged_params.keys() & param_dict.keys()
                if overlapping_keys:
                    raise ValueError(
                        f"Overlapping parameter keys found during variation expansion: {overlapping_keys}"
                    )
                merged_params.update(param_dict)
            combined_param_variations.append(CaseInfo(params=merged_params))

        # If product is empty, variations list should be empty
        case_info.variations = (
            combined_param_variations if combined_param_variations else None
        )
        # Note: We intentionally discard explicit_variations here because they conflict

    # 4. Recurse into the variations (either original explicit or newly generated ones)
    if case_info.variations:
        for variation in case_info.variations:
            # We pass the variation object itself, which is modified in place
            _expand_parameter_variations(variation)


def preprocess_test_cases(
    raw_test_cases: Dict[CaseName, Dict[str, Any]],
) -> PreprocessedTestCasesFile:
    """Applies all preprocessing steps: resolves bases and variations."""
    parsed_cases: Dict[CaseName, ResolvableBaseCaseInfo] = {
        name: ResolvableBaseCaseInfo(**data) for name, data in raw_test_cases.items()
    }

    # Expand parameter variations recursively first
    for case_info in parsed_cases.values():
        _expand_parameter_variations(case_info)

    resolved_bases = resolve_bases(parsed_cases)

    expanded_cases = resolve_variations(resolved_bases)
    concrete_cases: dict[CaseName, PreprocessedCaseInfo] = {
        name: PreprocessedCaseInfo(
            params=case.params,
            harness=ensure_string(case.harness),
        )
        for name, case in expanded_cases.items()
        if not case.abstract
    }

    return PreprocessedTestCasesFile(root=concrete_cases)
