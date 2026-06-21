import os

import pytest

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def fixture_path():
    def _path(name: str) -> str:
        return os.path.join(FIXTURE_DIR, name)

    return _path
