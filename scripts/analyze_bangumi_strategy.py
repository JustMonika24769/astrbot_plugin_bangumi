from __future__ import annotations

# ruff: noqa: E402
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_PARENT = REPO_ROOT.parent
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astrbot_plugin_bangumi.src.domain.types import SubjectType

JsonDict = dict[str, object]

API_BASE_URL = "https://api.bgm.tv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".pipeline-workspace"
DEFAULT_JSON_NAME = "bangumi_strategy_analysis.json"
DEFAULT_MARKDOWN_NAME = "bangumi_strategy_report.md"
DEFAULT_USER_AGENT = (
    "AstrBot-Bangumi-Plugin/strategy-analysis "
    "(https://github.com/united-pooh/astrbot_plugin_bangumi)"
)
COLLECTION_TYPES = {
    1: "想看",
    2: "看过",
    3: "在看",
    4: "搁置",
    5: "抛弃",
}
TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}


class AnalysisError(RuntimeError):
    """User-actionable analysis failure."""


@dataclass(frozen=True)
class AnalysisConfig:
    access_token: str = ""
    user_agent: str = DEFAULT_USER_AGENT
    username: str = ""
    proxy_http: str = ""
    port: str = ""
    max_retries: int = 3
    render_mode: str = "pillow"
    env_path: Path = REPO_ROOT / ".env"
    db_path: Path | None = None
    require_db: bool = False
    output_dir: Path = DEFAULT_OUTPUT_DIR
    output_json: Path | None = None
    output_md: Path | None = None
    page_limit: int = 50
    rate_limit_seconds: float = 0.35
    api_base_url: str = API_BASE_URL

    def redaction_values(self) -> list[str]:
        values = [self.access_token]
        if self.access_token:
            values.append(f"Bearer {self.access_token}")
        return [value for value in values if value]


def safe_text(text: object, config: AnalysisConfig | None = None) -> str:
    result = str(text)
    tokens = config.redaction_values() if config is not None else []
    for token in tokens:
        result = result.replace(token, "[REDACTED]")
    return result


def parse_key_value_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value.startswith(("'", '"')):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def first_config_value(
    values: dict[str, str],
    environment: os._Environ[str],
    keys: tuple[str, ...],
    default: str = "",
) -> str:
    for key in keys:
        if key in values and values[key] != "":
            return values[key]
    for key in keys:
        if key in environment and environment[key] != "":
            return environment[key]
    return default


def parse_int(value: object, default: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return parsed


def parse_float(value: object, default: float) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return default
    return parsed


def normalize_token(value: str) -> str:
    token = value.strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def build_proxy_url(proxy_http: str, port: str) -> str | None:
    host = proxy_http.strip()
    proxy_port = port.strip()
    if not host or not proxy_port:
        return None

    url = host if "://" in host else f"http://{host}"
    parsed = urllib.parse.urlsplit(url)
    netloc = parsed.netloc or parsed.path
    if ":" not in netloc and proxy_port:
        netloc = f"{netloc}:{proxy_port}"
    if ":" not in netloc:
        return None
    scheme = parsed.scheme or "http"
    return urllib.parse.urlunsplit((scheme, netloc, "", "", ""))


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读采集 Bangumi 收藏和本地订阅数据，生成番剧管理策略分析。",
    )
    parser.add_argument(
        "--env-path",
        type=Path,
        default=REPO_ROOT / ".env",
        help="配置文件路径，默认读取项目 .env。",
    )
    parser.add_argument("--username", help="Bangumi 用户名；缺省时通过 /v0/me 推断。")
    parser.add_argument(
        "--access-token", help="Bangumi access_token；优先建议放入 .env。"
    )
    parser.add_argument("--user-agent", help="Bangumi API User-Agent。")
    parser.add_argument("--proxy-http", help="代理主机，例如 127.0.0.1。")
    parser.add_argument("--port", help="代理端口，例如 7890。")
    parser.add_argument("--max-retries", type=int, help="API 失败后的最大重试次数。")
    parser.add_argument(
        "--render-mode", help="记录当前插件渲染模式，例如 pillow、playwright 或 rpc。"
    )
    parser.add_argument(
        "--db-path", type=Path, help="本地 AstrBot Bangumi SQLite 数据库路径。"
    )
    parser.add_argument(
        "--require-db",
        action="store_true",
        help="要求必须读取本地 SQLite 数据库；缺失或表结构不匹配时失败。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="默认报告目录，缺省写入 .pipeline-workspace。",
    )
    parser.add_argument("--output-json", type=Path, help="机器可读 JSON 输出路径。")
    parser.add_argument("--output-md", type=Path, help="中文 Markdown 报告输出路径。")
    parser.add_argument(
        "--page-limit",
        type=int,
        help="Bangumi collections 分页大小，最大 50。",
    )
    parser.add_argument(
        "--rate-limit-seconds",
        type=float,
        help="串行 GET 请求之间的最小间隔秒数。",
    )
    parser.add_argument(
        "--api-base-url",
        default=API_BASE_URL,
        help=argparse.SUPPRESS,
    )
    return parser


