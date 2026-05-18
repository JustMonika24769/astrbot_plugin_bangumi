import ast
import json
import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASTROBOT_IMPORT_RULE = "AstrBot package-loading import rule"
TOP_LEVEL_SRC_PREFIX = "src" + "."
APP_IMPORT_BOUNDARY_BANNED_ROOTS = {
    "astrbot": "depends on AstrBot framework",
    "sqlalchemy": "depends on SQLAlchemy",
    "src.db": "depends on concrete database implementation",
    "src.render": "depends on concrete render implementation",
    "astrbot_plugin_bangumi.src.db": "depends on concrete database implementation",
    "astrbot_plugin_bangumi.src.render": "depends on concrete render implementation",
}
DOMAIN_IMPORT_BOUNDARY_BANNED_ROOTS = {
    "aiohttp": "depends on HTTP client",
    "astrbot": "depends on AstrBot framework",
    "jinja2": "depends on template engine",
    "sqlalchemy": "depends on SQLAlchemy",
}


def _python_files_under(*relative_roots: str) -> list[Path]:
    return sorted(
        file_path
        for relative_root in relative_roots
        for file_path in (PROJECT_ROOT / relative_root).rglob("*.py")
    )


def _format_location(file_path: Path, line_number: int, detail: str) -> str:
    return f"{file_path.relative_to(PROJECT_ROOT)}:{line_number}: {detail}"


def _is_top_level_src_module(module_name: str | None) -> bool:
    return module_name == "src" or bool(
        module_name and module_name.startswith(TOP_LEVEL_SRC_PREFIX)
    )


def _module_matches_root(module_name: str, root: str) -> bool:
    return module_name == root or module_name.startswith(root + ".")


