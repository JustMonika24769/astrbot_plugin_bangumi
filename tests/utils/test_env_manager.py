from pathlib import Path

from astrbot_plugin_bangumi.src.utils.env_manager import EnvManager


def test_generate_env_from_schema_writes_defaults(tmp_path: Path) -> None:
    schema = tmp_path / "_conf_schema.json"
    env = tmp_path / ".env"
    schema.write_text(
        '{"access_token":{"default":""},"max_retries":{"default":3},'
        '"render_mode":{"default":"html"}}',
        encoding="utf-8",
    )

    EnvManager.generate_env_from_schema(schema, env, render_mode_default="pillow")

    assert env.read_text(encoding="utf-8").splitlines() == [
        "# Generated from _conf_schema.json for local testing.",
        "# Fill access_token before running integration tests that hit Bangumi APIs.",
        "",
        "access_token=",
        "max_retries=3",
        "render_mode=pillow",
    ]


def test_generate_env_from_schema_preserves_existing_values(tmp_path: Path) -> None:
    schema = tmp_path / "_conf_schema.json"
    env = tmp_path / ".env"
    schema.write_text(
        '{"access_token":{"default":""},"render_mode":{"default":"html"}}',
        encoding="utf-8",
    )
    env.write_text("access_token=kept\nrender_mode=html\n", encoding="utf-8")

    EnvManager.generate_env_from_schema(schema, env, render_mode_default="pillow")

    content = env.read_text(encoding="utf-8")
    assert "access_token=kept" in content
    assert "render_mode=html" in content
