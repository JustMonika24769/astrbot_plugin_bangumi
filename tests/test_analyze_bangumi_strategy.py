from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "analyze_bangumi_strategy.py"
JsonDict = dict[str, object]


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "analyze_bangumi_strategy_test_module", SCRIPT_PATH
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeBangumiClient:
    def __init__(
        self,
        me: JsonDict,
        collections: list[JsonDict],
        *,
        subject_eps: int = 12,
    ) -> None:
        self.me = me
        self.collections = collections
        self.subject_eps = subject_eps
        self.collection_calls: list[tuple[str, int]] = []
        self.me_called = False
        self.subject_calls: list[int] = []
        self.episode_calls: list[int] = []

    def get_me(self) -> JsonDict:
        self.me_called = True
        return self.me

    def iter_user_collections(
        self,
        username: str,
        collection_type: int,
        *,
        subject_type: int,
        page_limit: int = 50,
    ) -> list[JsonDict]:
        assert subject_type == 2
        assert page_limit <= 50
        self.collection_calls.append((username, collection_type))
        return [
            item for item in self.collections if item.get("type") == collection_type
        ]

    def get_subject(self, subject_id: int) -> JsonDict:
        self.subject_calls.append(subject_id)
        return {
            "id": subject_id,
            "type": 2,
            "name": f"Subject {subject_id}",
            "name_cn": f"补全条目 {subject_id}",
            "eps": self.subject_eps,
            "tags": [{"name": "补全"}],
        }

    def iter_episodes(
        self, subject_id: int, *, page_limit: int = 100
    ) -> list[JsonDict]:
        self.episode_calls.append(subject_id)
        return [
            {"id": subject_id * 100 + 1, "type": 0, "ep": 1},
            {"id": subject_id * 100 + 2, "type": 0, "ep": 2},
        ]


def collection_item(
    subject_id: int,
    title: str,
    collection_type: int,
    *,
    ep_status: int = 0,
    total_episodes: int = 12,
    rate: int = 0,
    tags: list[str] | None = None,
) -> JsonDict:
    return {
        "type": collection_type,
        "rate": rate,
        "ep_status": ep_status,
        "subject": {
            "id": subject_id,
            "type": 2,
            "name": title,
            "name_cn": title,
            "eps": total_episodes,
            "tags": [{"name": tag} for tag in tags or []],
        },
    }


def test_cli_help_uses_pipeline_default_output_dir() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert ".pipeline-workspace" in result.stdout
    assert "--db-path" in result.stdout
    assert "--require-db" in result.stdout


