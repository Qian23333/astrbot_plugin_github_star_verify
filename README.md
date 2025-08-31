# 🤖 QQ群GitHub Star验证插件

<div align="center">

*基于GitHub Star的QQ群验证插件，支持多群组配置不同仓库，只允许Star过指定仓库的用户加入群聊*

[功能简介](#功能简介) •
[快速开始](#快速开始) •
[WebUI 配置](#webui-配置) •
[使用说明](#使用说明) •
[常见问题](#常见问题) •
[最小配置契约](#最小配置契约)

</div>

---

## 功能简介

这是一个专为AstrBot设计的GitHub Star验证插件，通过验证新成员是否Star过指定的GitHub仓库来控制群成员准入。

### 核心功能
- ⭐ **GitHub Star验证** - 新成员必须Star指定仓库才能留在群内
- 🏢 **多群组支持** - 不同QQ群可配置不同GitHub仓库进行验证
- 🔗 **账号绑定防护** - 防止同一GitHub账号被多个QQ号绑定到同一仓库
- 🤖 **自动化流程** - 入群即验证，无需人工干预
- 💾 **本地数据库** - 使用SQLite存储Star用户数据，支持离线验证
- ⚡ **异步架构** - 基于aiosqlite和httpx，高性能异步处理
- 🎨 **高度自定义** - 所有消息模板和时间参数可自由配置

## 快速开始

### 1. 获取GitHub Token
1. 访问 [GitHub Settings > Developer Settings > Personal Access Tokens > Fine-grained personal access tokens](https://github.com/settings/personal-access-tokens)
2. 点击 "Generate new token"
3. 设置名称，选择 `All repositories` 或者 `Only select repositories` 权限
4. 添加 Permission 必须包含 Metadata
5. 生成并复制token

注意：部分组织或仓库对个人访问令牌（PAT）有策略限制，例如要求使用 Fine-grained token、限制有效期（可能不接受超过 1 年的长期 token），或需要组织管理员批准。请根据目标仓库/组织的访问策略生成 token。

### 2. 验证流程示例
```
[新用户加入群聊]

🤖 机器人：
欢迎 @新用户 加入本群！
请在 5 分钟内 @我 并回复你的GitHub用户名来完成验证。
格式：@机器人 GitHub用户名
只有Star过 AstrBotDevs/AstrBot 的用户才能留在群里。

👤 用户：@机器人 octocat

🤖 机器人：@用户 GitHub验证成功！欢迎加入本群！
```

## WebUI 配置
下列项在仪表盘配置页面中逐项填写：

- GitHub API Token（必需） — `github_token`（string）
  - 说明：用于调用 GitHub API。请使用 GitHub 的 [Fine-grained personal access token](https://github.com/settings/personal-access-tokens)生成。
  - 权限：选择 All repositories 或 Only select repositories，并确保包含 Metadata 权限（用于获取用户/仓库信息）。
  - 安全：请妥善保管 token，不要在公共仓库或截图中泄露；注意部分组织/仓库对 token 有策略或有效期限制（例如不接受长期 token 或需组织批准），生成前请检查目标仓库/组织的访问策略。

- 默认 GitHub 仓库（可选） — `github_repo`（string）
  - 说明：默认要验证 Star 的仓库，格式 `owner/repo`。当群未在 `group_repo_map` 中配置时使用此值。

- 群组仓库映射 — `group_repo_map`（list / 多行文本）
  - 说明：按群号映射不同仓库，每行一条。格式示例：`123456789:owner/repo`。

- 验证超时时间（秒） — `verification_timeout`（int）
  - 默认：300

- 踢出延迟时间（秒） — `kick_delay`（int）
  - 默认：60

- 消息模板（可自定义）
  - `join_prompt`：入群提示，变量：`{member_name}`, `{timeout}`, `{repo}`
  - `welcome_message`：验证成功消息，变量：`{at_user}`, `{repo}`
  - `failure_message`：超时警告，变量：`{at_user}`, `{countdown}`
  - 其他：`kick_message`, `not_star_message`, `already_bound_message`, `invalid_github_message`

配置字段表（在 WebUI 中填写）

| 字段（键） | WebUI 标签 | 类型 | 必需 | 说明 | 示例 |
|---|---|---:|:---:|---|---|
| github_token | GitHub API Token | string | 是 | 用于调用 GitHub API 的个人访问令牌（生成地址见提示） | ghp_xxxxxxxxxxxxx |
| github_repo | 默认 GitHub 仓库 | string | 否 | 默认仓库，格式 `owner/repo`，当群未在 `group_repo_map` 配置时使用 | AstrBotDevs/AstrBot |
| group_repo_map | 群组仓库映射 | list / 多行文本 | 否 | 每行或条目一个映射：`群号:owner/repo`（UI 也可能以可编辑条目形式展示） | 123456789:AstrBotDevs/AstrBot |
| verification_timeout | 验证超时时间（秒） | int | 否 | 用户必须在此时间内完成验证，默认 300（5 分钟） | 300 |
| kick_delay | 踢出延迟时间（秒） | int | 否 | 验证超时警告后等待多久执行踢出操作，默认 60 | 60 |
| join_prompt | 入群验证提示语 | string | 否 | 入群提示模板，支持变量：{member_name}, {timeout}, {repo} | 欢迎 {member_name} 加入本群！请在 {timeout} 分钟内 @我 并回复你的GitHub用户名。 |
| welcome_message | 验证成功消息 | string | 否 | 成功后发送的欢迎消息，支持变量：{at_user}, {repo} | {at_user} GitHub验证成功！欢迎加入本群！ |
| failure_message | 验证超时警告 | string | 否 | 验证超时时的警告，支持变量：{at_user}, {countdown} | {at_user} 验证超时，你将在 {countdown} 秒后被移出群聊。 |
| kick_message | 踢出通知 | string | 否 | 用户被踢出后的通知消息 | {member_name} 因未完成验证被移出 |
| not_star_message | 未 Star 提示 | string | 否 | 用户未 Star 指定仓库或用户名不存在的提示 | {at_user} 未 Star {repo} |
| already_bound_message | 已绑定提示 | string | 否 | GitHub 用户名已被其他 QQ 绑定时的提示 | {at_user} 已被其他 QQ 绑定 |
| invalid_github_message | 无效格式提示 | string | 否 | 用户输入格式错误时的提示 | {at_user} 请提供有效的 GitHub 用户名 |

在 WebUI 中填写这些字段并保存即可，保存后重载插件或重启 AstrBot 以使配置生效。

## 使用说明
1. 新成员入群，机器人发送验证提示 `join_prompt`。
2. 成员 @ 机器人 并回复 GitHub 用户名（格式要求见 `join_prompt`）。
3. 系统检查是否已 Star 并完成绑定，成功则发送 `welcome_message`，超时未验证则在 `kick_delay` 后踢出。

### 常用命令
```
/github bind <用户名>    # 绑定 GitHub 用户到当前群组仓库
/github unbind           # 解绑当前群组仓库的绑定
/github mystatus         # 查看自己的绑定状态
/github help             # 显示帮助

# 管理员
/github sync [仓库]      # 同步 Star 用户数据（不带参数为同步全部仓库）
/github status           # 查看插件状态
```

关键说明：
- 只能绑定已对目标仓库 Star 的 GitHub 用户；若用户不在本地数据库，请管理员使用 `/github sync` 同步。
- 每个 QQ 号在每个仓库只能绑定一个 GitHub 用户；每个 GitHub 用户在每个仓库只能被一个 QQ 号绑定。

常见失败原因（简短）：用户名格式错误 / 用户未 Star / 用户已被他人绑定 / GitHub Token 或网络问题。

## 常见问题
- Token 无效或权限不足：确认 token 未过期且有仓库访问权限。
- 仓库格式错误：应为 `owner/repo`，且仓库为公开仓库。
- 映射格式：`group_repo_map` 可为每行 `群号:owner/repo` 或 JSON 对象，确保群号与实际 QQ 群号一致。
- 插件未响应：确认 AstrBot 收到入群事件（机器人是否为管理员、事件权限），检查插件日志。
- 配置未生效：重载插件或重启 AstrBot。

## 最小配置契约
- 输入：`github_token`（string），`github_repo` 或 `group_repo_map`（string/object）
- 输出：验证通过/失败的消息和（在超时场景）踢出动作