def load_config(argv: list[str] | None = None) -> AnalysisConfig:
    parser = create_parser()
    args = parser.parse_args(argv)
    env_values = parse_key_value_file(args.env_path)
    environment = os.environ

    access_token = normalize_token(
        first_config_value(
            env_values,
            environment,
            ("access_token", "BANGUMI_ACCESS_TOKEN"),
        )
    )
    username = first_config_value(
        env_values,
        environment,
        ("username", "BANGUMI_USERNAME", "bangumi_username"),
    )
    user_agent = first_config_value(
        env_values,
        environment,
        ("user_agent", "BANGUMI_USER_AGENT"),
        DEFAULT_USER_AGENT,
    )
    proxy_http = first_config_value(
        env_values,
        environment,
        ("proxy_http", "BANGUMI_PROXY_HTTP"),
    )
    port = first_config_value(
        env_values,
        environment,
        ("port", "BANGUMI_PROXY_PORT"),
    )
    render_mode = first_config_value(
        env_values,
        environment,
        ("render_mode", "BANGUMI_RENDER_MODE"),
        "pillow",
    )
    max_retries = parse_int(
        first_config_value(
            env_values,
            environment,
            ("max_retries", "BANGUMI_MAX_RETRIES"),
            "3",
        ),
        3,
    )
    db_path_value = first_config_value(
        env_values,
        environment,
        ("db_path", "BANGUMI_DB_PATH"),
    )

    if args.access_token is not None:
        access_token = normalize_token(args.access_token)
    if args.username is not None:
        username = args.username
    if args.user_agent is not None:
        user_agent = args.user_agent
    if args.proxy_http is not None:
        proxy_http = args.proxy_http
    if args.port is not None:
        port = args.port
    if args.max_retries is not None:
        max_retries = args.max_retries
    if args.render_mode is not None:
        render_mode = args.render_mode
    if args.db_path is not None:
        db_path_value = str(args.db_path)

    page_limit = args.page_limit if args.page_limit is not None else 50
    rate_limit_seconds = (
        args.rate_limit_seconds if args.rate_limit_seconds is not None else 0.35
    )
    max_retries = max(0, max_retries)
    page_limit = min(50, max(1, page_limit))
    rate_limit_seconds = max(0.0, rate_limit_seconds)

    return AnalysisConfig(
        access_token=access_token,
        user_agent=user_agent or DEFAULT_USER_AGENT,
        username=username.strip(),
        proxy_http=proxy_http,
        port=port,
        max_retries=max_retries,
        render_mode=render_mode,
        env_path=args.env_path,
        db_path=Path(db_path_value).expanduser() if db_path_value else None,
        require_db=args.require_db,
        output_dir=args.output_dir,
        output_json=args.output_json,
        output_md=args.output_md,
        page_limit=page_limit,
        rate_limit_seconds=rate_limit_seconds,
        api_base_url=args.api_base_url.rstrip("/"),
    )


