from pathlib import Path
from app.test_stack_detector import TestStackDetector


class TesterValidator:
    __test__ = False
    """Validates tester output using the adapter obtained from TestStackDetector."""

    def __init__(self):
        self._detector = TestStackDetector()

    def validate(self, project_root: str, changes: list, level: str = "unit", environment: str = "host") -> dict:
        """
        Validate the tester changes using the detected adapter.

        Args:
            project_root: Absolute path to the project (or workspace) root.
            changes: List of change dicts as returned by DeveloperChanges.parse().
                     Each dict has keys "file", "action", "content".
            level: Test level (default "unit").
            environment: Test environment (default "host").

        Returns:
            dict with keys:
                success (bool): True if all checks pass.
                errors (list[str]): List of error messages.
                strategy (TestStrategy | None): detected strategy on success.
        """
        root = Path(project_root)
        adapter = self._detector.detect(str(root))

        if adapter is None:
            return {
                "success": False,
                "errors": ["Kein unterstützter Test-Stack erkannt."],
                "strategy": None
            }

        # Obtain the strategy to get the stack name for error messages
        strategy = adapter.get_strategy(level, environment)
        stack_name = strategy.stack

        errors = []
        has_test_file = False

        for change in changes:
            action = change.get("action", "")
            if action not in ("create", "update"):
                continue  # delete actions are irrelevant

            file_path = change.get("file", "")
            content = change.get("content", "")

            if not adapter.is_test_file(file_path):
                errors.append(
                    f"File '{file_path}' is not a valid test file for "
                    f"the detected test stack ({stack_name})."
                )
                continue

            has_test_file = True

            file_errors = adapter.validate_test_file(file_path, content)
            if not file_errors.get("success", True):
                error_list = file_errors.get("errors", [])
                errors.extend(error_list)

        if not has_test_file:
            errors.append(
                f"No test file was created or updated for the detected "
                f"test stack ({stack_name})."
            )

        success = len(errors) == 0
        if not success:
            strategy = None
        return {"success": success, "errors": errors, "strategy": strategy}
