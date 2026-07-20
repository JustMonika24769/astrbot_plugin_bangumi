from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bangumi.src.card_renderer import CardRenderError
from astrbot_plugin_bangumi.src.entities import (
    BroadcastSchedule,
    SubscribeResult,
    TrackedSubject,
)
from astrbot_plugin_bangumi.src.plugin_config import PluginConfig
from astrbot_plugin_bangumi.src.tracking import SubscriptionManager


def build_manager(api, repository, renderer, context) -> SubscriptionManager:
    return SubscriptionManager(
        api=api,
        repository=repository,
        renderer=renderer,
        context=context,
        config=PluginConfig({}),
    )


@pytest.mark.asyncio
async def test_subscribe_uses_latest_episode_as_baseline(
    subject, episode, context
) -> None:
    api = MagicMock(session=MagicMock())
    api.get_latest_aired_episode = AsyncMock(return_value=episode)
    repository = MagicMock()
    repository.subscribe.return_value = True
    manager = build_manager(api, repository, MagicMock(), context)
    manager._broadcast_schedules[str(subject.id)] = BroadcastSchedule(
        broadcast_date="2026-07-15",
        broadcast_time="23:30",
    )

    result = await manager.subscribe("session", subject)

    assert result == SubscribeResult(subject, episode, True)
    api.get_latest_aired_episode.assert_awaited_once_with(
        subject.id,
        broadcast_time="23:30",
        refresh=True,
    )
    repository.subscribe.assert_called_once_with(
        "session",
        subject,
        baseline_episode=4,
        broadcast_date="2026-07-15",
        broadcast_time="23:30",
    )


@pytest.mark.asyncio
async def test_check_updates_marks_only_successful_delivery(
    subject, episode, context
) -> None:
    api = MagicMock(session=MagicMock())
    api.get_subject = AsyncMock(return_value=subject)
    api.get_latest_aired_episode = AsyncMock(return_value=episode)
    api.with_embedded_cover = AsyncMock(return_value=subject)
    repository = MagicMock()
    repository.list_tracked_subjects.return_value = [
        TrackedSubject(
            subject_id=str(subject.id),
            title=subject.title,
            name=subject.name,
            cover_url=subject.cover_url,
            air_date=subject.air_date,
            total_episodes=12,
            current_episode=3,
            broadcast_date=None,
            broadcast_time=None,
            last_checked_at=None,
            last_error=None,
        )
    ]
    repository.pending_sessions.return_value = ["good", "bad"]
    repository.delivery_progress.return_value = {"good": 3, "bad": 2}
    renderer = MagicMock()
    renderer.update_card = AsyncMock(return_value="card.jpg")
    context.send_message.side_effect = [True, False]
    manager = build_manager(api, repository, renderer, context)

    report = await manager.check_updates(refresh=True)

    assert report.delivered == 1
    assert report.failed == 1
    assert renderer.update_card.await_count == 2
    baselines = {
        call.kwargs["previous_episode"]
        for call in renderer.update_card.await_args_list
    }
    assert baselines == {2, 3}
    repository.mark_notified.assert_called_once_with("good", str(subject.id), 4)
    repository.mark_delivery_error.assert_called_once()


@pytest.mark.asyncio
async def test_check_updates_merges_aliases_before_sending(
    subject, episode, context
) -> None:
    canonical = "onebot-main:GroupMessage:818800431"
    api = MagicMock(session=MagicMock())
    api.get_subject = AsyncMock(return_value=subject)
    api.get_latest_aired_episode = AsyncMock(return_value=episode)
    api.with_embedded_cover = AsyncMock(return_value=subject)
    repository = MagicMock()
    repository.list_tracked_subjects.return_value = [
        TrackedSubject(
            subject_id=str(subject.id),
            title=subject.title,
            name=subject.name,
            cover_url=subject.cover_url,
            air_date=subject.air_date,
            total_episodes=12,
            current_episode=3,
            broadcast_date=None,
            broadcast_time=None,
            last_checked_at=None,
            last_error=None,
        )
    ]
    repository.pending_sessions.side_effect = [
        ["818800431", canonical],
        [canonical],
    ]
    repository.migrate_session_aliases.return_value = 1
    repository.delivery_progress.return_value = {canonical: 3}
    renderer = MagicMock()
    renderer.update_card = AsyncMock(return_value="card.jpg")
    manager = build_manager(api, repository, renderer, context)

    report = await manager.check_updates(refresh=True)

    assert report.pending_deliveries == 1
    assert report.delivered == 1
    assert context.send_message.await_count == 1
    repository.migrate_session_aliases.assert_called_once_with(
        canonical, {"818800431"}
    )
    repository.mark_notified.assert_called_once_with(
        canonical, str(subject.id), 4
    )


