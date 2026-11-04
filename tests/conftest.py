from datetime import datetime

import pytest

from emporio import config
from emporio.data import load_store
from emporio.policies import load_policies
from emporio.tools import SessionState, build_tools

# Tuesday 3 Nov 2026, 10:00, store open. Orders in the data are from 2025/2026.
TODAY = datetime(2026, 11, 3, 10, 0, tzinfo=config.STORE_TZ)


@pytest.fixture(scope="session")
def store():
    return load_store()


@pytest.fixture(scope="session")
def policies():
    return load_policies()


@pytest.fixture
def state():
    return SessionState("test")


@pytest.fixture
def tools(store, policies, state, tmp_path):
    """The six tools as a dict: tools['search_products'](...)."""
    funcs = build_tools(store, policies, state, now_fn=lambda: TODAY, runtime_dir=tmp_path)
    return {f.__name__: f for f in funcs}
