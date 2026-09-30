from . import hh, indeed, linkedin
from .base import CONTRACT

ADAPTERS = (hh, linkedin)
LOGIN_SITES = (hh, linkedin, indeed)


def adapter_for(url: str):
    return next((adapter for adapter in ADAPTERS if adapter.handles(url)), None)


def adapter_named(site: str):
    return next((adapter for adapter in LOGIN_SITES if adapter.SITE == site), None)


def missing_contract(adapter) -> list[str]:
    return [name for name in CONTRACT if not hasattr(adapter, name)]
