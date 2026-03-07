import pytest
from loguru import logger

from src.render import SubjectRenderer


@pytest.mark.asyncio
async def test_render_subject_card_success() -> None:
    # 准备测试数据
    subject_data = {
        "date": "2026-01-11",
        "platform": "TV",
        "images": {
            "small": "https://lain.bgm.tv/r/200/pic/cover/l/71/50/525565_OxOv7.jpg",
            "grid": "https://lain.bgm.tv/r/100/pic/cover/l/71/50/525565_OxOv7.jpg",
            "large": "https://lain.bgm.tv/pic/cover/l/71/50/525565_OxOv7.jpg",
            "medium": "https://lain.bgm.tv/r/800/pic/cover/l/71/50/525565_OxOv7.jpg",
            "common": "https://lain.bgm.tv/r/400/pic/cover/l/71/50/525565_OxOv7.jpg",
        },
        "summary": "总是活力充沛,却又很在意周遭目光的女孩:铃木实优\r\n以及个性文静,却能清楚表达自己意见的男生:谷悠介\r\n\r\n本次故事将讲述这两人的生活点滴铃木喜欢着谷,却一直无法鼓起勇气告白直到某天,两人放学回家时走在同一条路上并牵起了手借由该契机,两人相互倾诉对彼此的好感并开始了交往同学们虽然感到讶异,但也都很支持两人的恋情\r\n这部恋爱喜剧描写的,正是这对个性截然相反的两人,在彼此尊重之下慢慢加深互相的理解,并与朋友们一同度过的校园生活点滴如此温暖的故事就此开幕!\r\n\r\n\r\n\r\n[简介原文]\r\nいつも元気いっぱいだけど周りの目を気にしてしまう女子・鈴木と、\r\n物静かだけど自分の意見をしっかり言える男子・谷\r\n正反対な二人が误解や勘違いをしながらもお互いを尊重し、\r\nゆっくりと理解を深めていく姿と、友人たちとの学校生活を描くラブコメディ",
        "name": "正反対な君と僕",
        "name_cn": "相反的你和我",
        "tags": [
            {"name": "恋爱", "count": 1356},
            {"name": "校园", "count": 1071},
            {"name": "2026年1月", "count": 1033},
            {"name": "漫画改", "count": 823},
        ],
        "infobox": [
            {"key": "中文名", "value": "相反的你和我"},
            {"key": "别名", "value": [{"v": "正相反的你与我"}]},
            {"key": "话数", "value": "12"},
            {"key": "放送开始", "value": "2026年1月11日"},
        ],
        "total_episodes": 12,
        "id": 525565,
        "type": 2,
        "rating": {
            "rank": 677,
            "total": 2517,
            "count": {
                "1": 6,
                "2": 3,
                "3": 7,
                "4": 13,
                "5": 40,
                "6": 167,
                "7": 753,
                "8": 1234,
                "9": 194,
                "10": 100,
            },
            "score": 7.6,
        },
    }

    renderer = SubjectRenderer()

    # 运行渲染器
    base64_image = await renderer.render_subject_card(
        rpc_url="https://api.unitedpooh.top/rpc",
        data=subject_data,
        headless=True,
        timeout=60000,
    )

    # 验证结果
    assert base64_image is not None, "[-] 渲染失败,未返回 Base64 字符串"
    assert isinstance(base64_image, str), "返回值应为 Base64 字符串"
    assert len(base64_image) > 100, "Base64 字符串过短"

    logger.info(f"[+] 渲染成功!图片长度: {len(base64_image)} 字符")
