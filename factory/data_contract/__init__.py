"""Generated data validators; regenerate with python -m factory.data_contract.generate."""

from factory.data_contract.errors import DataError


def validate_price_bars(*args, **kwargs):
    from factory.data_contract.generated import validate_price_bars as validate

    return validate(*args, **kwargs)


def validate_events(*args, **kwargs):
    from factory.data_contract.generated import validate_events as validate

    return validate(*args, **kwargs)


__all__ = ["DataError", "validate_price_bars", "validate_events"]
