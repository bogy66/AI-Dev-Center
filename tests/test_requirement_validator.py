from app.requirement_model import (
    Requirement,
    RequirementEvidence,
    ValidationResult,
)
from app.requirement_validator import RequirementValidator


def _make_req(**overrides):
    defaults = {
        "id": "req-1",
        "name": "python",
        "type": "executable",
        "purpose": "run scripts",
        "required": True,
        "confidence": 0.9,
        "evidence": (
            RequirementEvidence(
                id="ev1",
                source_type="manual",
                description="found",
            ),
        ),
        "source_file": None,
        "detected_version": None,
        "required_version": None,
        "install_method": None,
        "verification_method": None,
        "status": "discovered",
        "metadata": {},
    }
    defaults.update(overrides)
    return Requirement(**defaults)


def test_valid_requirement_no_warnings():
    req = _make_req()
    result = RequirementValidator.validate([req])
    assert result.valid is True
    assert result.errors == ()
    assert result.warnings == ()
    assert result.normalized_requirements == (req,)
    assert result.required_requirements == (req,)
    assert result.optional_requirements == ()
    assert result.rejected_requirements == ()
    assert result.requirements == (req,)


def test_empty_name_is_invalid():
    req = _make_req(name="")
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert len(result.errors) == 1
    assert "name" in result.errors[0]
    assert result.rejected_requirements == (req,)
    assert result.normalized_requirements == ()


def test_whitespace_only_name_is_invalid():
    req = _make_req(name="   ")
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("name" in e for e in result.errors)


def test_empty_type_is_invalid():
    req = _make_req(type="")
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("type" in e for e in result.errors)


def test_empty_purpose_is_invalid():
    req = _make_req(purpose="")
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("purpose" in e for e in result.errors)


def test_confidence_above_one_is_invalid():
    req = _make_req(confidence=1.5)
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("confidence" in e for e in result.errors)


def test_confidence_below_zero_is_invalid():
    req = _make_req(confidence=-0.1)
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("confidence" in e for e in result.errors)


def test_confidence_not_number_is_invalid():
    req = _make_req(confidence="high")
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("confidence" in e for e in result.errors)


def test_required_not_bool_is_invalid():
    req = _make_req(required=1)
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("required" in e for e in result.errors)


def test_install_method_empty_string_is_invalid():
    req = _make_req(install_method="")
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("install_method" in e for e in result.errors)


def test_install_method_whitespace_is_invalid():
    req = _make_req(install_method="   ")
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("install_method" in e for e in result.errors)


def test_verification_method_empty_string_is_invalid():
    req = _make_req(verification_method="")
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("verification_method" in e for e in result.errors)


def test_verification_method_whitespace_is_invalid():
    req = _make_req(verification_method="\t")
    result = RequirementValidator.validate([req])
    assert result.valid is False
    assert any("verification_method" in e for e in result.errors)


def test_missing_evidence_generates_warning():
    req = _make_req(evidence=())
    result = RequirementValidator.validate([req])
    assert result.valid is True
    assert len(result.warnings) == 1
    assert "evidence" in result.warnings[0]
    assert result.normalized_requirements == (req,)


def test_required_low_confidence_generates_warning():
    req = _make_req(required=True, confidence=0.3)
    result = RequirementValidator.validate([req])
    assert result.valid is True
    assert len(result.warnings) == 1
    assert "confidence" in result.warnings[0]
    assert result.required_requirements == (req,)


def test_optional_low_confidence_no_warning():
    req = _make_req(required=False, confidence=0.3)
    result = RequirementValidator.validate([req])
    assert result.valid is True
    assert result.warnings == ()
    assert result.optional_requirements == (req,)


def test_unknown_type_is_allowed():
    req = _make_req(type="unknown")
    result = RequirementValidator.validate([req])
    assert result.valid is True
    assert result.normalized_requirements == (req,)


def test_invalid_requirement_does_not_block_others():
    valid_req = _make_req(id="valid")
    invalid_req = _make_req(id="invalid", name="")
    result = RequirementValidator.validate([valid_req, invalid_req])
    assert result.valid is False
    assert result.normalized_requirements == (valid_req,)
    assert result.required_requirements == (valid_req,)
    assert result.rejected_requirements == (invalid_req,)
    assert len(result.errors) == 1


def test_mixed_valid_invalid_and_optional():
    req_valid_required = _make_req(id="r1", required=True)
    req_valid_optional = _make_req(id="o1", required=False)
    req_invalid = _make_req(id="bad", purpose="   ")
    reqs = [req_valid_required, req_valid_optional, req_invalid]
    result = RequirementValidator.validate(reqs)
    assert result.valid is False
    assert result.normalized_requirements == (req_valid_required, req_valid_optional)
    assert result.required_requirements == (req_valid_required,)
    assert result.optional_requirements == (req_valid_optional,)
    assert result.rejected_requirements == (req_invalid,)
    assert len(result.errors) == 1


def test_empty_input():
    result = RequirementValidator.validate([])
    assert result.valid is True
    assert result.requirements == ()
    assert result.normalized_requirements == ()
    assert result.required_requirements == ()
    assert result.optional_requirements == ()
    assert result.rejected_requirements == ()
    assert result.errors == ()
    assert result.warnings == ()


def test_no_mutation_of_input_objects():
    req = _make_req()
    original_name = req.name
    original_type = req.type
    original_confidence = req.confidence
    RequirementValidator.validate([req])
    assert req.name == original_name
    assert req.type == original_type
    assert req.confidence == original_confidence
