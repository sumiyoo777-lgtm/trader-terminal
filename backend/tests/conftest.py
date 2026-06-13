"""Test bootstrap: point the app at a throwaway SQLite file and disable the
scheduler/demo seed BEFORE any app module is imported."""
import os
import pathlib

_TEST_DB = pathlib.Path(__file__).parent / "_test_terminal.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["DEMO_SEED"] = "false"
os.environ["ENABLE_LOCAL_KRONOS"] = "false"
os.environ["FLASHALPHA_API_KEY"] = ""  # never use a real key in tests
os.environ["ENABLE_SELF_COMPUTED_GEX"] = "false"  # no network in tests
