# 🤖 QQ群成员验证插件

<div align="center">

![Version](https://img.shields.io/badge/version-1.2.1-blue.svg)  
![License](https://img.shields.io/badge/license-MIT-green.svg)  
![Platform](https://img.shields.io/badge/platform-AstrBot-purple.svg)

*一个简单高效的QQ群验证工具，保护您的群聊免受广告机器人和不良用户的侵扰*

[功能简介](#✨-功能简介) •  
[安装方法](#📥-安装方法) •  
[配置说明](#⚙️-配置说明) •  
[使用教程](#📝-使用教程) •  
[常见问题](#❓-常见问题) •  
[更新日志](#📋-更新日志)

</div>

---

## ✨ 功能简介

QQ群成员验证插件为 AstrBot 提供了强大的新成员管理功能，能有效过滤可疑用户，提升群聊质量。

- 🔍 **自动监测** - 实时检测新成员入群并立即发送验证提示  
- 🔑 **关键词验证** - 用户需要 @机器人 并回复指定关键词完成验证  
- ⏱️ **超时踢出** - 未在规定时间内完成验证的用户将被自动移出群聊  
- 🎨 **高度自定义** - 所有提示消息和时间设置均可根据需求调整
- 
- 🔄 **变量支持** - 提示信息支持动态变量，使消息更加个性化  

## 📥 安装方法

<details>
<summary>展开查看详细安装步骤</summary>

1. 进入 AstrBot 的插件管理界面  
2. 搜索 `astrbot_plugin_Group-Verification` 进行安装  
3. 配置插件选项（关键词、超时等）  
4. 保存并重启机器人或手动解压 release 包放入插件目录  
5. 配置 `_conf_schema.json` 以启用特定功能，如群聊限制  

</details>

## ⚙️ 配置说明

### 基础配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `verification_word` | string | 关键词验证内容 |
| `verification_timeout` | int | 验证超时时间（秒） |
| `kick_delay` | int | 发送失败提示后延迟踢出时间（秒） |
| `welcome_message` | string | 验证成功提示语 |
| `failure_message` | string | 验证失败提示语，支持 `{countdown}` 变量 |
| `kick_message` | string | 踢出消息模板，支持 `{member_name}` 变量 |
| `join_prompt` | string | 新人提示语模板，支持 `{member_name}` `{timeout}` `{verification_word}` |

### 支持的模板变量

- `{member_name}` - 用户昵称或QQ号  
- `{timeout}` - 验证超时（分钟）  
- `{countdown}` - 踢出倒计时（秒）  
- `{verification_word}` - 验证关键词内容  

## 📝 使用教程

<table>
  <tr>
    <td width="50%">
      <h3>1️⃣ 启用插件</h3>
      <p>在 AstrBot 插件页中启用本插件，确认已安装并配置完成。</p>
    </td>
    <td width="50%">
      <h3>2️⃣ 验证流程</h3>
      <p>新成员入群后将收到提示，需在指定时间内@机器人并发送验证词。</p>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>3️⃣ 成功通过</h3>
      <p>用户验证成功后将收到欢迎消息，可正常参与群聊。</p>
    </td>
    <td width="50%">
      <h3>4️⃣ 未验证处理</h3>
      <p>验证超时的用户将收到警告并在延迟后被自动踢出。</p>
    </td>
  </tr>
</table>

## ❓ 常见问题

<details>
<summary><b>机器人未响应新成员？</b></summary>
<p>请确认机器人是否为管理员，并检查 AstrBot 的事件通知权限设置。</p>
</details>

<details>
<summary><b>设置了验证词但无法识别？</b></summary>
<p>请确保用户消息中包含验证词，并正确 @ 机器人。</p>
</details>


## 📋 更新日志
### v1.2.1 (2025-08-06)
- ✍️ 修复： 修复了入群欢迎语和验证成功语中昵称重复的问题，并优化了消息模板的动态能力。
- 🔧 优化： 统一了消息处理逻辑，让插件能够更灵活地配置和生成包含 @ 用户的消息。
- 📦 增强： 提高了插件的健壮性，确保了消息模板和 @ 占位符能被正确解析和使用。
### v1.2.0 (2025-08-06)
- ✍️ 修复： 修复了多项配置未生效的问题，包括 join_prompt 硬编码和 failure_message 占位符未替换。
- 🔧 优化： 将获取用户昵称的逻辑前置，减少 API 调用次数，并增加了 API 调用的容错处理。
- 📦 增强： 统一了代码与配置文件的默认值，使插件行为与

### v1.1.1 (2025-06-19)
-  ✍️ 新增对成员退群的处理（防止资源浪费）
- 🔧 新增对成员主动离开或被踢出群聊，系统会自动清理其验证状态并取消超时任务


### v1.0.4 (2025-06-01)
-  ✍️ 修复退群后无通知的错误
- 🔧 优化逻辑结构，统一用户 ID 和群号处理
- 🧹 清理冗余任务与状态数据
- 📦 文档更新，增强使用说明

### v1.0.2 (2025-04-22)
- ✨ 修复部分 bug  
- 📝 提升代码可读性  

### v1.0.1 (2025-04-21)
- 🐛 修复验证关键词匹配逻辑  
- ✨ 增加用户ID类型兼容处理  
- 📝 完善日志记录  

### v1.0.0 (2025-04-20)
- 🚀 插件首次发布  
- ✅ 基础验证功能实现  
- 🔧 可配置验证关键词和超时时间  

---

### 插件作者: huotuo146

- 🌐 [GitHub](https://github.com/huntuo146)  
- 📧 Email: [2996603469@qq.com]  
- 🔗 项目地址: [astrbot_plugin_Group-Verification](https://github.com/huntuo146/astrbot_plugin_Group-Verification)

## 📜 许可证

本项目采用 [MIT 许可证](LICENSE) 进行开源。

---

<div align="center">
<p>如果您觉得这个插件有用，请考虑给项目一个 ⭐Star！</p>
<p>有问题或建议？欢迎 <a href="https://github.com/huntuo146/astrbot_plugin_Group-Verification/issues/new">提交 Issue</a></p>
<sub>Made with ❤️ by huotuo146</sub>
</div>
