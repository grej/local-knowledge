import pytest


@pytest.fixture
def base_dir(tmp_path):
    return tmp_path