def _resolve_import_from_module(file_path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module

    relative_module_path = file_path.relative_to(PROJECT_ROOT).with_suffix("")
    package_parts = list(relative_module_path.parts[:-1])
    base_length = len(package_parts) - node.level + 1
    if base_length < 0:
        return node.module

    resolved_parts = package_parts[:base_length]
    if node.module:
        resolved_parts.extend(node.module.split("."))
    return ".".join(resolved_parts)


def _find_direct_internal_imports(file_path: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(file_path.read_text(), filename=str(file_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_top_level_src_module(alias.name):
                    violations.append(
                        _format_location(
                            file_path,
                            node.lineno,
                            f"uses top-level {alias.name} import",
                        )
                    )
        elif isinstance(node, ast.ImportFrom) and _is_top_level_src_module(node.module):
            violations.append(
                _format_location(
                    file_path,
                    node.lineno,
                    f"uses top-level {node.module} import",
                )
            )
    return violations


def _find_banned_imports(
    file_path: Path, banned_roots: dict[str, str], boundary_name: str
) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(file_path.read_text(), filename=str(file_path))
    for node in ast.walk(tree):
        imported_modules: list[str] = []
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base_module = _resolve_import_from_module(file_path, node)
            if base_module:
                imported_modules.append(base_module)
                imported_modules.extend(
                    f"{base_module}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )

        for module_name in imported_modules:
            for banned_root, reason in banned_roots.items():
                if _module_matches_root(module_name, banned_root):
                    violations.append(
                        _format_location(
                            file_path,
                            node.lineno,
                            f"{boundary_name}: imports {module_name} ({reason})",
                        )
                    )
                    break
    return violations


def _is_monkeypatch_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "monkeypatch"
    )


def _find_top_level_monkeypatch_targets(file_path: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(file_path.read_text(), filename=str(file_path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_monkeypatch_call(node):
            continue

        string_nodes = [
            value
            for value in [*node.args, *(keyword.value for keyword in node.keywords)]
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ]
        for value in string_nodes:
            if value.value.startswith(TOP_LEVEL_SRC_PREFIX):
                violations.append(
                    _format_location(
                        file_path,
                        value.lineno,
                        "uses top-level src monkeypatch target",
                    )
                )
    return violations


def test_metadata_declares_recommended_astrbot_fields() -> None:
    metadata = yaml.safe_load((PROJECT_ROOT / "metadata.yaml").read_text())

    assert metadata["name"].startswith("astrbot_plugin_")
    assert metadata["display_name"]
    assert metadata["license"] == "Apache-2.0"
    assert metadata["astrbot_version"] == ">=4.16,<5"


def test_readme_documents_registered_commands_and_dependency_behavior() -> None:
    main_py = (PROJECT_ROOT / "main.py").read_text()
    readme = (PROJECT_ROOT / "README.md").read_text()

    commands = set(re.findall(r'@filter\.command\("([^"]+)"\)', main_py))
    readme_commands = set(re.findall(r"^\| `/([^`]+)` \|", readme, re.MULTILINE))

    assert commands
    assert readme_commands == commands
    assert "插件首次运行时会自动检查并安装" not in readme


def test_readme_version_badge_matches_metadata_version() -> None:
    metadata = yaml.safe_load((PROJECT_ROOT / "metadata.yaml").read_text())
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert (
        f"https://img.shields.io/badge/version-{metadata['version']}-blue.svg" in readme
    )


def test_plugin_uses_metadata_instead_of_deprecated_register_decorator() -> None:
    main_py = (PROJECT_ROOT / "main.py").read_text()

    assert "@register(" not in main_py
    assert (
        "from astrbot.api.star import Context, Star, StarTools, register" not in main_py
    )


def test_main_imports_match_astrbot_package_loading() -> None:
    main_py = (PROJECT_ROOT / "main.py").read_text()

    assert "from .src." in main_py, (
        f"{ASTROBOT_IMPORT_RULE}: main.py must import plugin internals via .src"
    )
    assert "from src." not in main_py, (
        f"{ASTROBOT_IMPORT_RULE}: main.py must not fall back to top-level src imports"
    )
    assert "import src." not in main_py, (
        f"{ASTROBOT_IMPORT_RULE}: main.py must not fall back to top-level src imports"
    )
    assert "except ImportError" not in main_py, (
        f"{ASTROBOT_IMPORT_RULE}: main.py must not use top-level src fallback imports"
    )


def test_tests_and_scripts_use_package_imports_for_plugin_internals() -> None:
    violations: list[str] = []
    for file_path in _python_files_under("tests", "scripts"):
        violations.extend(_find_direct_internal_imports(file_path))
        violations.extend(_find_top_level_monkeypatch_targets(file_path))

    assert not violations, (
        f"{ASTROBOT_IMPORT_RULE}: tests and scripts must use "
        "astrbot_plugin_bangumi.src package paths instead of top-level src imports "
        "or monkeypatch targets:\n" + "\n".join(violations)
    )


def test_app_import_boundary_excludes_framework_db_and_render_details() -> None:
    violations: list[str] = []
    for file_path in _python_files_under("src/app"):
        violations.extend(
            _find_banned_imports(
                file_path,
                APP_IMPORT_BOUNDARY_BANNED_ROOTS,
                "App import boundary",
            )
        )

    assert not violations, (
        "App layer must depend on app/domain contracts instead of AstrBot, "
        "SQLAlchemy, database implementations, or render implementations:\n"
        + "\n".join(violations)
    )


def test_domain_import_boundary_excludes_external_details() -> None:
    violations: list[str] = []
    for file_path in _python_files_under("src/domain"):
        violations.extend(
            _find_banned_imports(
                file_path,
                DOMAIN_IMPORT_BOUNDARY_BANNED_ROOTS,
                "Domain import boundary",
            )
        )

    assert not violations, (
        "Domain layer must stay independent from framework, HTTP, database, "
        "and template-engine dependencies:\n" + "\n".join(violations)
    )


def test_config_schema_exposes_render_mode_options() -> None:
    schema = json.loads((PROJECT_ROOT / "_conf_schema.json").read_text())

    assert schema["render_mode"]["options"] == ["html", "pillow"]
    assert schema["episode_card_template"]["default"] == "cinematic_poster"
    assert schema["episode_card_template"]["options"] == [
        "pastel_lightbox",
        "editorial_digest",
        "cinematic_poster",
    ]


def test_gitignore_excludes_generated_artifacts() -> None:
    gitignore_lines = {
        line.strip()
        for line in (PROJECT_ROOT / ".gitignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert "rendered_images/" in gitignore_lines
    assert ".codex-pet-runs/" in gitignore_lines
    assert ".pipeline-last-run-summary.json" in gitignore_lines
