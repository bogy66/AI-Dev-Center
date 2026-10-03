"""Requirements-only checks for adoption 026; no product execution/evidence."""
import json
import os
from pathlib import Path
import re

import pytest

from requirements.evidence.selector_map import (
    SELECTOR_MAP, LEGACY_COUNCIL_REPRODUCTIONS, resolve_selector,
)
from requirements.evidence.council_lifecycle_scope import COUNCIL_LIFECYCLE_OBLIGATIONS
from requirements.evidence.proof_obligations import derive_status
from requirements.status_model import compute_all_requirement_states, NOT_IMPLEMENTED, IMPLEMENTED_TEST_NIO, IMPLEMENTED_TEST_IO

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_SRC = Path(os.environ.get("ADC_REQUIREMENTS_SOURCE", ROOT / "requirements"))
EVIDENCE_STORE = os.environ.get("ADC_REQUIREMENTS_EVIDENCE_STORE")

SUB_IDS = {f"SUB_REQ_{i:03d}" for i in range(33, 41)}
TEST_IDS = set(COUNCIL_LIFECYCLE_OBLIGATIONS)


def _blocks(path, directive):
    source = path.read_text()
    blocks = re.split(r"(?=^\.\. " + directive + r"::)", source, flags=re.M)
    out = {}
    for block in blocks:
        match = re.search(r"^   :id: (\w+)$", block, re.M)
        if match:
            out[match[1]] = block
    return out


def test_adoption_is_scoped_and_contract_selectors_do_not_fabricate_evidence():
    subs = _blocks(REQUIREMENTS_SRC / "subsystem/subsystem_requirements.rst", "subreq")
    tests = _blocks(REQUIREMENTS_SRC / "verification/tests.rst", "test")
    from requirements.evidence.ingest import ingest_all_runs
    observed_results = ingest_all_runs(store_root=EVIDENCE_STORE, write=False).test_ids_updated
    covered = set()
    for sid in SUB_IDS:
        assert ':status: approved' in subs[sid]
        assert 'Acceptance:' in subs[sid]
        assert 'CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026' in subs[sid]
    for tid in TEST_IDS:
        observed = observed_results.get(tid, 'NOT_RUN')
        assert f':verification_result: {observed}' in tests[tid]
        covered.update(re.search(r":verifies: (.+)", tests[tid])[1].split(', '))
        assert SELECTOR_MAP[tid]
        assert all(resolve_selector(selector + '::contract_probe') == tid for selector in SELECTOR_MAP[tid])
        assert derive_status(required_tests=(), functional_result='IO',
                             all_selectors_collectible=True, extra_proof_gate_ok=True) == 'UNPROVEN'
    assert covered == SUB_IDS
    # Implementation associations are permissible; only actual test evidence
    # may establish compliance. Adoption must not forbid legitimate mappings.
    from requirements.evidence.council_lifecycle_scope import COUNCIL_CONTRACT_SELECTORS
    assert {tid: tuple(SELECTOR_MAP[tid]) for tid in TEST_IDS} == COUNCIL_CONTRACT_SELECTORS


def test_legacy_reproductions_cannot_claim_new_or_alternatives_compliance():
    assert LEGACY_COUNCIL_REPRODUCTIONS
    assert all(s.startswith('tests/test_engineering_council.py::') for s in SELECTOR_MAP['TEST_003'])
    for selector in LEGACY_COUNCIL_REPRODUCTIONS:
        assert resolve_selector(selector) is None
    assert resolve_selector('tests/test_engineering_council.py::TestPhase1DataIsolation::example') == 'TEST_003'


def test_only_unexecuted_obligations_may_lack_evidence():
    from jsonschema import Draft202012Validator
    schema = json.loads((REQUIREMENTS_SRC / 'schemas.json').read_text())
    rule = next(r for r in schema['schemas'] if r['id'] == 'test-has-evidence')
    validator = Draft202012Validator({**rule['select'], '$defs': schema['$defs']})
    assert not validator.is_valid({'type': 'test', 'verification_result': 'NOT_RUN'})
    for result in ('IO', 'NIO'):
        assert validator.is_valid({'type': 'test', 'verification_result': result})
    state_rule = next(r for r in schema['schemas'] if r['id'] == 'test-verification-state')
    state_validator = Draft202012Validator(state_rule['validate']['local'])
    assert not state_validator.is_valid({'verification_result': 'INVALID'})
    assert not state_validator.is_valid({})
    assert state_validator.is_valid({'verification_result': 'NOT_RUN'})
    assert rule['validate']['network_back']['evidences']['minContains'] == 1


@pytest.mark.parametrize('language', ['en', 'de'])
def test_built_contract_keeps_approval_and_evidence_truthful(language):
    build_root = Path(os.environ.get('ADC_REQUIREMENTS_BUILD_ROOT', ROOT / 'requirements/_build'))
    data = json.loads((build_root / 'html' / language / 'needs.json').read_text())
    needs = next(iter(data['versions'].values()))['needs']
    states = compute_all_requirement_states(needs)
    from requirements.evidence.ingest import ingest_all_runs
    observed = ingest_all_runs(store_root=EVIDENCE_STORE, write=False).test_ids_updated
    for sid in SUB_IDS:
        assert needs[sid]['status'] == 'approved'
        implementations = [nid for nid, need in needs.items() if sid in need.get('implements', [])]
        tid = f'TEST_{36 + (int(sid[-3:]) - 33) // 2:03d}'
        expected = (IMPLEMENTED_TEST_IO if observed.get(tid) == 'IO' else IMPLEMENTED_TEST_NIO) if implementations else NOT_IMPLEMENTED
        assert states[sid] == expected  # A mapping alone must never produce IO.
    for tid in TEST_IDS:
        result = observed.get(tid, 'NOT_RUN')
        assert needs[tid]['verification_result'] == result
        if result in ('IO', 'NIO'):
            assert needs[tid].get('evidences_back'), 'executed obligation lacks actual Evidence'
    assert all(needs[f'SUB_REQ_{i:03d}']['status'] == 'draft' for i in range(1, 33))
    assert all(needs[f'IF_REQ_{i:03d}']['status'] == 'draft' for i in range(1, 37))
    violations = json.loads((build_root / 'html' / language / 'schema_violations.json').read_text())
    assert not violations['validation_warnings']


@pytest.mark.parametrize('language', ['en', 'de'])
def test_legitimate_implementation_association_does_not_create_acceptance(language):
    build_root = Path(os.environ.get('ADC_REQUIREMENTS_BUILD_ROOT', ROOT / 'requirements/_build'))
    data = json.loads((build_root / 'html' / language / 'needs.json').read_text())
    needs = next(iter(data['versions'].values()))['needs']
    # In-memory fixture only: normative requirements and implementation RST
    # are not altered. A legitimate association is allowed, but NOT_RUN must
    # continue to block a green result without actual evidence.
    needs['IMPL_CONTRACT_FIXTURE'] = {'type': 'impl', 'implements': sorted(SUB_IDS)}
    # Preserve the original negative protection independently of current
    # execution history: a mapping plus NOT_RUN can never establish IO.
    for tid in TEST_IDS:
        needs[tid]['verification_result'] = 'NOT_RUN'
    states = compute_all_requirement_states(needs)
    assert all(states[sid] == IMPLEMENTED_TEST_NIO for sid in SUB_IDS)
