# 熬夜大王

每天按当地日出时间，在各群公布当天凌晨最后一位发消息的群友。例如：

> 🌅 小明是今天的熬夜大王！恭喜！
>
> 祝熬夜大王身体健康，今天记得好好补觉！

## 安装

在 AstrBot 管理面板打开「插件」，选择从仓库链接安装，粘贴以下地址：

```text
https://github.com/P9pijiu987/astrbot_plugin_night_owl
```

适用于 AstrBot 4.9.2 至 4.x。消息适配器需要接收普通群消息并支持主动群发，例如 OneBot v11（aiocqhttp）或 Telegram。Telegram 如只转发命令，需要调整机器人群隐私设置，让 AstrBot 能收到普通群消息。QQ 官方机器人接口无法通过此插件主动发榜。

## 配置

默认使用台北。发榜时间和凌晨的起点都以配置时区为准，和 AstrBot 主机的时区无关。要换城市，请在插件配置里一并修改时区、纬度和经度。

| 配置项 | 默认值 | 用途 |
| --- | --- | --- |
| `timezone` | `Asia/Taipei` | 日出所属日期和午夜起点使用的 IANA 时区 |
| `latitude` | `25.033` | 地点纬度，北纬为正 |
| `longitude` | `121.5654` | 地点经度，东经为正 |

## 评选规则

- 从当地 **00:00（含）到当天日出（不含）**，每群独立记录插件收到的消息。图片和表情也计入，排除私聊与 AstrBot 自己发出的消息。同一秒收到多条时，以后收到的为准。
- 日出时每群自动发一条公告。当天没有日出，或群里没有符合条件的消息时，就跳过。
- 只在 AstrBot 的 `data/plugin_data/astrbot_plugin_night_owl` 保存每群最新候选、时间、发榜会话和发送状态，不保存消息正文或回查历史。当天日出后恢复运行时，会补发仍未公布的结果。

实现参考 [AstrBot 消息事件](https://docs.astrbot.app/dev/star/guides/listen-message-event.html)、[主动发送消息](https://docs.astrbot.app/dev/star/guides/send-message.html) 和 [Astral 日出计算](https://astral.readthedocs.io/en/latest/package.html#astral.sun.sunrise)。
