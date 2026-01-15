<div align="center">

# Bangumi 搜索插件使用指南
[![repo](https://img.shields.io/badge/repo-v1.3-blue.svg)](https://github.com/united-pooh/astrbot_plugin_bangumi)
[![License](https://img.shields.io/badge/license-Apacha2.0-green.svg)](LICENSE-2.0)
[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.0.0-orange.svg)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

**和 AI 一起追番**

</div>

> [!NOTE]  
> 本项目在[astrbot_plugin_bangumi](https://github.com/Amatsutsumi/astrbot_plugin_bangumi) 的基础上进行二次开发

## 📌 核心命令

### 条目搜索 (图文卡片)
`/bgm搜索 <关键词|ID>`

- 通过名称或ID搜索动画、游戏、书籍等条目。
- **功能升级**：自动生成精美的图文卡片，包含封面、评分、排名、简介及标签信息。
- **示例**：
  - `/bgm搜索 进击的巨人`
  - `/bgm搜索 326` (通过 Subject ID 搜索)

## 🛠️ 配置参数

在 AstrBot 的管理面板或配置文件中设置：

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `access_token` | string | 无 | Bangumi API 令牌（建议配置以获得更高配额） |
| `user_agent` | string | 自动生成 | API 请求头 User-Agent，无需手动配置 |
| `proxy_http` | string | 无 | HTTP 代理地址 (例如 `127.0.0.1`) |
| `port` | int | 无 | HTTP 代理端口 (例如 `7890`) |

### Access Token 获取
虽然不强制，但建议配置 Access Token 以避免 API 限流。
1. 注册/登录 [Bangumi](https://bgm.tv/)
2. 访问 [个人令牌页面](https://next.bgm.tv/demo/access-token/create) 创建新令牌。
3. 将生成的 Token 填入插件配置的 `access_token` 字段。

## 📦 环境依赖

插件首次运行时会自动检查并安装以下依赖：
- **Playwright 浏览器内核**: 用于渲染卡片图片。

如果遇到环境问题，可尝试手动安装：
```bash
pip install -r requirements.txt
playwright install chromium
```