class BangumiV0Client:
    def __init__(self, config: AnalysisConfig) -> None:
        self.config = config
        proxy_url = build_proxy_url(config.proxy_http, config.port)
        handlers: list[urllib.request.BaseHandler] = []
        if proxy_url is not None:
            handlers.append(
                urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            )
        self.opener = urllib.request.build_opener(*handlers)
        self.last_request_at = 0.0

    def _sleep_for_rate_limit(self) -> None:
        if self.config.rate_limit_seconds <= 0:
            return
        elapsed = time.monotonic() - self.last_request_at
        wait_for = self.config.rate_limit_seconds - elapsed
        if wait_for > 0:
            time.sleep(wait_for)

    def _request_json(
        self,
        path: str,
        params: dict[str, object] | None = None,
    ) -> JsonDict:
        url = f"{self.config.api_base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        headers = {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
            "Authorization": f"Bearer {self.config.access_token}",
        }
        request = urllib.request.Request(url, headers=headers, method="GET")
        attempts = self.config.max_retries + 1
        last_error = ""

        for attempt in range(1, attempts + 1):
            try:
                self._sleep_for_rate_limit()
                with self.opener.open(request, timeout=20) as response:
                    self.last_request_at = time.monotonic()
                    body = response.read().decode("utf-8")
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    return cast(JsonDict, parsed)
                if isinstance(parsed, list):
                    return {"data": parsed}
                raise AnalysisError(f"Bangumi API GET {path} 返回了不可识别的 JSON。")
            except urllib.error.HTTPError as exc:
                self.last_request_at = time.monotonic()
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                last_error = (
                    f"HTTP {exc.code} {exc.reason}: {safe_text(detail, self.config)}"
                )
                if exc.code not in TRANSIENT_HTTP_STATUS or attempt == attempts:
                    break
                retry_after = parse_float(exc.headers.get("Retry-After"), 0.0)
                time.sleep(max(retry_after, self.config.rate_limit_seconds))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                self.last_request_at = time.monotonic()
                last_error = safe_text(exc, self.config)
                if attempt == attempts:
                    break
                time.sleep(self.config.rate_limit_seconds)

        raise AnalysisError(
            safe_text(
                f"Bangumi API GET {path} 在 {attempts} 次尝试后失败：{last_error}",
                self.config,
            )
        )

    def get_me(self) -> JsonDict:
        return self._request_json("/v0/me")

    def iter_user_collections(
        self,
        username: str,
        collection_type: int,
        *,
        subject_type: int = int(SubjectType.ANIME),
        page_limit: int = 50,
    ) -> list[JsonDict]:
        limit = min(50, max(1, page_limit))
        offset = 0
        items: list[JsonDict] = []
        while True:
            payload = self._request_json(
                f"/v0/users/{urllib.parse.quote(username)}/collections",
                {
                    "subject_type": subject_type,
                    "type": collection_type,
                    "limit": limit,
                    "offset": offset,
                },
            )
            page_data = payload.get("data", [])
            if not isinstance(page_data, list):
                raise AnalysisError("Bangumi collections 响应缺少 data 列表。")
            dict_items = [item for item in page_data if isinstance(item, dict)]
            items.extend(cast(list[JsonDict], dict_items))
            total = parse_int(payload.get("total"), -1)
            if not dict_items:
                break
            offset += len(dict_items)
            if total >= 0 and offset >= total:
                break
            if len(dict_items) < limit and total < 0:
                break
        return items

    def get_subject(self, subject_id: int) -> JsonDict:
        return self._request_json(f"/v0/subjects/{subject_id}")

    def iter_episodes(
        self, subject_id: int, *, page_limit: int = 100
    ) -> list[JsonDict]:
        limit = min(100, max(1, page_limit))
        offset = 0
        episodes: list[JsonDict] = []
        while True:
            payload = self._request_json(
                "/v0/episodes",
                {"subject_id": subject_id, "limit": limit, "offset": offset},
            )
            page_data = payload.get("data", [])
            if not isinstance(page_data, list):
                raise AnalysisError("Bangumi episodes 响应缺少 data 列表。")
            dict_items = [item for item in page_data if isinstance(item, dict)]
            episodes.extend(cast(list[JsonDict], dict_items))
            total = parse_int(payload.get("total"), -1)
            if not dict_items:
                break
            offset += len(dict_items)
            if total >= 0 and offset >= total:
                break
            if len(dict_items) < limit and total < 0:
                break
        return episodes


def resolve_username(config: AnalysisConfig, client: BangumiV0Client) -> str:
    if config.username:
        return config.username
    me = client.get_me()
    username = me.get("username") or me.get("id")
    if username is None or str(username).strip() == "":
        raise AnalysisError(
            "无法从 GET /v0/me 推断 Bangumi username；请使用 --username 或 "
            "BANGUMI_USERNAME 显式提供。"
        )
    return str(username).strip()


