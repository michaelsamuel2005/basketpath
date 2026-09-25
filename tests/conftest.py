import pytest

from basketpath import db, fixture


@pytest.fixture(scope="session")
def fx(tmp_path_factory):
    """Generated data with a known answer key, loaded exactly as the real export would be."""
    out = tmp_path_factory.mktemp("fixture")
    key = fixture.generate(out)
    return db.connect(out / "raw"), key, out