def test_missing_credentials_fails_without_reading_real_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("access_token", raising=False)
    monkeypatch.delenv("BANGUMI_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("BANGUMI_USERNAME", raising=False)
    script = load_script()
    exit_code = script.main(
        [
            "--env-path",
            str(tmp_path / "missing.env"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "access_token" in captured.err
    assert "Bangumi access token" in captured.err


def test_config_precedence_and_proxy_requires_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = load_script()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "access_token=from_file",
                "username=file_user",
                "user_agent=FileAgent/1.0",
                "proxy_http=socks5://127.0.0.1:1080",
                "port=1080",
                "max_retries=2",
                "render_mode=pillow",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BANGUMI_ACCESS_TOKEN", "from_env")
    monkeypatch.setenv("BANGUMI_USERNAME", "env_user")
    monkeypatch.setenv("BANGUMI_USER_AGENT", "EnvAgent/1.0")
    monkeypatch.setenv("BANGUMI_PROXY_HTTP", "env-proxy")
    monkeypatch.setenv("BANGUMI_PROXY_PORT", "9090")
    monkeypatch.setenv("BANGUMI_MAX_RETRIES", "9")
    monkeypatch.setenv("BANGUMI_RENDER_MODE", "html")

    config = script.load_config(["--env-path", str(env_path)])

    assert config.access_token == "from_file"
    assert config.username == "file_user"
    assert config.user_agent == "FileAgent/1.0"
    assert config.proxy_http == "socks5://127.0.0.1:1080"
    assert config.port == "1080"
    assert config.max_retries == 2
    assert config.render_mode == "pillow"

    override_config = script.load_config(
        [
            "--env-path",
            str(env_path),
            "--access-token",
            "from_cli",
            "--username",
            "cli_user",
            "--user-agent",
            "CliAgent/1.0",
            "--proxy-http",
            "cli-proxy",
            "--port",
            "7070",
            "--max-retries",
            "4",
            "--render-mode",
            "html",
        ]
    )

    assert override_config.access_token == "from_cli"
    assert override_config.username == "cli_user"
    assert override_config.user_agent == "CliAgent/1.0"
    assert override_config.proxy_http == "cli-proxy"
    assert override_config.port == "7070"
    assert override_config.max_retries == 4
    assert override_config.render_mode == "html"
    assert script.build_proxy_url("socks5://127.0.0.1:1080", "") is None
    assert (
        script.build_proxy_url("socks5://127.0.0.1:1080", "7890")
        == "socks5://127.0.0.1:1080"
    )


def test_username_can_be_resolved_from_me_without_leaking_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_script()
    secret_token = "bgm_super_secret_token"
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"access_token={secret_token}\nuser_agent=OfflineTest/1.0\nmax_retries=1\n",
        encoding="utf-8",
    )
    fake_client = FakeBangumiClient(
        {"username": "resolved_user"},
        [
            collection_item(
                101,
                "正在追的番",
                3,
                ep_status=4,
                total_episodes=12,
                rate=8,
                tags=["科幻", "原创"],
            )
        ],
    )
    monkeypatch.setattr(
        script,
        "BangumiV0Client",
        lambda config: fake_client,
    )

    exit_code = script.main(
        [
            "--env-path",
            str(env_path),
            "--output-dir",
            str(tmp_path / "reports"),
        ]
    )

    captured = capsys.readouterr()
    output_json = tmp_path / "reports" / "bangumi_strategy_analysis.json"
    output_md = tmp_path / "reports" / "bangumi_strategy_report.md"
    report_text = output_json.read_text(encoding="utf-8")
    markdown_text = output_md.read_text(encoding="utf-8")

    assert exit_code == 0
    assert fake_client.me_called is True
    assert ("resolved_user", 3) in fake_client.collection_calls
    assert secret_token not in captured.out
    assert secret_token not in captured.err
    assert secret_token not in report_text
    assert secret_token not in markdown_text
    assert json.loads(report_text)["username"] == "resolved_user"


def test_client_paginates_collections_and_redacts_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = load_script()
    config = script.AnalysisConfig(
        access_token="bgm_raw_token",
        user_agent="OfflineTest/1.0",
        username="demo",
        max_retries=1,
        rate_limit_seconds=0,
    )
    client = script.BangumiV0Client(config)
    requests: list[JsonDict] = []

    def fake_request(path: str, params: dict[str, object] | None = None) -> JsonDict:
        assert path == "/v0/users/demo/collections"
        assert params is not None
        requests.append(dict(params))
        offset = int(params["offset"])
        if offset == 0:
            return {
                "total": 3,
                "data": [
                    collection_item(1, "A", 3),
                    collection_item(2, "B", 3),
                ],
            }
        if offset == 2:
            return {"total": 3, "data": [collection_item(3, "C", 3)]}
        raise AssertionError(f"unexpected offset {offset}")

    monkeypatch.setattr(client, "_request_json", fake_request)

    items = client.iter_user_collections(
        "demo",
        3,
        subject_type=2,
        page_limit=2,
    )

    assert [item["subject"]["id"] for item in items] == [1, 2, 3]
    assert requests == [
        {"subject_type": 2, "type": 3, "limit": 2, "offset": 0},
        {"subject_type": 2, "type": 3, "limit": 2, "offset": 2},
    ]
    with pytest.raises(script.AnalysisError) as exc_info:
        raise script.AnalysisError("failed for bgm_raw_token")
    assert "bgm_raw_token" not in script.safe_text(str(exc_info.value), config)


def test_sqlite_optional_missing_and_required_failure(tmp_path: Path) -> None:
    script = load_script()
    missing = tmp_path / "data.db"

    optional = script.read_local_subscriptions(missing, require_db=False)
    assert optional["status"] == "missing"
    assert optional["subjects"] == []

    with pytest.raises(script.AnalysisError) as exc_info:
        script.read_local_subscriptions(missing, require_db=True)

    assert "SQLite" in str(exc_info.value)
    assert str(missing) in str(exc_info.value)


def test_sqlite_read_only_subscription_summary(tmp_path: Path) -> None:
    script = load_script()
    db_path = tmp_path / "data.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE bangumi_subjects (
            subject_id TEXT PRIMARY KEY,
            name TEXT,
            air_date TEXT,
            total_episodes INTEGER,
            current_episode INTEGER,
            updated_at TEXT
        );
        CREATE TABLE subscriptions (
            group_id TEXT,
            subject_id TEXT,
            created_at TEXT,
            PRIMARY KEY (group_id, subject_id)
        );
        INSERT INTO bangumi_subjects VALUES
            ('101', '仍在订阅的弃坑番', '2025-01-01', 12, 12, '2025-04-01'),
            ('102', '未订阅的在看番', '2025-02-01', 12, 4, '2025-04-02');
        INSERT INTO subscriptions VALUES
            ('1001', '101', '2025-01-02'),
            ('1002', '101', '2025-01-03');
        """
    )
    connection.commit()
    connection.close()

    result = script.read_local_subscriptions(db_path, require_db=True)

    assert result["status"] == "available"
    assert result["summary"]["local_subject_count"] == 2
    assert result["summary"]["subscription_count"] == 2
    assert result["subjects"][0]["group_count"] == 2


def test_metrics_conflicts_and_chinese_recommendations_use_real_evidence() -> None:
    script = load_script()
    collections = [
        collection_item(
            101,
            "仍在订阅的弃坑番",
            5,
            ep_status=2,
            total_episodes=12,
            rate=4,
            tags=["悬疑"],
        ),
        collection_item(
            102,
            "未订阅的在看番",
            3,
            ep_status=10,
            total_episodes=12,
            rate=9,
            tags=["科幻", "原创"],
        ),
        collection_item(103, "想看长篇", 1, total_episodes=48, tags=["科幻"]),
    ]
    local_data = {
        "status": "available",
        "summary": {"local_subject_count": 1, "subscription_count": 2},
        "subjects": [
            {
                "subject_id": 101,
                "title": "仍在订阅的弃坑番",
                "current_episode": 12,
                "total_episodes": 12,
                "group_count": 2,
                "group_ids": ["1001", "1002"],
                "updated_at": "2025-04-01",
            }
        ],
    }

    analysis = script.build_analysis(
        username="demo_user",
        collections=collections,
        local_data=local_data,
        generated_at="2026-05-17T12:00:00+08:00",
    )
    markdown = script.render_markdown_report(analysis)

    assert analysis["collection_total"] == 3
    assert analysis["collection_type_counts"]["在看"] == 1
    assert analysis["rating_distribution"]["9"] == 1
    assert analysis["tag_distribution"]["科幻"] == 2
    assert "已抛弃但仍订阅" in {
        conflict["conflict_type"] for conflict in analysis["subscription_conflicts"]
    }
    assert "在看但未订阅" in {
        conflict["conflict_type"] for conflict in analysis["subscription_conflicts"]
    }
    assert "追番节奏" in markdown
    assert "插件订阅通知策略" in markdown
    assert "仍在订阅的弃坑番" in markdown
    assert "未订阅的在看番" in markdown


def test_missing_local_subscription_data_does_not_infer_conflicts() -> None:
    script = load_script()

    analysis = script.build_analysis(
        username="demo_user",
        collections=[
            collection_item(
                102,
                "未验证订阅状态的在看番",
                3,
                ep_status=10,
                total_episodes=12,
                rate=9,
                tags=["科幻"],
            )
        ],
        local_data={
            "status": "missing",
            "summary": {"local_subject_count": 0, "subscription_count": 0},
            "subjects": [],
        },
        generated_at="2026-05-17T12:00:00+08:00",
    )
    markdown = script.render_markdown_report(analysis)

    assert analysis["subscription_conflicts"] == []
    assert (
        analysis["local_subscription_coverage"]["unsubscribed_watching_count"] is None
    )
    assert "在看但未订阅" not in markdown
    assert "本地 SQLite 订阅数据缺失" in markdown


def test_enriches_missing_subject_episode_counts() -> None:
    script = load_script()
    client = FakeBangumiClient(
        {"username": "demo"},
        [{"type": 3, "subject_id": 301, "ep_status": 1}],
    )

    enriched = script.enrich_user_collections(
        client,
        [{"type": 3, "subject_id": 301, "ep_status": 1}],
    )
    analysis = script.build_analysis(
        username="demo",
        collections=enriched,
        local_data={
            "status": "missing",
            "summary": {"local_subject_count": 0, "subscription_count": 0},
            "subjects": [],
        },
        generated_at="2026-05-17T12:00:00+08:00",
    )

    assert client.subject_calls == [301]
    assert analysis["evidence"][0]["title"] == "补全条目 301"
    assert analysis["evidence"][0]["total_episodes"] == 12


def test_enriches_episode_count_when_subject_has_no_eps() -> None:
    script = load_script()
    client = FakeBangumiClient(
        {"username": "demo"},
        [{"type": 3, "subject_id": 302, "ep_status": 1}],
        subject_eps=0,
    )

    enriched = script.enrich_user_collections(
        client,
        [{"type": 3, "subject_id": 302, "ep_status": 1}],
    )
    analysis = script.build_analysis(
        username="demo",
        collections=enriched,
        local_data={
            "status": "missing",
            "summary": {"local_subject_count": 0, "subscription_count": 0},
            "subjects": [],
        },
        generated_at="2026-05-17T12:00:00+08:00",
    )

    assert client.subject_calls == [302]
    assert client.episode_calls == [302]
    assert analysis["evidence"][0]["total_episodes"] == 2


def test_schema_mismatch_is_actionable(tmp_path: Path) -> None:
    script = load_script()
    db_path = tmp_path / "broken.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE bangumi_subjects (subject_id TEXT PRIMARY KEY)")
    connection.commit()
    connection.close()

    with pytest.raises(script.AnalysisError) as exc_info:
        script.read_local_subscriptions(db_path, require_db=True)

    assert "subscriptions" in str(exc_info.value)
    assert "表结构" in str(exc_info.value)

    optional = script.read_local_subscriptions(db_path, require_db=False)
    assert optional["status"] == "schema_mismatch"
    assert optional["subjects"] == []