def discover_db_path(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser()

    candidates = [
        REPO_ROOT / "data.db",
        REPO_ROOT / "data" / "data.db",
        REPO_ROOT / "database.db",
        REPO_ROOT / "data" / "bangumi.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def sqlite_readonly_uri(path: Path) -> str:
    quoted = urllib.parse.quote(str(path.resolve()), safe="/:")
    return f"file:{quoted}?mode=ro"


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def missing_columns(
    connection: sqlite3.Connection,
    table: str,
    required_columns: set[str],
) -> set[str]:
    columns = table_columns(connection, table)
    return required_columns - columns


def normalize_subject_id(value: object) -> object:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return str(value)


def read_local_subscriptions(
    db_path: Path | None,
    *,
    require_db: bool,
) -> JsonDict:
    resolved_path = discover_db_path(db_path)
    if resolved_path is None or not resolved_path.exists():
        target = str(resolved_path or db_path or "data.db")
        if require_db:
            raise AnalysisError(
                f"必须读取 SQLite 数据库，但未找到 {target}；请通过 --db-path 指定 data.db。"
            )
        return {
            "status": "missing",
            "db_path": target,
            "summary": {
                "local_subject_count": 0,
                "subscription_count": 0,
                "subscribed_subject_count": 0,
                "group_count": 0,
            },
            "subjects": [],
        }

    try:
        connection = sqlite3.connect(sqlite_readonly_uri(resolved_path), uri=True)
    except sqlite3.Error as exc:
        if require_db:
            raise AnalysisError(
                f"无法以只读模式打开 SQLite 数据库 {resolved_path}：{exc}"
            ) from exc
        return {
            "status": "unreadable",
            "db_path": str(resolved_path),
            "error": str(exc),
            "summary": {
                "local_subject_count": 0,
                "subscription_count": 0,
                "subscribed_subject_count": 0,
                "group_count": 0,
            },
            "subjects": [],
        }

    try:
        schema_checks = {
            "bangumi_subjects": {
                "subject_id",
                "name",
                "air_date",
                "total_episodes",
                "current_episode",
                "updated_at",
            },
            "subscriptions": {"group_id", "subject_id", "created_at"},
        }
        schema_errors: list[str] = []
        for table, required_columns in schema_checks.items():
            missing = missing_columns(connection, table, required_columns)
            if missing:
                schema_errors.append(f"{table}.{', '.join(sorted(missing))}")
        if schema_errors:
            message = (
                f"SQLite 表结构缺少 {'; '.join(schema_errors)}，请检查插件数据库。"
            )
            if require_db:
                raise AnalysisError(message)
            return {
                "status": "schema_mismatch",
                "db_path": str(resolved_path),
                "error": message,
                "summary": {
                    "local_subject_count": 0,
                    "subscription_count": 0,
                    "subscribed_subject_count": 0,
                    "group_count": 0,
                },
                "subjects": [],
            }
        rows = connection.execute(
            """
            SELECT
                s.subject_id,
                s.name,
                s.air_date,
                s.total_episodes,
                s.current_episode,
                s.updated_at,
                COUNT(sub.group_id) AS group_count,
                GROUP_CONCAT(sub.group_id) AS group_ids
            FROM bangumi_subjects AS s
            LEFT JOIN subscriptions AS sub ON sub.subject_id = s.subject_id
            GROUP BY
                s.subject_id,
                s.name,
                s.air_date,
                s.total_episodes,
                s.current_episode,
                s.updated_at
            ORDER BY s.subject_id
            """
        ).fetchall()
    except sqlite3.Error as exc:
        raise AnalysisError(f"SQLite 只读查询失败：{exc}") from exc
    finally:
        connection.close()

    subjects: list[JsonDict] = []
    all_group_ids: set[str] = set()
    subscription_count = 0
    for row in rows:
        group_ids = [group_id for group_id in str(row[7] or "").split(",") if group_id]
        all_group_ids.update(group_ids)
        group_count = parse_int(row[6], 0)
        subscription_count += group_count
        subjects.append(
            {
                "subject_id": normalize_subject_id(row[0]),
                "title": row[1] or str(row[0]),
                "air_date": row[2],
                "total_episodes": parse_int(row[3], 0),
                "current_episode": parse_int(row[4], 0),
                "updated_at": str(row[5]) if row[5] is not None else "",
                "group_count": group_count,
                "group_ids": group_ids,
            }
        )

    return {
        "status": "available",
        "db_path": str(resolved_path),
        "summary": {
            "local_subject_count": len(subjects),
            "subscription_count": subscription_count,
            "subscribed_subject_count": sum(
                1
                for subject in subjects
                if parse_int(subject.get("group_count"), 0) > 0
            ),
            "group_count": len(all_group_ids),
        },
        "subjects": subjects,
    }


def list_from_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def dict_from_value(value: object) -> JsonDict:
    return cast(JsonDict, value) if isinstance(value, dict) else {}


def item_subject(item: JsonDict) -> JsonDict:
    return dict_from_value(item.get("subject"))


def extract_tags(item: JsonDict, subject: JsonDict) -> list[str]:
    tags: list[str] = []
    for source in (item.get("tags"), subject.get("tags")):
        for tag in list_from_value(source):
            if isinstance(tag, str) and tag:
                tags.append(tag)
            elif isinstance(tag, dict):
                name = tag.get("name")
                if isinstance(name, str) and name:
                    tags.append(name)
    return tags


def extract_title(subject: JsonDict, fallback_id: object) -> str:
    for key in ("name_cn", "name"):
        value = subject.get(key)
        if isinstance(value, str) and value:
            return value
    return str(fallback_id)


def extract_total_episodes(item: JsonDict, subject: JsonDict) -> int:
    for value in (
        item.get("total_episodes"),
        item.get("eps"),
        subject.get("eps"),
        subject.get("total_episodes"),
        subject.get("total_episodes_count"),
    ):
        parsed = parse_int(value, 0)
        if parsed > 0:
            return parsed
    return 0


def collection_to_evidence(item: JsonDict) -> JsonDict:
    subject = item_subject(item)
    subject_id = normalize_subject_id(
        item.get("subject_id") or subject.get("id") or subject.get("subject_id") or ""
    )
    collection_type = parse_int(item.get("type"), 0)
    ep_status = parse_int(item.get("ep_status"), 0)
    total_episodes = extract_total_episodes(item, subject)
    return {
        "subject_id": subject_id,
        "title": extract_title(subject, subject_id),
        "collection_type": collection_type,
        "collection_label": COLLECTION_TYPES.get(collection_type, "未知"),
        "rate": parse_int(item.get("rate"), 0),
        "ep_status": ep_status,
        "total_episodes": total_episodes,
        "progress_ratio": (
            round(ep_status / total_episodes, 3) if total_episodes > 0 else None
        ),
        "tags": extract_tags(item, subject),
    }


def local_subject_map(local_data: JsonDict) -> dict[object, JsonDict]:
    subjects = list_from_value(local_data.get("subjects"))
    result: dict[object, JsonDict] = {}
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        subject_id = normalize_subject_id(subject.get("subject_id"))
        result[subject_id] = cast(JsonDict, subject)
    return result


def progress_anomalies(evidence_items: list[JsonDict]) -> list[JsonDict]:
    anomalies: list[JsonDict] = []
    for item in evidence_items:
        ep_status = parse_int(item.get("ep_status"), 0)
        total_episodes = parse_int(item.get("total_episodes"), 0)
        collection_type = parse_int(item.get("collection_type"), 0)
        if total_episodes > 0 and ep_status > total_episodes:
            anomalies.append({**item, "issue": "进度超过总集数"})
        elif collection_type in {3, 4} and total_episodes > 0 and ep_status == 0:
            anomalies.append({**item, "issue": "在看/搁置但没有观看进度"})
        elif (
            collection_type == 3 and total_episodes > 0 and ep_status >= total_episodes
        ):
            anomalies.append({**item, "issue": "已接近完结但仍标记为在看"})
    return anomalies


def build_subscription_conflicts(
    evidence_items: list[JsonDict],
    local_data: JsonDict,
) -> list[JsonDict]:
    if local_data.get("status") != "available":
        return []

    local_map = local_subject_map(local_data)
    subscribed_ids = {
        subject_id
        for subject_id, subject in local_map.items()
        if parse_int(subject.get("group_count"), 0) > 0
    }
    collection_ids = {item.get("subject_id") for item in evidence_items}
    conflicts: list[JsonDict] = []
    for item in evidence_items:
        subject_id = item.get("subject_id")
        collection_type = parse_int(item.get("collection_type"), 0)
        is_subscribed = subject_id in subscribed_ids
        if collection_type == 5 and is_subscribed:
            conflicts.append({**item, "conflict_type": "已抛弃但仍订阅"})
        elif collection_type == 2 and is_subscribed:
            conflicts.append({**item, "conflict_type": "已看过但仍订阅"})
        elif collection_type == 3 and not is_subscribed:
            conflicts.append({**item, "conflict_type": "在看但未订阅"})

    for subject_id, subject in local_map.items():
        if (
            parse_int(subject.get("group_count"), 0) > 0
            and subject_id not in collection_ids
        ):
            conflicts.append(
                {
                    "subject_id": subject_id,
                    "title": subject.get("title", str(subject_id)),
                    "group_count": subject.get("group_count", 0),
                    "group_ids": subject.get("group_ids", []),
                    "conflict_type": "本地订阅但收藏缺失",
                }
            )
    return conflicts


def top_items(counter: dict[str, int], limit: int = 10) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))[:limit])


