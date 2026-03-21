import pytest


@pytest.fixture
def base_dir(tmp_path):
    return tmp_path


@pytest.fixture
def db(base_dir):
    from localknowledge.db import Database

    return Database(base_dir)
