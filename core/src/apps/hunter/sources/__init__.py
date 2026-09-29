from . import hh

ADAPTERS = (hh,)


def adapter_for(url: str):
    return next((adapter for adapter in ADAPTERS if adapter.handles(url)), None)
