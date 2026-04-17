import pathlib
import pytest
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

THREADS_DIR = pathlib.Path(__file__).parent.parent / "schema-validation" / "threads"


def _load(filename: str) -> str:
    return (THREADS_DIR / filename).read_text()


@pytest.fixture
def thread_a():
    return _load("thread-a-incident.md")


@pytest.fixture
def thread_b():
    return _load("thread-b-qa.md")


@pytest.fixture
def thread_c():
    return _load("thread-c-howto.md")


@pytest.fixture
def thread_d():
    return _load("thread-d-sparse.md")