def build_analysis(
    *,
    username: str,
    collections: list[JsonDict],
    local_data: JsonDict,
    generated_at: str | None = None,
) -> JsonDict:
    evidence_items = [collection_to_evidence(item) for item in collections]
    collection_counts = {label: 0 for label in COLLECTION_TYPES.values()}
    rating_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    backlog_items: list[JsonDict] = []

    for item in evidence_items:
        label = str(item.get("collection_label", "未知"))
        if label in collection_counts:
            collection_counts[label] += 1
        rate = parse_int(item.get("rate"), 0)
        if rate > 0:
            rating_counts[str(rate)] = rating_counts.get(str(rate), 0) + 1
        for tag in list_from_value(item.get("tags")):
            if isinstance(tag, str):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if parse_int(item.get("collection_type"), 0) in {1, 3, 4}:
            backlog_items.append(item)

    local_status = str(local_data.get("status", "unknown"))
    local_map = local_subject_map(local_data) if local_status == "available" else {}
    subscribed_ids = {
        subject_id
        for subject_id, subject in local_map.items()
        if parse_int(subject.get("group_count"), 0) > 0
    }
    collection_ids = {item.get("subject_id") for item in evidence_items}
    subscription_conflicts = build_subscription_conflicts(evidence_items, local_data)
    analysis: JsonDict = {
        "generated_at": generated_at or dt.datetime.now(dt.UTC).isoformat(),
        "username": username,
        "data_sources": {
            "bangumi_api": "available",
            "local_sqlite": local_data.get("status", "unknown"),
        },
        "collection_total": len(evidence_items),
        "collection_type_counts": collection_counts,
        "rating_distribution": dict(sorted(rating_counts.items())),
        "tag_distribution": top_items(tag_counts),
        "backlog": {
            "total": len(backlog_items),
            "watching": collection_counts["在看"],
            "wishlist": collection_counts["想看"],
            "on_hold": collection_counts["搁置"],
            "items": backlog_items[:20],
        },
        "progress_anomalies": progress_anomalies(evidence_items),
        "local_subscription_coverage": {
            "status": local_status,
            "summary": local_data.get("summary", {}),
            "subscribed_collection_count": (
                len(collection_ids & subscribed_ids)
                if local_status == "available"
                else None
            ),
            "unsubscribed_watching_count": (
                sum(
                    1
                    for item in evidence_items
                    if parse_int(item.get("collection_type"), 0) == 3
                    and item.get("subject_id") not in subscribed_ids
                )
                if local_status == "available"
                else None
            ),
        },
        "subscription_conflicts": subscription_conflicts,
        "evidence": evidence_items,
    }
    analysis["recommendations"] = generate_recommendations(analysis)
    return analysis


