<div align="center">

# Bangumi 搜索插件使用指南
[![repo](https://img.shields.io/badge/repo-v1.2-blue.svg)](https://github.com/united-pooh/astrbot_plugin_bangumi)
[![License](https://img.shields.io/badge/license-Apacha2.0-green.svg)](LICENSE-2.0)
[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.0.0-orange.svg)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

**和 AI 一起追番**

</div>

> [!NOTE]  
> 本项目在[astrbot_plugin_bangumi](https://github.com/Amatsutsumi/astrbot_plugin_bangumi) 的基础上进行二次开发

## 
`/bgm角色搜索 关键词`

### 角色模糊搜索

- 通过名称模糊匹配条目
- 示例：`/bgm角色搜索 鹿岛理理` 

### 角色精准搜索
`/bgm角色 ID`

- 通过ID准确匹配条目
- 示例：`/bgm角色 36904` 

### 人物模糊搜索
`/bgm人物搜索 关键词`

- 通过名称模糊匹配条目
- 示例：`/bgm人物搜索 片冈智` 

### 人物精准搜索
`/bgm人物 ID`

- 通过ID准确匹配条目
- 示例：`/bgm人物 5756` 

### 用户搜索
`/bgm用户 ID`

- 通过用户名准确匹配用户
- 示例：`/bgm用户 aurora5454` 

## 📌 基本命令

### 精确搜索
`/bgm搜索 关键词或ID`

- 通过名称或ID精确匹配条目
- 显示完整信息（评分/简介/封面等）
- 示例：`/bgm搜索 进击的巨人` 或 `/bgm搜索 123456`

### 模糊搜索
`/bgm模糊 关键词`

- 显示自定义数量的相关结果
- 快速查找不确定名称的条目
- 示例：`/bgm模糊 命运`

### access_token获取

注册bangumi账号，点击[个人令牌](https://next.bgm.tv/demo/access-token/create)，创建token

## 🛠️ 配置参数

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| access_token | string | 无 | Bangumi API密钥（必填） |
| max_fuzzy_results | int | 5 | 模糊搜索最大结果数 |
| use_forward | bool | false | 是否使用转发消息样式 |
| if_fromfilesystem | bool | false | 是否从本地加载图片 |
