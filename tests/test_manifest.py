from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def registered_commands() -> set[str]:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "command"
            ):
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                commands.add(str(decorator.args[0].value))
            for keyword in decorator.keywords:
                if keyword.arg == "alias" and isinstance(keyword.value, ast.Set):
                    commands.update(
                        str(item.value)
                        for item in keyword.value.elts
                        if isinstance(item, ast.Constant)
                    )
    return commands


def test_metadata_and_readme_versions_match() -> None:
    metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert metadata["version"] == "v2.1.0"
    assert "version-v2.1.0-blue" in readme
    assert "## v2.1.0" in changelog


def test_all_registered_commands_are_documented() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `/([^`]+)` \|", readme, re.MULTILINE))

    assert registered_commands() <= documented


def test_runtime_uses_only_astrbot_t2i_render_path() -> None:
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    renderer = (ROOT / "src" / "card_renderer.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "self.html_render" in main
    assert "return_url=False" in renderer
    assert "playwright" not in requirements.lower()
    assert "pillow" not in requirements.lower()
    assert not (ROOT / "src" / "render").exists()


def test_config_schema_has_no_legacy_render_backends() -> None:
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

    assert "card_quality" in schema
    assert "render_mode" not in schema
    assert "render_server_url" not in schema


def test_packaging_script_and_ignore_rule_exist() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    package_script = ROOT / "scripts" / "package_plugin.ps1"

    assert "dist/" in gitignore
    assert package_script.exists()
    assert "--exclude-standard" in package_script.read_text(encoding="utf-8")