def evidence_title(item: JsonDict | None) -> str:
    if not item:
        return "无具体条目"
    return str(item.get("title") or item.get("subject_id") or "无具体条目")


def find_first_by_type(
    evidence_items: list[JsonDict], collection_type: int
) -> JsonDict | None:
    for item in evidence_items:
        if parse_int(item.get("collection_type"), 0) == collection_type:
            return item
    return None


def recommendation(
    dimension: str,
    priority: str,
    action: str,
    evidence: list[JsonDict],
    *,
    insufficient_data: bool = False,
) -> JsonDict:
    return {
        "dimension": dimension,
        "priority": priority,
        "action": action,
        "evidence": evidence,
        "insufficient_data": insufficient_data,
    }


def generate_recommendations(analysis: JsonDict) -> list[JsonDict]:
    evidence_items = [
        cast(JsonDict, item)
        for item in list_from_value(analysis.get("evidence"))
        if isinstance(item, dict)
    ]
    counts = dict_from_value(analysis.get("collection_type_counts"))
    conflicts = [
        cast(JsonDict, item)
        for item in list_from_value(analysis.get("subscription_conflicts"))
        if isinstance(item, dict)
    ]
    local_coverage = dict_from_value(analysis.get("local_subscription_coverage"))
    tag_distribution = dict_from_value(analysis.get("tag_distribution"))
    rating_distribution = dict_from_value(analysis.get("rating_distribution"))
    recs: list[JsonDict] = []

    watching_count = parse_int(counts.get("在看"), 0)
    watching_example = find_first_by_type(evidence_items, 3)
    if watching_count > 0 and watching_example is not None:
        recs.append(
            recommendation(
                "追番节奏",
                "立即处理",
                (
                    f"当前在看 {watching_count} 部，先核对《{evidence_title(watching_example)}》"
                    "这类有进度记录的条目，把临近完结或进度异常的番优先补齐。"
                ),
                [watching_example],
            )
        )
    else:
        recs.append(
            recommendation(
                "追番节奏",
                "可观察项",
                "收藏数据里没有在看条目，暂不生成追番节奏调整，只保留后续观察。",
                [{"metric": "在看数量", "value": watching_count}],
                insufficient_data=True,
            )
        )

    wishlist_count = parse_int(counts.get("想看"), 0)
    wishlist_example = find_first_by_type(evidence_items, 1)
    if wishlist_count > 0 and wishlist_example is not None:
        recs.append(
            recommendation(
                "想看清单清理",
                "季度整理",
                (
                    f"想看清单有 {wishlist_count} 部，可从《{evidence_title(wishlist_example)}》"
                    "开始按篇幅、标签和近期兴趣分层，先清理低优先级长篇。"
                ),
                [wishlist_example],
            )
        )
    else:
        recs.append(
            recommendation(
                "想看清单清理",
                "可观察项",
                "没有想看条目，暂不需要清单清理。",
                [{"metric": "想看数量", "value": wishlist_count}],
                insufficient_data=True,
            )
        )

    paused_count = parse_int(counts.get("搁置"), 0) + parse_int(counts.get("抛弃"), 0)
    dropped_conflict = next(
        (item for item in conflicts if item.get("conflict_type") == "已抛弃但仍订阅"),
        None,
    )
    paused_example = dropped_conflict or find_first_by_type(evidence_items, 4)
    if paused_count > 0 and paused_example is not None:
        recs.append(
            recommendation(
                "搁置/抛弃复盘",
                "立即处理" if dropped_conflict else "季度整理",
                (
                    f"搁置/抛弃共有 {paused_count} 部；优先复盘"
                    f"《{evidence_title(paused_example)}》，避免继续占用订阅和注意力。"
                ),
                [paused_example],
            )
        )
    else:
        recs.append(
            recommendation(
                "搁置/抛弃复盘",
                "可观察项",
                "没有搁置或抛弃条目，暂时无需复盘。",
                [{"metric": "搁置加抛弃数量", "value": paused_count}],
                insufficient_data=True,
            )
        )

    if tag_distribution or rating_distribution:
        top_tag = next(iter(tag_distribution), "无标签")
        recs.append(
            recommendation(
                "评分与偏好标签",
                "季度整理",
                (
                    f"当前最高频标签是「{top_tag}」，评分分布覆盖 "
                    f"{len(rating_distribution)} 个分数段；后续选番可以优先保留高分高频标签，"
                    "同时复盘低分标签的踩雷来源。"
                ),
                [
                    {
                        "metric": "tag_distribution",
                        "value": tag_distribution,
                    },
                    {
                        "metric": "rating_distribution",
                        "value": rating_distribution,
                    },
                ],
            )
        )
    else:
        recs.append(
            recommendation(
                "评分与偏好标签",
                "可观察项",
                "收藏数据缺少评分和标签，暂不推断偏好。",
                [{"metric": "评分/标签", "value": "数据不足"}],
                insufficient_data=True,
            )
        )

    local_status = str(local_coverage.get("status", "unknown"))
    if local_status == "available":
        conflict_example = conflicts[0] if conflicts else None
        action = (
            f"本地订阅与收藏发现 {len(conflicts)} 个冲突；"
            f"先处理《{evidence_title(conflict_example)}》这类状态不一致条目。"
            if conflict_example
            else "本地订阅已可读取，当前未发现收藏状态冲突；后续只需周期性核对通知噪音。"
        )
        recs.append(
            recommendation(
                "插件订阅通知策略",
                "立即处理" if conflict_example else "可观察项",
                action,
                [conflict_example or {"metric": "subscription_conflicts", "value": 0}],
            )
        )
    else:
        recs.append(
            recommendation(
                "插件订阅通知策略",
                "可观察项",
                "本地 SQLite 订阅数据缺失，无法判断订阅通知是否与 Bangumi 收藏冲突。",
                [{"metric": "local_sqlite_status", "value": local_status}],
                insufficient_data=True,
            )
        )
    return recs


