from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bangumi.src.app import SubscriptionService
from astrbot_plugin_bangumi.src.domain.exceptions import DatabaseError
from astrbot_plugin_bangumi.src.domain.schemas import Episode


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.subscribe_subject = MagicMock(return_value=True)
    repo.remove_subscription = MagicMock(return_value=True)
    repo.find_group_subscription_candidates = MagicMock(return_value=[])
    repo.get_monitored_subjects = MagicMock(return_value=[])
    repo.update_subject_episode = MagicMock()
    repo.get_subject_subscribers = MagicMock(return_value=[])
    return repo


@pytest.fixture
def mock_service() -> MagicMock:
    service = MagicMock()
    service.search_subjects = AsyncMock()
    service.get_subject_details = AsyncMock()
    service.get_calendar = AsyncMock()
    service.get_latest_episode = AsyncMock()
    service.get_subject_base64image = AsyncMock()
    return service


@pytest.fixture
def mock_config_manager() -> MagicMock:
    config_manager = MagicMock()
    config_manager.get_render_mode.return_value = "html"
    config_manager.get_render_server_url.return_value = "rpc"
    config_manager.get_max_retries.return_value = 1
    config_manager.get_episode_card_template.return_value = "cinematic_poster"
    return config_manager


@pytest.mark.asyncio
async def test_get_subscribe_candidates_clamps_limit_and_handles_empty(
    mock_repo: MagicMock, mock_service: MagicMock, mock_config_manager: MagicMock
) -> None:
    service = SubscriptionService(mock_repo, mock_service, mock_config_manager)

    error, candidates = await service.get_subscribe_candidates("", 100)
    assert error == "❌ 请提供要订阅的番剧关键词或ID"
    assert candidates == []

    mock_service.search_subjects.return_value = {"data": [{"id": 1, "name": "A"}]}
    error, candidates = await service.get_subscribe_candidates("A", 100)

    assert error is None
    assert candidates == [{"subject_id": "1", "name": "A"}]
    mock_service.search_subjects.assert_awaited_with(
        keyword="A", limit=10, subject_type=[2], subject_tags=None
    )


@pytest.mark.asyncio
async def test_subscribe_by_subject_id_handles_database_error(
    mock_repo: MagicMock, mock_service: MagicMock, mock_config_manager: MagicMock
) -> None:
    mock_service.get_subject_details.return_value = {"id": 1, "name": "A", "eps": "12"}
    mock_service.get_calendar.return_value = [{"items": [{"id": 1}]}]
    mock_repo.subscribe_subject.side_effect = DatabaseError("db down")
    service = SubscriptionService(mock_repo, mock_service, mock_config_manager)

    result = await service.subscribe_by_subject_id("group", "1")

    assert "处理失败: db down" in result


@pytest.mark.asyncio
async def test_unsubscribe_empty_query(
    mock_repo: MagicMock, mock_service: MagicMock, mock_config_manager: MagicMock
) -> None:
    service = SubscriptionService(mock_repo, mock_service, mock_config_manager)

    result = await service.unsubscribe("group", "  ")

    assert result == "❌ 请提供要取消订阅的番剧关键词或ID"
    mock_repo.find_group_subscription_candidates.assert_not_called()


@pytest.mark.asyncio
async def test_check_updates_updates_new_episode_and_notifies(
    mock_repo: MagicMock, mock_service: MagicMock, mock_config_manager: MagicMock
) -> None:
    subject = SimpleNamespace(subject_id="1", name="番", current_episode=1)
    episode = Episode(
        id=10,
        subject_id=1,
        type=0,
        ep=2,
        sort=2,
        name="ep2",
        name_cn="第二集",
        comment=1,
    )
    mock_repo.get_monitored_subjects.return_value = [subject]
    mock_service.get_latest_episode.return_value = episode
    mock_service.get_subject_base64image.return_value = None
    service = SubscriptionService(mock_repo, mock_service, mock_config_manager)
    service._notify_subscribers = AsyncMock()

    await service.check_updates()

    mock_repo.update_subject_episode.assert_called_once_with("1", 2)
    service._notify_subscribers.assert_awaited_once_with(episode, "1", "番")


@pytest.mark.asyncio
async def test_notify_subscribers_skips_without_groups(
    mock_repo: MagicMock, mock_service: MagicMock, mock_config_manager: MagicMock
) -> None:
    service = SubscriptionService(mock_repo, mock_service, mock_config_manager)
    service.renderer.render_episode = AsyncMock()

    await service._notify_subscribers(_episode(), "1", "番")

    service.renderer.render_episode.assert_not_called()


@pytest.mark.asyncio
async def test_notify_subscribers_passes_configured_episode_template(
    mock_repo: MagicMock,
    mock_service: MagicMock,
    mock_config_manager: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_repo.get_subject_subscribers.return_value = ["group"]
    mock_config_manager.get_episode_card_template.return_value = "pastel_lightbox"
    send_message_by_id = AsyncMock()
    monkeypatch.setattr(
        "astrbot_plugin_bangumi.src.app.subscription_service.StarTools.send_message_by_id",
        send_message_by_id,
    )
    service = SubscriptionService(mock_repo, mock_service, mock_config_manager)
    service.renderer.render_episode = AsyncMock(return_value="image")
    episode = _episode()

    await service._notify_subscribers(episode, "1", "番")

    service.renderer.render_episode.assert_awaited_once_with(
        episode,
        rpc_url="rpc",
        max_retries=1,
        variant="pastel_lightbox",
    )
    send_message_by_id.assert_awaited_once()


def _episode() -> Episode:
    return Episode(
        id=10,
        subject_id=1,
        type=0,
        ep=2,
        sort=2,
        name="ep2",
        name_cn="第二集",
        comment=1,
    )
