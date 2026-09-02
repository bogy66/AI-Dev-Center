"""Stable execution identities for central workflow processors."""

ADC_IMPLEMENTATION_VERSION = "adc-python-1"


def execution_identity(
    entity: str, *, provider: str | None = None,
    model: str | None = None, model_version: str | None = None,
    **dependencies,
) -> dict:
    """Return only genuinely known, structured determinants of a processor."""
    identity = {
        "entity": entity,
        "entity_version": 1,
        "implementation_version": ADC_IMPLEMENTATION_VERSION,
    }
    if provider:
        identity["provider"] = provider
    if model:
        identity["model"] = model
    if model_version:
        identity["model_version"] = model_version
    identity.update({key: value for key, value in dependencies.items() if value is not None})
    return identity