def render_markdown_report(analysis: JsonDict) -> str:
    lines = [
        "# Bangumi 番剧管理策略分析",
        "",
        f"- 目标用户：{analysis.get('username', '')}",
        f"- 生成时间：{analysis.get('generated_at', '')}",
        f"- 收藏总量：{analysis.get('collection_total', 0)}",
        "",
        "## 收藏概览",
    ]
    counts = dict_from_value(analysis.get("collection_type_counts"))
    for label in COLLECTION_TYPES.values():
        lines.append(f"- {label}：{counts.get(label, 0)}")

    lines.extend(["", "## 策略建议"])
    for rec_value in list_from_value(analysis.get("recommendations")):
        if not isinstance(rec_value, dict):
            continue
        rec = cast(JsonDict, rec_value)
        lines.append("")
        lines.append(f"### {rec.get('dimension', '')}")
        lines.append(f"- 优先级：{rec.get('priority', '')}")
        lines.append(f"- 行动：{rec.get('action', '')}")
        evidence_parts: list[str] = []
        for evidence_value in list_from_value(rec.get("evidence")):
            if isinstance(evidence_value, dict):
                evidence = cast(JsonDict, evidence_value)
                title = evidence.get("title")
                metric = evidence.get("metric")
                if title:
                    evidence_parts.append(str(title))
                elif metric:
                    evidence_parts.append(f"{metric}={evidence.get('value')}")
        lines.append(
            f"- 证据：{'; '.join(evidence_parts) if evidence_parts else '数据不足'}"
        )

    conflicts = [
        cast(JsonDict, item)
        for item in list_from_value(analysis.get("subscription_conflicts"))
        if isinstance(item, dict)
    ]
    lines.extend(["", "## 订阅冲突"])
    if conflicts:
        for conflict in conflicts:
            lines.append(
                f"- {conflict.get('conflict_type', '')}："
                f"{conflict.get('title', conflict.get('subject_id', ''))}"
            )
    else:
        lines.append("- 未发现明确订阅冲突，或本地订阅数据不足。")

    return "\n".join(lines) + "\n"


