"""Start the local demo without storing a password in the repository."""
import getpass
import os
from pathlib import Path
import subprocess
import sys
import warnings


def main():
    env = os.environ.copy()
    if not env.get("DEMO_PASSWORD"):
        # Refuse getpass's echoing fallback when no secure terminal is available.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                password = getpass.getpass("Mat khau demo (khong luu vao tep): ")
            except getpass.GetPassWarning:
                raise SystemExit("Can terminal an mat khau hoac bien DEMO_PASSWORD.")
        if not password:
            raise SystemExit("Can nhap mat khau demo.")
        env["DEMO_PASSWORD"] = password
    return subprocess.call(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8000", "--no-proxy-headers", "--no-access-log"],
        cwd=Path(__file__).resolve().parents[1], env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