@pytest.mark.asyncio
async def test_check_updates_falls_back_to_text_when_t2i_fails(
    subject, episode, context
) -> None:
    api = MagicMock(session=MagicMock())
    api.get_subject = AsyncMock(return_value=subject)
    api.get_latest_aired_episode = AsyncMock(return_value=episode)
    api.with_embedded_cover = AsyncMock(return_value=subject)
    repository = MagicMock()
    repository.list_tracked_subjects.return_value = [
        TrackedSubject(
            subject_id=str(subject.id),
            title=subject.title,
            name=subject.name,
            cover_url=subject.cover_url,
            air_date=subject.air_date,
            total_episodes=12,
            current_episode=3,
            broadcast_date=None,
            broadcast_time=None,
            last_checked_at=None,
            last_error=None,
        )
    ]
    repository.pending_sessions.return_value = ["session"]
    repository.delivery_progress.return_value = {"session": 3}
    renderer = MagicMock()
    renderer.update_card = AsyncMock(side_effect=CardRenderError("T2I unavailable"))
    manager = build_manager(api, repository, renderer, context)

    report = await manager.check_updates(refresh=True)

    assert report.delivered == 1
    assert report.failed == 0
    repository.mark_notified.assert_called_once_with("session", str(subject.id), 4)
    sent_chain = context.send_message.await_args.args[1]
    assert "更新至第 4 集" in sent_chain.chain[0].text


@pytest.mark.asyncio
async def test_check_updates_does_not_render_without_pending_sessions(
    subject, episode, context
) -> None:
    api = MagicMock(session=MagicMock())
    api.get_subject = AsyncMock(return_value=subject)
    api.get_latest_aired_episode = AsyncMock(return_value=episode)
    api.with_embedded_cover = AsyncMock(return_value=subject)
    repository = MagicMock()
    repository.list_tracked_subjects.return_value = [
        SimpleNamespace(
            subject_id=str(subject.id),
            title=subject.title,
            broadcast_date=None,
            broadcast_time=None,
        )
    ]
    repository.pending_sessions.return_value = []
    renderer = MagicMock()
    renderer.update_card = AsyncMock()
    manager = build_manager(api, repository, renderer, context)

    report = await manager.check_updates()

    assert report.delivered == 0
    renderer.update_card.assert_not_awaited()


@pytest.mark.asyncio
async def test_render_test_card_does_not_advance_progress(
    subject, episode, context
) -> None:
    api = MagicMock(session=MagicMock())
    api.get_subject = AsyncMock(return_value=subject)
    api.get_latest_aired_episode = AsyncMock(return_value=episode)
    api.with_embedded_cover = AsyncMock(return_value=subject)
    repository = MagicMock()
    repository.find_subscription.return_value = [
        SimpleNamespace(
            subject_id=str(subject.id),
            broadcast_time=None,
            last_notified_episode=3,
        )
    ]
    renderer = MagicMock()
    renderer.update_card = AsyncMock(return_value="card.jpg")
    manager = build_manager(api, repository, renderer, context)

    assert await manager.render_test_card("session", str(subject.id)) == "card.jpg"
    repository.mark_notified.assert_not_called()


def test_notification_session_uses_astrbot_message_type_values() -> None:
    context = MagicMock()
    onebot = MagicMock()
    onebot.meta.return_value = SimpleNamespace(
        id="onebot-main", name="aiocqhttp"
    )
    telegram = MagicMock()
    telegram.meta.return_value = SimpleNamespace(
        id="telegram-main", name="telegram"
    )
    context.platform_manager.platform_insts = [onebot, telegram]
    manager = build_manager(MagicMock(), MagicMock(), MagicMock(), context)

    assert manager._notification_session("818800431") == (
        "onebot-main:GroupMessage:818800431"
    )
    assert manager._notification_session(
        "aiocqhttp:group:123"
    ) == "onebot-main:GroupMessage:123"
    assert manager._notification_session(
        "telegram-main:FriendMessage:456"
    ) == "telegram-main:FriendMessage:456"


def test_notification_session_rejects_ambiguous_legacy_platform() -> None:
    context = MagicMock()
    platforms = []
    for platform_id in ("onebot-a", "onebot-b"):
        platform = MagicMock()
        platform.meta.return_value = SimpleNamespace(
            id=platform_id, name="aiocqhttp"
        )
        platforms.append(platform)
    context.platform_manager.platform_insts = platforms
    manager = build_manager(MagicMock(), MagicMock(), MagicMock(), context)

    with pytest.raises(RuntimeError, match="多个 aiocqhttp"):
        manager._notification_session("818800431")