def write_reports(analysis: JsonDict, config: AnalysisConfig) -> tuple[Path, Path]:
    output_dir = config.output_dir
    output_json = config.output_json or output_dir / DEFAULT_JSON_NAME
    output_md = config.output_md or output_dir / DEFAULT_MARKDOWN_NAME
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_md.write_text(render_markdown_report(analysis), encoding="utf-8")
    return output_json, output_md


def collect_user_collections(
    client: BangumiV0Client,
    username: str,
    page_limit: int,
) -> list[JsonDict]:
    collections: list[JsonDict] = []
    for collection_type in COLLECTION_TYPES:
        collections.extend(
            client.iter_user_collections(
                username,
                collection_type,
                subject_type=int(SubjectType.ANIME),
                page_limit=page_limit,
            )
        )
    return collections


def needs_subject_enrichment(item: JsonDict) -> bool:
    subject = item_subject(item)
    if not subject:
        return True
    return extract_total_episodes(item, subject) == 0


def enrich_user_collections(
    client: BangumiV0Client,
    collections: list[JsonDict],
) -> list[JsonDict]:
    enriched: list[JsonDict] = []
    for item in collections:
        if not needs_subject_enrichment(item):
            enriched.append(item)
            continue

        subject_id = normalize_subject_id(
            item.get("subject_id") or item_subject(item).get("id")
        )
        if not isinstance(subject_id, int):
            enriched.append(item)
            continue

        item_copy = dict(item)
        try:
            subject = client.get_subject(subject_id)
            if subject:
                item_copy["subject"] = subject
            if extract_total_episodes(item_copy, item_subject(item_copy)) == 0:
                episodes = client.iter_episodes(subject_id)
                normal_episodes = [
                    episode
                    for episode in episodes
                    if parse_int(episode.get("type"), 0) == 0
                ]
                if normal_episodes:
                    item_copy["total_episodes"] = len(normal_episodes)
        except AnalysisError as exc:
            item_copy["enrichment_status"] = f"failed: {safe_text(exc, client.config)}"
        enriched.append(item_copy)
    return enriched


def run(config: AnalysisConfig) -> tuple[JsonDict, Path, Path]:
    if not config.access_token:
        raise AnalysisError(
            "缺少 Bangumi access token / access_token。请在 .env 写入 "
            "access_token=...，或通过 --access-token / BANGUMI_ACCESS_TOKEN 提供。"
        )
    client = BangumiV0Client(config)
    username = resolve_username(config, client)
    local_data = read_local_subscriptions(config.db_path, require_db=config.require_db)
    collections = collect_user_collections(client, username, config.page_limit)
    collections = enrich_user_collections(client, collections)
    analysis = build_analysis(
        username=username,
        collections=collections,
        local_data=local_data,
    )
    data_sources = dict_from_value(analysis.get("data_sources"))
    data_sources["render_mode"] = config.render_mode
    analysis["data_sources"] = data_sources
    output_json, output_md = write_reports(analysis, config)
    return analysis, output_json, output_md


def main(argv: list[str] | None = None) -> int:
    config: AnalysisConfig | None = None
    try:
        config = load_config(argv)
        analysis, output_json, output_md = run(config)
        print(
            "已生成 Bangumi 策略分析："
            f"username={analysis.get('username')} "
            f"json={output_json} markdown={output_md}"
        )
        return 0
    except AnalysisError as exc:
        print(safe_text(exc, config), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已中断。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"未预期错误：{safe_text(exc, config)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
