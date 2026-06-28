# Bangumi v1.3.2-v1.4.1 顺序迭代计划

## 总原则

- 严格按 `v1.3.2 -> v1.4.0 -> v1.4.1` 顺序推进,当前版本未通过审核前不进入下一版本。
- 每个版本使用独立分支、独立提交留痕;版本内 review 或 QA 不过时,只在当前版本继续迭代。
- 每个版本都必须同步 `metadata.yaml`、`README.md`、`CHANGELOG.md`,并保持 README 指令表与 `main.py` 注册命令一致。
- `v1.4.0` 和 `v1.4.1` 必须通过真实数据渲染图自检;只有我方能清晰读出图片中文字、确认 desc 无重叠/裁切后,才交给用户人工审核。
- 涉及较大实现时使用 `multi-agent-pipeline` 分阶段推进,由 orchestrator 负责集成、冲突处理、最终验证和 Git 留痕。

## v1.3.2: BGM 搜索指令别名

分支: `codex/bgm-aliases-1.3.2`

范围:
- `/bgm番剧` 增加别名: `/bgm动漫`、`/bgm动画`、`/bgm番`、`/bgm动画片`。
- `/bgm剧场版` 增加别名: `/bgm电影`。
- 不修改图片渲染、字体、响应格式或搜索结果样式。

验收:
- 新别名注册在现有 `search_anime` / `search_movie` handler 上,不复制业务逻辑。
- README 命令表包含全部注册命令。
- 版本号更新为 `v1.3.2`。

Git 留痕:
- 提交信息: `feat :sparkles: : 支持 bgm 搜索指令别名`

## v1.4.0: 长文本响应图片化与三渲染模式

分支: `codex/response-image-rendering-1.4.0`,基于通过审核的 `v1.3.2`。

范围:
- 所有文本响应统一判断: `30` 字以内且无换行继续纯文本;否则渲染为图片。
- `render_mode` 调整为 `pillow`、`playwright`、`rpc`,默认 `pillow`;旧值 `html` 兼容映射为 `playwright`。
- 图片风格复用 `pastel_lightbox`、`editorial_digest`、`cinematic_poster` 三种 episode 风格。
- 得意黑首次启动检测本地字体缓存;不存在则从官方 Smiley Sans 发布包拉取,存在即使用,拉取失败则退化到当前渲染默认字体。
- `/bgm模板` 升级为统一图片风格切换入口,保持旧序号与模板名兼容。

设计与审核:
- 使用 `ce-frontend-design` 做三风格响应卡设计,延续现有 episode 三模板的视觉语言。
- 使用真实 Bangumi 数据生成三风格预览图。
- 我方先打开预览图自检,确认标题、meta、正文、候选编号都能清晰读出且无元素重叠后,再交给用户审核。
- 用户审核不过时,只在 `v1.4.0` 内继续迭代。

Git 留痕:
- 提交信息: `feat :sparkles: : 支持长文本响应图片化与三种渲染模式`

## v1.4.1: BGM 搜索结果三风格渲染

分支: `codex/search-result-styles-1.4.1`,基于通过审核的 `v1.4.0`。

范围:
- `/bgm`、`/bgm番剧`、`/bgm剧场版`、`/bgm漫画` 及其别名的搜索结果支持三种统一风格。
- 复用 `v1.4.0` 已确认的字体、渲染模式和风格基础设施。
- 不重新发散设计,只把搜索结果渲染接入已确认的三风格系统。

验收:
- 三种风格均使用真实 Bangumi 搜索数据生成预览图。
- 图片中文字可清晰阅读,desc 不重叠、不被遮挡、不异常裁切。
- 保持现有搜索语义和 top_k 行为不变。

Git 留痕:
- 提交信息: `feat :sparkles: : 支持 bgm 搜索结果三风格渲染`

## 每版本质量门禁

每个版本提交前必须通过:

```bash
python -m pytest -q
python -m mypy src main.py
python -m ruff check .
python -m ruff format --check .
git diff --check
```

`v1.4.0` 和 `v1.4.1` 额外要求:
- 生成真实数据预览图。
- orchestrator 先完成肉眼可读性自检。
- 用户审核确认后再进入下一版本。
