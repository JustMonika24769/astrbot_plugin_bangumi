"""Optional real-browser smoke test. Install Playwright and Chromium to run it."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

BRIDGE_FIXTURE = r"""
window.fixture = {
  subscriptions: [
    {subject_id:'454083',title:'少女乐队的呐喊',cover_url:'https://blocked.invalid/poster.jpg',session_id:'onebot-main:GroupMessage:10001',total_episodes:13,current_episode:11,last_notified_episode:10,broadcast_time:'23:30',weekly_schedule:'常规每周五 23:30（北京时间）',broadcast_schedule:'首播 2024-04-05 · 每周五 23:30',last_checked_at:'2026-11-12T19:30:00',pending:true},
    {subject_id:'328609',title:'葬送的芙莉莲',cover_url:'',session_id:'onebot-main:GroupMessage:10001',total_episodes:28,current_episode:28,last_notified_episode:28,broadcast_time:'22:00',broadcast_schedule:'每周五 22:00',last_checked_at:'2026-11-12T19:30:00',pending:false},
    {subject_id:'253',title:'星际牛仔',cover_url:'',session_id:'onebot-main:FriendMessage:10002',total_episodes:26,current_episode:10,last_notified_episode:9,broadcast_time:'',broadcast_schedule:'未设置',last_checked_at:'2026-11-12T19:30:00',pending:true,delivery_error:'上次发送失败，等待下一轮重试'}
  ],
  platforms:[{id:'onebot-main',name:'aiocqhttp'}], jobs:[],checking:false
};
window.calls = [];
window.AstrBotPluginView = {
  ready: async () => ({isDark:false}),
  apiGet: async (endpoint) => {
    if (endpoint==='webui/state') return structuredClone(window.fixture);
    if (endpoint==='webui/calendar') return {days:[{weekday_id:1,weekday_name:'星期一',is_today:true,items:[{id:454083,title:'少女乐队的呐喊',cover_url:'',score:8.5}]},{weekday_id:2,weekday_name:'星期二',items:[]}]};
    throw new Error('unexpected endpoint');
  },
  apiPost: async (endpoint, body) => {
    window.calls.push({endpoint,body});
    if (endpoint==='webui/cover') return {cover_url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII='};
    if (endpoint==='webui/subject') return {subject:{id:Number(body.subject_id),title:'少女乐队的呐喊',summary:'<script>window.xss=true</script> 故事简介',total_episodes:13},weekly_schedule:'常规每周五 23:30（北京时间）',episodes:[{id:1,number:12,title:'新的故事',air_date:'2026-11-20'}],airing:{message:'本周暂无已收录排期，可能停更、延期或资料未补全',upcoming:[1]}};
    if (endpoint==='webui/search') return {subjects:[{id:999,title:'<script>window.xss=true</script> 新的故事',air_date:'2026-11-12',score:8.1,cover_url:'javascript:alert(1)'}]};
    if (endpoint==='webui/subscribe') {
      window.fixture.subscriptions.push({...window.fixture.subscriptions[0],title:'新的故事',subject_id:body.subject_id,session_id:body.session_id});
      return {created:true,title:'新的故事'};
    }
    if (endpoint==='webui/unsubscribe') {
      window.fixture.subscriptions=window.fixture.subscriptions.filter(item=>!(item.subject_id===body.subject_id && item.session_id===body.session_id)); return {removed:true};
    }
    if (endpoint==='webui/check') {window.fixture.jobs=[{id:'1',status:'done',started_at:'2026-11-12T20:00:00',summary:'检查完成',report:{details:['示例检查明细']}}]; return {job_id:'1'};}
    throw new Error('unexpected endpoint');
  }
};
"""


@pytest.mark.asyncio
async def test_webui_browser_management_and_responsive_layout(tmp_path: Path) -> None:
    playwright_api = pytest.importorskip("playwright.async_api")
    chromium = shutil.which("chromium") or shutil.which("google-chrome")
    if not chromium:
        pytest.skip("Chromium is not installed")
    async with playwright_api.async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=chromium, args=["--no-sandbox"]
        )
        try:
            page = await browser.new_page(
                viewport={"width": 1440, "height": 1050},
                device_scale_factor=1,
                reduced_motion="reduce",
            )
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def serve(route):
                relative = route.request.url.split("http://bangumi.test/", 1)[-1].split(
                    "?", 1
                )[0]
                file = ROOT / "views" / "bangumi" / (relative or "index.html")
                await route.fulfill(path=str(file))

            await page.route("http://bangumi.test/**", serve)
            await page.add_init_script(BRIDGE_FIXTURE)
            await page.goto("http://bangumi.test/")
            await playwright_api.expect(page.locator(".anime-card")).to_have_count(3)
            await page.wait_for_function(
                "[...document.querySelectorAll('.poster img')].every(img => img.complete && img.naturalWidth > 0)"
            )
            assert await page.locator(".poster img").count() == 3
            await page.screenshot(
                path=str(tmp_path / "webui-desktop.png"), full_page=True
            )
            await page.get_by_role("button", name="等待通知").click()
            await playwright_api.expect(page.locator(".anime-card")).to_have_count(2)
            await page.locator("#local-search").fill("少女")
            await playwright_api.expect(page.locator(".anime-card")).to_have_count(1)
            await page.locator("#local-search").fill("")
            await page.get_by_role("button", name="全部收藏").click()
            await page.locator("#session-filter").select_option(
                "onebot-main:FriendMessage:10002"
            )
            await playwright_api.expect(page.locator(".anime-card")).to_have_count(1)
            await page.locator(".anime-card button[data-remove]").click()
            await playwright_api.expect(page.locator("#confirm-dialog")).to_be_visible()
            await page.locator("#confirm-action").click()
            await playwright_api.expect(
                page.locator("#confirm-dialog")
            ).not_to_be_visible()
            await playwright_api.expect(page.locator(".anime-card")).to_have_count(2)
            await page.locator("#add").click()
            await page.locator("#remote-query").fill("新的故事")
            await page.locator("#search-form").evaluate(
                "(form) => form.requestSubmit()"
            )
            await playwright_api.expect(page.locator(".search-result")).to_have_count(1)
            assert not await page.evaluate("Boolean(window.xss)")
            await page.wait_for_function(
                "document.querySelector('.search-result img')?.naturalWidth > 0"
            )
            assert (
                await page.locator(".search-result img").get_attribute("src")
            ).startswith("data:image/png;base64,")
            await page.locator("[data-subscribe]").click()
            await playwright_api.expect(page.locator("[data-subscribe]")).to_have_text(
                "已订阅"
            )
            await page.locator('[data-close="add-dialog"]').click()
            await playwright_api.expect(page.locator(".anime-card")).to_have_count(3)
            async with page.expect_download() as downloaded:
                await page.locator("#export").click()
            download = await downloaded.value
            payload = json.loads(Path(await download.path()).read_text())
            assert len(payload["subscriptions"]) == 3
            await page.locator("#check").click()
            await page.locator("#confirm-action").click()
            await playwright_api.expect(
                page.locator("#confirm-dialog")
            ).not_to_be_visible()
            await page.locator('[data-page="activity"]').click()
            await playwright_api.expect(page.locator(".activity-card")).to_have_count(1)
            await page.locator('[data-page="calendar"]').click()
            await playwright_api.expect(page.locator(".calendar-card")).to_have_count(1)
            await page.wait_for_function(
                "document.querySelector('.calendar-cover')?.naturalWidth > 0"
            )
            assert (
                await page.evaluate(
                    "window.calls.filter(call=>call.endpoint==='webui/cover' && call.body.subject_id==='454083').length"
                )
                == 1
            )
            await page.locator('[data-day="2"]').click()
            await playwright_api.expect(
                page.locator("#calendar-list .empty-state")
            ).to_be_visible()
            await page.locator('[data-page="subscriptions"]').click()
            await page.locator("#toast").evaluate("element => {element.hidden = true}")
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.screenshot(
                path=str(tmp_path / "webui-mobile.png"), full_page=True
            )
            assert await page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            )
            await page.evaluate("document.documentElement.dataset.theme='dark'")
            await page.set_viewport_size({"width": 1440, "height": 1050})
            await page.screenshot(path=str(tmp_path / "webui-dark.png"), full_page=True)
            await page.locator("#add").click()
            await page.locator("#target-session").select_option("new")
            await page.locator("#target-id").fill("20003")
            await playwright_api.expect(
                page.locator("[data-subscribe]")
            ).to_be_enabled()
            await page.locator("[data-subscribe]").click()
            await playwright_api.expect(page.locator("[data-subscribe]")).to_have_text(
                "已订阅"
            )
            assert (
                await page.evaluate(
                    "window.calls.filter(call=>call.endpoint==='webui/subscribe').at(-1).body.session_id"
                )
                == "onebot-main:GroupMessage:20003"
            )
            assert errors == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_details_work_inside_astrbot_sandbox(tmp_path):
    playwright_api = pytest.importorskip("playwright.async_api")
    chromium = shutil.which("chromium") or shutil.which("google-chrome")
    if not chromium:
        pytest.skip("Chromium is not installed")
    async with playwright_api.async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=chromium, args=["--no-sandbox"]
        )
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1050})

            async def serve(route):
                relative = route.request.url.split("http://bangumi.test/", 1)[-1]
                if relative == "host":
                    await route.fulfill(
                        content_type="text/html",
                        body='<iframe style="width:100%;height:95vh" sandbox="allow-scripts allow-forms allow-downloads" src="/index.html"></iframe>',
                    )
                else:
                    await route.fulfill(path=str(ROOT / "views" / "bangumi" / relative))

            await page.route("http://bangumi.test/**", serve)
            await page.add_init_script(BRIDGE_FIXTURE)
            await page.goto("http://bangumi.test/host")
            frame = page.frame_locator("iframe")
            await playwright_api.expect(frame.locator(".anime-card")).to_have_count(3)
            await playwright_api.expect(
                frame.locator(".poster-bottom").first
            ).to_contain_text("每周五")
            await frame.get_by_role("button", name="条目详情").first.click()
            await playwright_api.expect(frame.locator("#detail-dialog")).to_be_visible()
            await playwright_api.expect(frame.locator("#detail-title")).to_have_text(
                "少女乐队的呐喊"
            )
            await playwright_api.expect(frame.locator(".episode-list")).to_contain_text(
                "2026-11-20（周五）"
            )
            await playwright_api.expect(
                frame.locator(".airing-notice")
            ).to_contain_text("可能停更")
            assert not await page.frames[1].evaluate("Boolean(window.xss)")
            await frame.get_by_role("button", name="关闭详情").click()
            await playwright_api.expect(
                frame.locator("#detail-dialog")
            ).not_to_be_visible()
            # A failed request is visible and can be retried without closing the dialog.
            await page.frames[1].evaluate(
                "() => {window.originalPost=window.AstrBotPluginView.apiPost; window.AstrBotPluginView.apiPost=async(endpoint, body)=>{if(endpoint==='webui/subject')throw new Error('暂时离线');return window.originalPost(endpoint,body);};}"
            )
            await frame.get_by_role("button", name="条目详情").first.click()
            await playwright_api.expect(frame.locator("#detail-body")).to_contain_text(
                "暂时离线"
            )
            await page.frames[1].evaluate(
                "() => {window.AstrBotPluginView.apiPost=window.originalPost;}"
            )
            await frame.get_by_role("button", name="重试", exact=True).click()
            await playwright_api.expect(frame.locator(".episode-list")).to_be_visible()
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.frames[1].evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            )
            await page.screenshot(
                path=str(tmp_path / "webui-details-mobile.png"), full_page=True
            )
        finally:
            await browser.close()
