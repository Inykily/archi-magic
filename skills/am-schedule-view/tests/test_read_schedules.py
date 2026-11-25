"""read_schedules.py: loader stub, version check and ASCII JSON (issue #297).

The script itself needs Revit. These tests cover the parts that do not: the file stays ASCII, the
SKILL.md loader runs a script with `inputs` and returns its `result`, and to_ascii_json is valid JSON.
"""
import ast
import json
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "read_schedules.py"
SKILL_MD = SKILL / "SKILL.md"


def loader_text():
    text = SKILL_MD.read_text(encoding="utf-8")
    block = re.search(r"```python\r?\n(.*?)```", text, re.S).group(1)
    assert "read_schedules.py" in block
    return "\n".join(line[3:] if line.startswith("   ") else line for line in block.splitlines())


def test_script_is_ascii_and_has_no_coding_cookie():
    raw = SCRIPT.read_bytes()
    raw.decode("ascii")
    assert b"coding" not in raw.splitlines()[0]


def test_script_returns_its_version():
    src = SCRIPT.read_text(encoding="ascii")
    assert re.search(r'^SCRIPT_VERSION = "[0-9-]+"$', src, re.M)
    assert '"scriptVersion": SCRIPT_VERSION' in src


def test_skill_loader_runs_the_file_with_inputs_and_result(tmp_path):
    fake = tmp_path / "read_schedules.py"
    fake.write_text('result = {"mode": inputs["mode"], "doc": doc}\n', encoding="ascii")
    stub = loader_text().replace(r"<skill dir>\scripts\read_schedules.py", str(fake))
    assert str(fake) in stub
    namespace = {"inputs": {"mode": "read"}, "doc": "model"}
    exec(compile(stub, "<loader>", "exec"), namespace)
    assert namespace["result"] == {"mode": "read", "doc": "model"}


def load_to_ascii_json():
    tree = ast.parse(SCRIPT.read_text(encoding="ascii"))
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "to_ascii_json")
    namespace = {"unicode": str, "basestring": str, "long": int}
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(SCRIPT), "exec"), namespace)
    return namespace["to_ascii_json"]


def test_to_ascii_json_round_trips_non_ascii_text():
    to_ascii_json = load_to_ascii_json()
    value = {"name": "Café \"A\" \\ \t", "rows": [[1, 2.5, None, True, False]],
             "emoji": "door \U0001F6AA", "cjk": "门"}
    text = to_ascii_json(value)
    text.encode("ascii")
    assert json.loads(text) == value
