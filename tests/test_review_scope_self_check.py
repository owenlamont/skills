from pathlib import Path
import subprocess
from typing import Final


_ROOT: Final = Path(__file__).resolve().parent.parent


def test_review_scope_self_check_passes() -> None:
    done = subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(_ROOT / "skills/pr-review/scripts/review_scope.py"),
            "self-check",
        ],
        cwd=_ROOT,
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )

    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
