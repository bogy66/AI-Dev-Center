import re
from pathlib import Path


class RequirementsManager:
    """Manages requirements for a workflow, including parsing and validation."""

    @staticmethod
    def parse_requirements_from_task(task):
        """
        Parse requirements from a task description.
        
        Looks for REQ-xxx patterns in the task description.
        If none found, creates a single default requirement.
        """
        # Look for REQ-xxx patterns
        req_pattern = r'REQ-(\d{3})'
        matches = re.findall(req_pattern, task)
        
        if matches:
            requirements = []
            for match in matches:
                requirements.append({
                    "id": f"REQ-{match}",
                    "description": f"Requirement REQ-{match}",
                    "status": "pending",
                    "tests": []
                })
            return requirements
        
        # If no REQ patterns found, create a single default requirement
        return [{
            "id": "REQ-001",
            "description": "Default requirement from task",
            "status": "pending",
            "tests": []
        }]

    @staticmethod
    def validate_requirements(requirements):
        """Validate that requirements have the expected structure."""
        if not requirements:
            return False
        
        for req in requirements:
            if not isinstance(req, dict):
                return False
            if "id" not in req or "description" not in req:
                return False
            if not req["id"].startswith("REQ-"):
                return False
        
        return True

    @staticmethod
    def assign_tests_to_requirements(requirements, tests):
        """
        Assign tests to requirements.
        
        Looks for REQ-xxx patterns in test names or descriptions.
        """
        for req in requirements:
            req_tests = []
            for test in tests:
                if req["id"] in test:
                    req_tests.append(test)
            req["tests"] = req_tests
            req["status"] = "assigned" if req_tests else "pending"
        
        return requirements
