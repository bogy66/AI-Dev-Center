from app.requirement_model import Requirement, ValidationResult


class RequirementValidator:
    """Deterministic validation for a list of requirements.

    Each requirement is validated independently. Invalid requirements are
    moved to ``rejected_requirements`` without blocking the validation of
    the remaining requirements.
    """

    @staticmethod
    def validate(requirements):
        errors = []
        warnings = []
        normalized = []
        required_list = []
        optional_list = []
        rejected_list = []

        for req in requirements:
            req_errors = []
            req_warnings = []

            # name
            if not isinstance(req.name, str) or not req.name.strip():
                req_errors.append(
                    f"Requirement '{req.id}': name must be a non-empty string."
                )

            # type
            if not isinstance(req.type, str) or not req.type.strip():
                req_errors.append(
                    f"Requirement '{req.id}': type must be a non-empty string."
                )

            # purpose
            if not isinstance(req.purpose, str) or not req.purpose.strip():
                req_errors.append(
                    f"Requirement '{req.id}': purpose must be a non-empty string."
                )

            # confidence
            if not isinstance(req.confidence, (int, float)) or not (
                0.0 <= req.confidence <= 1.0
            ):
                req_errors.append(
                    f"Requirement '{req.id}': confidence must be between 0.0 and 1.0."
                )

            # required must be bool
            if not isinstance(req.required, bool):
                req_errors.append(
                    f"Requirement '{req.id}': required must be a boolean."
                )

            # install_method, if present, must be non-empty
            if req.install_method is not None and (
                not isinstance(req.install_method, str)
                or not req.install_method.strip()
            ):
                req_errors.append(
                    f"Requirement '{req.id}': install_method must be a non-empty string when provided."
                )

            # verification_method, if present, must be non-empty
            if req.verification_method is not None and (
                not isinstance(req.verification_method, str)
                or not req.verification_method.strip()
            ):
                req_errors.append(
                    f"Requirement '{req.id}': verification_method must be a non-empty string when provided."
                )

            # missing evidence -> warning
            if not req.evidence:
                req_warnings.append(f"Requirement '{req.id}': missing evidence.")

            # required with low confidence -> warning
            if (
                req.required
                and isinstance(req.confidence, (int, float))
                and 0.0 <= req.confidence <= 1.0
                and req.confidence < 0.5
            ):
                req_warnings.append(
                    f"Requirement '{req.id}': required with low confidence."
                )

            if req_errors:
                errors.extend(req_errors)
                warnings.extend(req_warnings)
                rejected_list.append(req)
            else:
                warnings.extend(req_warnings)
                normalized.append(req)
                if req.required:
                    required_list.append(req)
                else:
                    optional_list.append(req)

        result = ValidationResult(
            id="validation-result",
            valid=len(errors) == 0,
            requirements=tuple(requirements),
            errors=tuple(errors),
            warnings=tuple(warnings),
            normalized_requirements=tuple(normalized),
            required_requirements=tuple(required_list),
            optional_requirements=tuple(optional_list),
            rejected_requirements=tuple(rejected_list),
        )
        return result
