"""Explicit target context for unit tests that enter S5 directly."""
import sys

from app.target_environment import (
    PROPERTY_ESTABLISHED,
    STATE_ESTABLISHED,
    EnvironmentProperty,
    TargetEnvironmentContext,
)


def established_test_target():
    """Model a previously resolved target without probing or using host PATH."""
    return TargetEnvironmentContext(
        state=STATE_ESTABLISHED,
        properties=(EnvironmentProperty(
            kind="interpreter", name="test target", state=PROPERTY_ESTABLISHED,
            target_executable=sys.executable,
        ),),
    )
