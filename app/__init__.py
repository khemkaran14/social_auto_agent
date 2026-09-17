import sys

if sys.version_info < (3, 11):
    raise RuntimeError(
        f"Social Auto Agent requires Python 3.11+, but this interpreter is "
        f"{sys.version_info.major}.{sys.version_info.minor}. Recreate your virtualenv with a "
        f"newer Python (e.g. `python3.11 -m venv .venv`) and reinstall dependencies."
    )
