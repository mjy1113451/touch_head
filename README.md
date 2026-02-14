# 摸头GIF生成器 (pat_head_gif)

一个 AstrBot 插件，用于自动回复"摸头"并生成摸头杀GIF。

## 功能

- 监听群聊和私聊消息中的"摸头"关键词
- 支持 @用户 生成定向摸头GIF
- 自动获取被@用户的QQ头像生成表情包
- **自动安装和启动 meme-generator API 服务**

## 安装

将插件目录放入 AstrBot 的 `addons/plugins/` 目录下，重启 AstrBot 或在管理面板重载插件。

插件会在首次加载时自动：
1. 检测是否安装了 `meme-generator`
2. 如未安装，自动执行 `pip install meme-generator`
3. 启动 meme-generator API 服务

## 配置

在 AstrBot 管理面板中配置以下参数：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_url` | meme-generator API地址 | `http://127.0.0.1:2233` |
| `api_port` | API服务端口 | `2233` |
| `auto_start_api` | 是否自动启动API服务 | `true` |

## 使用方法

发送包含"摸头"的消息并@目标用户：
```
摸头 @某人
```

## 工作流程

```
插件加载
    ↓
检测 meme-generator 是否已安装 → 未安装则自动 pip install
    ↓
检测 API 服务是否运行 → 未运行则自动启动
    ↓
用户发送: "摸头 @张三"
    ↓
插件提取张三的QQ号 → 获取QQ头像
    ↓
调用 meme-generator API → 生成摸头GIF
    ↓
发送表情包到群聊/私聊
```

## 依赖

- httpx>=0.24.0
- meme-generator（自动安装）

## 兼容性

- AstrBot 版本: v3.0+
- Python 版本: 3.10+
- 平台: QQ（通过 NapCat 等 OneBot 实现）

## 注意事项

1. 首次使用时，插件需要下载 meme-generator 的资源文件，可能需要等待一段时间
2. 如果自动启动失败，可以手动运行 `meme run` 命令启动 API 服务
3. Windows 系统可能需要安装 Visual C++ 运行时

## 支持

- [插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)
- [meme-generator 项目](https://github.com/MeetWq/meme-generator)
- [GitHub 仓库](https://github.com/mjy1113451/touch_head)
