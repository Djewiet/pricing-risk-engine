"""The examples quoted in the README and the docs must keep running."""

import re
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
EXAMPLES = sorted((ROOT / "examples").glob("*.py"))
README_BLOCKS = re.findall(r"```python\n(.*?)```", (ROOT / "README.md").read_text(), re.S)


@pytest.mark.parametrize("script", EXAMPLES, ids=lambda p: p.name)
def test_example_runs(script: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(str(script), run_name="__main__")
    assert capsys.readouterr().out


@pytest.mark.parametrize("block", README_BLOCKS, ids=lambda b: f"{len(b.splitlines())}-lines")
def test_readme_python_blocks_run(block: str) -> None:
    exec(compile(block, "README.md", "exec"), {})  # trusted input: our own README
