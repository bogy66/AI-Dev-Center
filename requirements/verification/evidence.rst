ADC Verification Evidence
=========================

Evidence captured from actual, freshly-observed test execution during this
mapping task — never inferred from a test's mere existence or from
historical statements. Each item records the exact command run, the
observed result, and enough provenance for a future reviewer to reproduce
it.

Repository identity for all evidence below: HEAD commit
``072aab394d2ee987f29c2b5c6c3b2936eea59ae5``. Execution context: local
deterministic pytest run via ``venv/bin/python -m pytest``, no live/paid
provider calls, no Real-System-E2E.

.. evidence:: S1/S2 cluster — deterministic pytest run, all passing
   :id: EVID_001
   :status: draft
   :evidences: TEST_001, TEST_002, TEST_003, TEST_004, TEST_005, TEST_006, TEST_007, TEST_008, TEST_009

   Command::

      venv/bin/python -m pytest -q tests/test_common_request.py \
        tests/test_requirement_lineage.py tests/test_engineering_council.py \
        tests/test_engineering_decision.py \
        tests/test_s2_subsubsystem_architecture.py

   Observed: 382 passed, 0 failed, 1 warning (unrelated Pydantic
   deprecation notice), 1.80s. Observed 2026-09-18T14:47Z (session-local).

.. evidence:: S3 cluster — deterministic pytest run, all passing
   :id: EVID_002
   :status: draft
   :evidences: TEST_010, TEST_011, TEST_012, TEST_013, TEST_014, TEST_015, TEST_020

   Command::

      venv/bin/python -m pytest -q tests/test_toolchain_materializer.py \
        tests/test_setup_approval.py tests/test_execution_boundary.py \
        tests/test_setup_execution_state.py \
        tests/test_missing_toolchain_setup.py \
        tests/test_development_testing_integration.py

   Observed: 182 passed, 0 failed, 1 warning (unrelated Pydantic
   deprecation notice), 1.13s. Observed 2026-09-18T14:49Z (session-local).

.. evidence:: S4/S5 cluster — deterministic pytest run, all passing
   :id: EVID_003
   :status: draft
   :evidences: TEST_016, TEST_017, TEST_018, TEST_019, TEST_021, TEST_022, TEST_023, TEST_024, TEST_025, TEST_026, TEST_027

   Command::

      venv/bin/python -m pytest -q tests/test_s4_subsubsystem_architecture.py \
        tests/test_s5_subsubsystem_architecture.py tests/test_s4_s5_apply_gate.py \
        tests/test_testing_stage.py tests/test_controlled_rework_stage.py \
        tests/test_change_application.py tests/test_change_provenance.py \
        tests/test_diagnostic_evidence.py tests/test_development_testing_stage.py \
        tests/test_verification.py tests/test_verification_feasibility.py \
        tests/test_s43_s44_path_safety.py tests/test_s42_test_change_noop_contract.py \
        tests/test_rework_diagnostic_fidelity.py

   Observed: 324 passed, 0 failed, 8 warnings (unrelated pytest
   collection/Pydantic deprecation notices), 3.81s. Observed
   2026-09-18T14:52Z (session-local).

.. evidence:: S6/cross-cutting cluster — deterministic pytest run, all passing
   :id: EVID_004
   :status: draft
   :evidences: TEST_028, TEST_029, TEST_030

   Command::

      venv/bin/python -m pytest -q tests/test_controlled_git_stage.py \
        tests/test_controlled_publish_stage.py tests/test_final_approval.py \
        tests/test_central_diagnostic_trace.py

   Observed: 91 passed, 0 failed, 1 warning (unrelated Pydantic
   deprecation notice), 2.70s. Observed 2026-09-18T14:48Z (session-local).
