"""Console-script launcher: `phantom-bridge-dashboard` -> `streamlit run app.py`."""

import sys
from pathlib import Path


def launch() -> None:
    from streamlit.web import cli as stcli

    app = str(Path(__file__).resolve().parent / "app.py")
    sys.argv = ["streamlit", "run", app]
    sys.exit(stcli.main())
