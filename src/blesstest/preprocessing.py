import base64
import hashlib
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


class PreprocessedCaseInfo(BaseCaseInfo):
    # Harness is required in the final preprocessed case
    pass


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
        edited_variation = original_variation.copy(
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
) -> Dict[CaseName, PreprocessedCaseInfo]:
    """Expands test cases with potentially nested 'variations' into individual cases."""
    expanded_cases: Dict[CaseName, PreprocessedCaseInfo] = {}
    original_names = set(resolved_base_cases.keys())

    def _expand_recursive(
        current_case_name: CaseName,
        current_case_info: CaseInfo,
        accumulated_expanded_cases: Dict[CaseName, PreprocessedCaseInfo],
        original_input_names: Set[CaseName],
    ):
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

            case = PreprocessedCaseInfo(**current_case_info.__dict__)
            accumulated_expanded_cases[current_case_name] = case
            return

        for variation_item in current_case_info.variations:
            new_case_name = _generate_variation_name(
                current_case_name,
                variation_item,
            )

            if new_case_name in accumulated_expanded_cases:
                raise ValueError(
                    f"Could not generate unique name for variation of '{current_case_name}'. Base name: {new_case_name}"
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


def preprocess_test_cases(
    raw_test_cases: Dict[CaseName, Dict[str, Any]],
) -> PreprocessedTestCasesFile:
    """Applies all preprocessing steps: resolves bases and variations."""
    parsed_cases: Dict[CaseName, ResolvableBaseCaseInfo] = {
        name: ResolvableBaseCaseInfo(**data) for name, data in raw_test_cases.items()
    }

    resolved_bases = resolve_bases(parsed_cases)

    expanded_cases = resolve_variations(resolved_bases)
    expanded_cases = {
        name: case for name, case in expanded_cases.items() if not case.abstract
    }

    return PreprocessedTestCasesFile(root=expanded_cases)
