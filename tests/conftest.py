import json
import pathlib

import pytest


@pytest.fixture(scope="session")
def vectors() -> dict:
    return json.loads((pathlib.Path(__file__).parent / "data" / "traccar_vectors.json").read_text())
