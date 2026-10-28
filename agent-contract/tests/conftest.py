from pathlib import Path

import pytest

from autogenesis_agent_contract import load_contract


@pytest.fixture
def contract():
    return load_contract()


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def anyio_backend():
    return "asyncio"
