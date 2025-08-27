# 🤖 QQ群GitHub Star验证插件

<div align="center">

![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-AstrBot-purple.svg)

*基于GitHub Star的QQ群验证插件，只允许Star过指定仓库的用户加入群聊*

[功能简介](#✨-功能简介) •
[快速开始](#�-快速开始) •
[安装配置](#📥-安装配置) •
[使用说明](#📝-使用说明) •
[技术特性](#🔧-技术特性) •
[常见问题](#❓-常见问题) •
[更新日志](#📋-更新日志)

</div>

---

## ✨ 功能简介

这是一个专为AstrBot设计的GitHub Star验证插件，通过验证新成员是否Star过指定的GitHub仓库来控制群成员准入。

### 核心功能
- ⭐ **GitHub Star验证** - 新成员必须Star指定仓库才能留在群内
- 🔗 **账号绑定防护** - 防止同一GitHub账号被多个QQ号绑定
- 🤖 **自动化流程** - 入群即验证，无需人工干预
- 💾 **本地数据库** - 使用SQLite存储Star用户数据，支持离线验证
- ⚡ **异步架构** - 基于aiosqlite和httpx，高性能异步处理
- 🎨 **高度自定义** - 所有消息模板和时间参数可自由配置

## 🚀 快速开始

### 1. 获取GitHub Token
1. 访问 [GitHub Settings > Personal Access Tokens](https://github.com/settings/tokens)
2. 点击 "Generate new token (classic)"
3. 设置token名称，选择 `public_repo` 权限
4. 生成并复制token（格式：`ghp_xxxxxxxxxxxxxxxxxxxx`）

### 2. 配置插件
在AstrBot插件配置中设置：
```json
{
  "github_token": "你的GitHub Token",
  "github_repo": "owner/repo",
  "verification_timeout": 300,
  "kick_delay": 60
}
```

### 3. 验证流程示例
```
[新用户加入群聊]

🤖 机器人：
欢迎 @新用户 加入本群！
请在 5 分钟内 @我 并回复你的GitHub用户名来完成验证。
格式：@机器人 GitHub用户名
只有Star过 SilianZ/astrbot 的用户才能留在群里。

👤 用户：@机器人 octocat

🤖 机器人：@用户 GitHub验证成功！欢迎Star过 SilianZ/astrbot 的开发者加入！
```

## �📥 安装配置

### 安装插件

### 安装插件

<details>
<summary>展开查看安装步骤</summary>

1. 进入 AstrBot 的插件管理界面  
2. 搜索 `astrbot_plugin_Group-Verification` 进行安装  
3. 配置插件选项（关键词、超时等）  
4. 保存并重启机器人或手动解压 release 包放入插件目录  
5. 配置 `_conf_schema.json` 以启用特定功能，如群聊限制  

</details>

## ⚙️ 配置说明

### 配置参数

| 配置项 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `github_token` | string | ✅ | GitHub个人访问令牌 |
| `github_repo` | string | ✅ | 目标仓库（格式：owner/repo） |
| `verification_timeout` | int | ❌ | 验证超时时间（秒，默认300） |
| `kick_delay` | int | ❌ | 踢出延迟时间（秒，默认60） |

### 消息模板配置

所有消息模板都支持变量替换：

```json
{
  "join_prompt": "欢迎 {member_name} 加入本群！\n请在 {timeout} 分钟内 @我 并回复你的GitHub用户名来完成验证。\n格式：@机器人 GitHub用户名\n只有Star过 {repo} 的用户才能留在群里。",
  "welcome_message": "{at_user} GitHub验证成功！欢迎Star过 {repo} 的开发者加入！",
  "failure_message": "{at_user} 验证超时，你将在 {countdown} 秒后被移出群聊。",
  "kick_message": "{member_name} 因未完成GitHub验证已被移出群聊。",
  "not_star_message": "{at_user} 验证失败：你没有Star过 {repo} 或GitHub用户名不存在。",
  "already_bound_message": "{at_user} 验证失败：该GitHub用户名已被其他QQ号绑定。",
  "invalid_github_message": "{at_user} 验证失败：请提供有效的GitHub用户名。格式：@机器人 GitHub用户名"
}
```

### 支持的变量

- `{member_name}` - 新成员@标记
- `{at_user}` - 用户@标记
- `{timeout}` - 超时时间（分钟）
- `{repo}` - GitHub仓库名
- `{countdown}` - 倒计时秒数

## 📝 使用说明

### 验证流程

1. **新成员入群** → 系统自动检测
2. **发送验证提示** → 机器人@新成员并说明验证要求
3. **用户回复GitHub用户名** → 格式：`@机器人 GitHub用户名`
4. **系统验证**：
   - 检查用户是否Star了指定仓库
   - 检查GitHub用户名是否已被其他QQ绑定
   - 检查用户名格式是否有效
5. **验证结果**：
   - ✅ 成功：绑定账号，发送欢迎消息
   - ❌ 失败：发送错误提示，超时后踢出群聊

### 错误处理

| 错误类型 | 系统响应 |
|----------|----------|
| 未Star仓库 | 提示用户先Star仓库 |
| GitHub用户名不存在 | 提示用户检查用户名 |
| 用户名已被绑定 | 提示联系管理员 |
| 格式错误 | 提示正确的输入格式 |
| 验证超时 | 发送警告并延迟踢出 |


## ❓ 常见问题

<details>
<summary><b>❓ 如何获取GitHub Token？</b></summary>
<p>
1. 访问 <a href="https://github.com/settings/personal-access-tokens">GitHub Personal Access Tokens</a><br>
2. 点击 "Generate new token"<br>
3. 设置仓库权限，选择 All repositories 或者 Only select repositories<br>
4. 添加权限 Metadata
5. 生成并保存token（格式：ghp_xxxxxxxxxxxxxxxxxxxx）
</p>
</details>

<details>
<summary><b>❓ 机器人没有响应新成员入群？</b></summary>
<p>
请检查：<br>
• 机器人是否为群管理员<br>
• 检查 AstrBot 的事件通知权限<br>
• 插件是否正确加载（查看日志）<br>
• GitHub Token和仓库配置是否正确
</p>
</details>

<details>
<summary><b>❓ 提示"验证失败：你没有Star过仓库"？</b></summary>
<p>
可能原因：<br>
• 用户确实没有Star指定仓库<br>
• GitHub Token权限不足<br>
• 仓库名称格式错误（应为：owner/repo）<br>
• GitHub API限制或网络问题
</p>
</details>

<details>
<summary><b>❓ 提示"该GitHub用户名已被其他QQ号绑定"？</b></summary>
<p>
说明该GitHub账号已被其他QQ号验证过。如需重新绑定：<br>
• 联系管理员手动解绑<br>
• 或使用其他GitHub账号验证
</p>
</details>

<details>
<summary><b>❓ GitHub API请求失败怎么办？</b></summary>
<p>
检查以下事项：<br>
• GitHub Token是否有效且未过期<br>
• 网络是否能访问GitHub API<br>
• 是否触发了API速率限制<br>
• 仓库是否存在且为公开仓库
</p>
</details>

## 📋 更新日志

### v2.0.0 (2025-08-28) 🌟
- ✨ **重大重构**：完全移除关键词验证，专注GitHub Star验证
- � **异步架构**：全面迁移到aiosqlite异步数据库操作
- � **简化流程**：用户只需@机器人并回复GitHub用户名即可
- � **优化存储**：改进数据库结构和查询性能
- 🛡️ **增强安全**：完善的输入验证和错误处理
- � **文档完善**：全新的使用文档和快速开始指南
- � **代码重构**：模块化设计，提高可维护性

### v1.2.1 (2025-08-06)
- ✍️ 修复：修复了入群欢迎语和验证成功语中昵称重复的问题
- 🔧 优化：统一了消息处理逻辑，提高消息模板的灵活性
- 📦 增强：提高了插件的健壮性和配置解析能力
### v1.2.0 (2025-08-06)
- ✍️ 修复：修复了多项配置未生效的问题
- 🔧 优化：减少API调用次数，增加容错处理
- 📦 增强：统一了代码与配置文件的默认值

### v1.1.1 (2025-06-19)
- ✍️ 新增：对成员退群的处理（防止资源浪费）
- 🔧 优化：自动清理验证状态并取消超时任务

### v1.0.4 (2025-06-01)
- ✍️ 修复：退群后无通知的错误
- 🔧 优化：逻辑结构，统一用户ID和群号处理
- 🧹 清理：冗余任务与状态数据

### v1.0.2 (2025-04-22)
- ✨ 修复：部分bug
- 📝 提升：代码可读性

### v1.0.1 (2025-04-21)
- 🐛 修复：验证关键词匹配逻辑
- ✨ 增加：用户ID类型兼容处理
- 📝 完善：日志记录

### v1.0.0 (2025-04-20)
- 🚀 插件首次发布
- ✅ 基础验证功能实现
- 🔧 可配置验证关键词和超时时间

---

## 👥 贡献者

<div align="center">

### 插件重构者：Qian23333

[![GitHub](https://img.shields.io/badge/GitHub-Qian23333-yellow?logo=github)](https://github.com/Qian23333)


### 原插件作者：huotuo146

[![GitHub](https://img.shields.io/badge/GitHub-huotuo146-blue?logo=github)](https://github.com/huntuo146)
[![Email](https://img.shields.io/badge/Email-2996603469@qq.com-red?logo=gmail)](mailto:2996603469@qq.com)


</div>


本项目采用 [MIT 许可证](LICENSE) 进行开源
