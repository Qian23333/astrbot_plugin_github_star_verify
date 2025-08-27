from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import asyncio
import re
from typing import Dict, Any
from .github_manager import GitHubStarManager


@register(
    "qq_github_star_verify",
    "Qian23333",
    "QQ群GitHub Star验证插件",
    "2.0.0",
    "https://github.com/Qian23333/astrbot_plugin_group_verification_github_star",
)
class QQGitHubStarVerifyPlugin(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.context = context

        # GitHub验证配置
        self.github_token = config.get("github_token", "")
        self.github_repo = config.get("github_repo", "")
        self.verification_timeout = config.get("verification_timeout", 300)
        self.kick_delay = config.get("kick_delay", 60)

        # 消息模板
        self.join_prompt = config.get(
            "join_prompt",
            "欢迎 {member_name} 加入本群！\n请在 {timeout} 分钟内 @我 并回复你的GitHub用户名来完成验证。\n格式：@机器人 GitHub用户名\n只有Star过 {repo} 的用户才能留在群里。",
        )
        self.welcome_message = config.get(
            "welcome_message",
            "{at_user} GitHub验证成功！欢迎Star过 {repo} 的开发者加入！",
        )
        self.failure_message = config.get(
            "failure_message", "{at_user} 验证超时，你将在 {countdown} 秒后被移出群聊。"
        )
        self.kick_message = config.get(
            "kick_message", "{member_name} 因未完成GitHub验证已被移出群聊。"
        )
        self.not_star_message = config.get(
            "not_star_message",
            "{at_user} 验证失败：你没有Star过 {repo} 或GitHub用户名不存在。",
        )
        self.already_bound_message = config.get(
            "already_bound_message",
            "{at_user} 验证失败：该GitHub用户名已被其他QQ号绑定。",
        )
        self.invalid_github_message = config.get(
            "invalid_github_message",
            "{at_user} 验证失败：请提供有效的GitHub用户名。格式：@机器人 GitHub用户名",
        )

        # 状态管理
        self.pending: Dict[str, int] = {}  # user_id -> group_id
        self.timeout_tasks: Dict[str, asyncio.Task] = {}

        # GitHub管理器
        self.github_manager = None

        # 验证必要配置
        if not self.github_token or not self.github_repo:
            logger.error(
                "[GitHub Verify] 缺少GitHub配置，请检查github_token和github_repo配置"
            )

    async def _ensure_github_manager(self):
        """确保GitHub管理器已初始化"""
        if self.github_manager is None:
            if not self.github_token or not self.github_repo:
                logger.error(
                    "[GitHub Verify] GitHub配置不完整，无法初始化GitHubStarManager"
                )
                return False

            self.github_manager = GitHubStarManager(
                github_token=self.github_token, github_repo=self.github_repo
            )

            # 初始化数据库
            await self.github_manager.init_database()

            # 检查数据库是否为空，记录状态但不自动同步
            stars_count = await self.github_manager.get_stars_count()
            if stars_count == 0:
                logger.info(
                    f"[GitHub Verify] 检测到数据库为空，请使用 /github sync 命令同步 {self.github_repo} 的Star用户"
                )
            else:
                logger.info(
                    f"[GitHub Verify] GitHub管理器已初始化，仓库: {self.github_repo}，数据库中有 {stars_count} 个Star用户"
                )

        return True

    async def sync_stargazers(self):
        """同步GitHub Star用户到数据库"""
        if not await self._ensure_github_manager():
            return False

        try:
            logger.info("[GitHub Verify] 开始获取GitHub Star用户...")
            stargazers = await self.github_manager.fetch_stargazers()

            if stargazers:
                logger.info(
                    f"[GitHub Verify] 成功获取 {len(stargazers)} 个Star用户，开始同步到数据库..."
                )
                await self.github_manager.sync_stargazers(stargazers)
                return True
            else:
                logger.info(
                    f"[GitHub Verify] 仓库 {self.github_repo} 当前没有Star用户，数据库已初始化"
                )
                # 即使没有Star用户，也算作成功的同步操作
                return True
        except Exception as e:
            logger.error(f"[GitHub Verify] 同步Star用户失败: {e}")
            return False

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def handle_event(self, event: AstrMessageEvent):
        if event.get_platform_name() != "aiocqhttp":
            return

        raw = event.message_obj.raw_message
        post_type = raw.get("post_type")

        if post_type == "notice":
            notice_type = raw.get("notice_type")
            if notice_type == "group_increase":
                await self._process_new_member(event)
            elif notice_type == "group_decrease":
                await self._process_member_decrease(event)

        elif post_type == "message" and raw.get("message_type") == "group":
            await self._process_verification_message(event)

    async def _process_new_member(self, event: AstrMessageEvent):
        """处理新成员入群的逻辑"""
        if not await self._ensure_github_manager():
            return

        raw = event.message_obj.raw_message
        uid = str(raw.get("user_id"))
        gid = raw.get("group_id")

        # 检查是否已经验证过
        existing_github = await self.github_manager.is_qq_bound(uid)
        if existing_github:
            logger.info(
                f"[GitHub Verify] 用户 {uid} 已绑定GitHub用户 {existing_github}，跳过验证"
            )
            return

        # 清理旧的验证任务
        if uid in self.timeout_tasks:
            old_task = self.timeout_tasks.pop(uid, None)
            if old_task and not old_task.done():
                old_task.cancel()

        self.pending[uid] = gid
        logger.info(f"[GitHub Verify] 用户 {uid} 加入群 {gid}，启动GitHub验证流程")

        # 获取用户昵称
        nickname = uid
        try:
            user_info = await event.bot.api.call_action(
                "get_group_member_info", group_id=gid, user_id=int(uid)
            )
            nickname = user_info.get("card", "") or user_info.get("nickname", uid)
        except Exception as e:
            logger.warning(f"[GitHub Verify] 获取用户 {uid} 昵称失败: {e}")

        # 发送验证提示
        prompt_message = self.join_prompt.format(
            member_name=f"[CQ:at,qq={uid}]",
            timeout=self.verification_timeout // 60,
            repo=self.github_repo,
        )

        await event.bot.api.call_action(
            "send_group_msg", group_id=gid, message=prompt_message
        )

        # 创建超时任务
        task = asyncio.create_task(self._timeout_kick(uid, gid, nickname))
        self.timeout_tasks[uid] = task

    async def _process_verification_message(self, event: AstrMessageEvent):
        """处理群聊消息中的GitHub验证"""
        uid = str(event.get_sender_id())
        if uid not in self.pending:
            return

        if not await self._ensure_github_manager():
            return

        text = event.message_str.strip()
        raw = event.message_obj.raw_message
        gid = raw.get("group_id")

        # 检查是否@了机器人
        bot_id = str(event.get_self_id())
        at_me = any(
            seg.get("type") == "at" and str(seg.get("data", {}).get("qq")) == bot_id
            for seg in raw.get("message", [])
        )

        if not at_me:
            return

        # 提取GitHub用户名
        github_username = self._extract_github_username(text)
        if not github_username:
            await event.bot.api.call_action(
                "send_group_msg",
                group_id=gid,
                message=self.invalid_github_message.format(at_user=f"[CQ:at,qq={uid}]"),
            )
            return

        # 直接通过GitHub API验证用户是否Star了仓库
        is_star = await self.github_manager.check_user_starred_directly(github_username)
        if not is_star:
            await event.bot.api.call_action(
                "send_group_msg",
                group_id=gid,
                message=self.not_star_message.format(
                    at_user=f"[CQ:at,qq={uid}]", repo=self.github_repo
                ),
            )
            return

        # 检查GitHub用户名是否已被绑定
        is_bound = await self.github_manager.is_github_id_bound(github_username)
        if is_bound:
            await event.bot.api.call_action(
                "send_group_msg",
                group_id=gid,
                message=self.already_bound_message.format(at_user=f"[CQ:at,qq={uid}]"),
            )
            return

        # 绑定GitHub用户名和QQ
        bind_success = await self.github_manager.bind_github_qq(github_username, uid)
        if not bind_success:
            await event.bot.api.call_action(
                "send_group_msg", group_id=gid, message="绑定失败，请稍后重试。"
            )
            return

        # 验证成功，清理任务
        task = self.timeout_tasks.pop(uid, None)
        if task and not task.done():
            task.cancel()

        self.pending.pop(uid, None)

        # 发送欢迎消息
        welcome_msg = self.welcome_message.format(
            at_user=f"[CQ:at,qq={uid}]", repo=self.github_repo
        )

        await event.bot.api.call_action(
            "send_group_msg", group_id=gid, message=welcome_msg
        )

        logger.info(
            f"[GitHub Verify] 用户 {uid} 使用GitHub用户名 {github_username} 验证成功"
        )
        event.stop_event()

    def _extract_github_username(self, text: str) -> str:
        """从消息中提取GitHub用户名"""
        # 移除@机器人的部分
        text = re.sub(r"\[CQ:at,qq=\d+\]", "", text).strip()

        # 简单的GitHub用户名验证（字母数字下划线横线，不能以横线开头结尾）
        pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$"

        if re.match(pattern, text) and len(text) <= 39:  # GitHub用户名最长39字符
            return text

        return ""

    async def _process_member_decrease(self, event: AstrMessageEvent):
        """处理成员减少的逻辑"""
        raw = event.message_obj.raw_message
        uid = str(raw.get("user_id"))

        if uid in self.pending:
            self.pending.pop(uid, None)
            task = self.timeout_tasks.pop(uid, None)
            if task and not task.done():
                task.cancel()
            logger.info(f"[GitHub Verify] 待验证用户 {uid} 已离开群聊，清理验证状态")

    async def _timeout_kick(self, uid: str, gid: int, nickname: str):
        """超时后执行踢人操作"""
        try:
            await asyncio.sleep(self.verification_timeout)

            if uid not in self.pending:
                return

            bot = self.context.get_platform("aiocqhttp").get_client()

            try:
                # 发送超时警告
                failure_msg = self.failure_message.format(
                    at_user=f"[CQ:at,qq={uid}]", countdown=self.kick_delay
                )
                await bot.api.call_action(
                    "send_group_msg", group_id=gid, message=failure_msg
                )

                await asyncio.sleep(self.kick_delay)

                if uid not in self.pending:
                    return

                # 踢出用户
                await bot.api.call_action(
                    "set_group_kick",
                    group_id=gid,
                    user_id=int(uid),
                    reject_add_request=False,
                )
                logger.info(
                    f"[GitHub Verify] 用户 {uid} ({nickname}) GitHub验证超时，已从群 {gid} 踢出"
                )

                # 发送踢出消息
                kick_msg = self.kick_message.format(member_name=nickname)
                await bot.api.call_action(
                    "send_group_msg", group_id=gid, message=kick_msg
                )

            except Exception as e:
                logger.error(f"[GitHub Verify] 踢出用户 {uid} 时发生错误: {e}")

        except asyncio.CancelledError:
            logger.info(f"[GitHub Verify] 用户 {uid} 验证成功，踢出任务已取消")
        finally:
            self.pending.pop(uid, None)
            self.timeout_tasks.pop(uid, None)

    # GitHub 管理指令组
    @filter.command_group("github")
    @filter.permission_type(filter.PermissionType.ADMIN)
    def github_commands(self):
        """GitHub Star验证管理指令"""
        pass

    @github_commands.command("sync")
    async def sync_command(self, event: AstrMessageEvent):
        """同步GitHub Star用户数据"""
        yield event.plain_result("开始同步GitHub Star用户数据...")

        success = await self.sync_stargazers()
        if success:
            stars_count = await self.github_manager.get_stars_count()
            bound_count = await self.github_manager.get_bound_count()
            yield event.plain_result(
                f"同步完成！数据库中共有 {stars_count} 个Star用户，其中 {bound_count} 个已绑定QQ号。"
            )
        else:
            yield event.plain_result("同步失败，请检查日志。")

    @github_commands.command("status")
    async def status_command(self, event: AstrMessageEvent):
        """查看插件状态"""
        if not await self._ensure_github_manager():
            yield event.plain_result("GitHub管理器未初始化。")
            return

        stars_count = await self.github_manager.get_stars_count()
        bound_count = await self.github_manager.get_bound_count()
        pending_count = len(self.pending)

        status_msg = f"""GitHub Star验证插件状态：
📊 数据库中Star用户: {stars_count}
🔗 已绑定QQ号: {bound_count}
⏳ 等待验证: {pending_count}
📦 监控仓库: {self.github_repo}"""

        yield event.plain_result(status_msg)

    # 用户命令组
    @filter.command_group("github")
    def user_commands(self):
        """用户GitHub命令组"""
        pass

    @user_commands.command("bind")
    async def bind_github_command(self, event: AstrMessageEvent):
        """绑定GitHub ID"""
        if event.get_platform_name() != "aiocqhttp":
            return

        if not await self._ensure_github_manager():
            yield event.plain_result("GitHub管理器未初始化，请联系管理员。")
            return

        # 提取GitHub用户名
        args = event.message_str.strip().split()
        if len(args) < 3:
            yield event.plain_result(
                "请提供GitHub用户名。格式：/github bind <GitHub用户名>"
            )
            return

        github_username = args[2]
        uid = str(event.get_sender_id())

        # 验证GitHub用户名格式
        github_username = self._extract_github_username(github_username)
        if not github_username:
            yield event.plain_result("请提供有效的GitHub用户名。")
            return

        # 检查用户是否已经绑定了其他GitHub ID
        existing_github = await self.github_manager.is_qq_bound(uid)
        if existing_github:
            yield event.plain_result(
                f"你已经绑定了GitHub用户 {existing_github}，如需更换请使用 /github unbind 先解绑。"
            )
            return

        # 检查GitHub用户是否在数据库中（即是否为Star用户）
        is_star = await self.github_manager.is_stargazer(github_username)
        if not is_star:
            yield event.plain_result(
                f"用户 {github_username} 不在Star用户数据库中，无法绑定。请先确保已Star仓库 {self.github_repo}。"
            )
            return

        # 检查GitHub用户名是否已被其他人绑定
        is_bound = await self.github_manager.is_github_id_bound(github_username)
        if is_bound:
            yield event.plain_result(f"GitHub用户 {github_username} 已被其他QQ号绑定。")
            return

        # 执行绑定
        bind_success = await self.github_manager.bind_github_qq(github_username, uid)
        if bind_success:
            yield event.plain_result(f"✅ 成功绑定GitHub用户 {github_username}！")
        else:
            yield event.plain_result("❌ 绑定失败，请稍后重试。")

    @user_commands.command("unbind")
    async def unbind_github_command(self, event: AstrMessageEvent):
        """解绑GitHub ID"""
        if event.get_platform_name() != "aiocqhttp":
            return

        if not await self._ensure_github_manager():
            yield event.plain_result("GitHub管理器未初始化，请联系管理员。")
            return

        uid = str(event.get_sender_id())

        # 检查用户是否已经绑定
        existing_github = await self.github_manager.is_qq_bound(uid)
        if not existing_github:
            yield event.plain_result("你还没有绑定任何GitHub用户。")
            return

        # 执行解绑
        unbind_success = await self.github_manager.unbind_qq(uid)
        if unbind_success:
            yield event.plain_result(f"✅ 成功解绑GitHub用户 {existing_github}！")
        else:
            yield event.plain_result("❌ 解绑失败，请稍后重试。")

    @user_commands.command("mystatus")
    async def user_status_command(self, event: AstrMessageEvent):
        """查看自己的绑定状态"""
        if event.get_platform_name() != "aiocqhttp":
            return

        if not await self._ensure_github_manager():
            yield event.plain_result("GitHub管理器未初始化，请联系管理员。")
            return

        uid = str(event.get_sender_id())
        existing_github = await self.github_manager.is_qq_bound(uid)

        if existing_github:
            yield event.plain_result(f"🔗 你已绑定GitHub用户: {existing_github}")
        else:
            yield event.plain_result(
                "❌ 你还没有绑定任何GitHub用户。\n使用 /github bind <用户名> 进行绑定。"
            )

    @user_commands.command("help")
    async def user_help_command(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_msg = """GitHub用户命令：
/github bind <用户名> - 绑定GitHub用户名
/github unbind - 解绑当前绑定的GitHub用户
/github mystatus - 查看绑定状态
/github help - 显示帮助信息

管理员命令：
/github sync - 同步GitHub Star用户数据（仅管理员）
/github status - 查看插件状态（仅管理员）

注意：
- 只能绑定已经Star过仓库的GitHub用户
- 每个QQ号只能绑定一个GitHub用户
- 每个GitHub用户只能被一个QQ号绑定"""

        yield event.plain_result(help_msg)

    async def __aenter__(self):
        await self._ensure_github_manager()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.github_manager:
            await self.github_manager.close()
