from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
import asyncio
import re
from typing import Dict, Any, Optional
from .github_manager import MultiRepoGitHubStarManager


class GitHubStarVerifyPlugin(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.context = context

        # GitHub验证配置
        self.github_token = config.get("github_token", "")
        self.default_repo = config.get("github_repo", "")

        # 解析群组仓库映射配置
        group_repo_config = config.get("group_repo_map", [])
        self.group_repo_map = {}
        for mapping in group_repo_config:
            if isinstance(mapping, str) and ":" in mapping:
                parts = mapping.split(":", 1)
                if len(parts) == 2:
                    group_id = parts[0].strip()
                    repo = parts[1].strip()
                    if group_id and repo:
                        self.group_repo_map[group_id] = repo

        self.verification_timeout = config.get("verification_timeout", 300)
        self.kick_delay = config.get("kick_delay", 60)

        # 消息模板
        self.join_prompt = config.get(
            "join_prompt",
            "欢迎 {member_name} 加入本群！\n请在 {timeout} 分钟内 @我 并回复你的GitHub用户名来完成验证。\n格式：@机器人 GitHub用户名\n只有Star过 {repo} 的用户才能留在群里。",
        )
        self.welcome_message = config.get(
            "welcome_message",
            "{at_user} GitHub验证成功！欢迎加入本群！",
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
        self.pending: Dict[str, str] = {}  # user_id -> group_id
        self.timeout_tasks: Dict[str, asyncio.Task] = {}

        # GitHub管理器
        self.github_manager = None

        # 验证必要配置
        if not self.github_token:
            logger.error(
                "[GitHub Star Verify] 缺少GitHub token配置"
            )

    def get_repo_for_group(self, group_id: str) -> Optional[str]:
        """获取指定群组对应的仓库"""
        repo = self.group_repo_map.get(str(group_id))
        if repo:
            return repo
        elif self.default_repo:
            return self.default_repo
        else:
            # 如果没有配置默认仓库且群组也没有映射，返回 None 或抛出异常
            logger.error(f"[GitHub Star Verify] 群组 {group_id} 没有配置仓库映射且没有默认仓库")
            return None

    def _group_key(self, gid) -> str:
        """统一群组ID表示为字符串"""
        return str(gid)

    def _group_id_int(self, gid) -> int:
        """将群组ID转换为整数用于API调用"""
        return int(str(gid))

    async def _ensure_github_manager(self):
        """确保GitHub管理器已初始化"""
        if self.github_manager is None:
            # 验证配置：至少需要有 default_repo 或 group_repo_map 中的一个
            has_default = bool(self.default_repo)
            has_group_mapping = bool(self.group_repo_map)

            if not self.github_token:
                logger.error(
                    "[GitHub Star Verify] 缺少GitHub token配置"
                )
                return False

            if not has_default and not has_group_mapping:
                logger.error(
                    "[GitHub Star Verify] 需要配置 default_repo 或 group_repo_map 中的至少一个"
                )
                return False

            self.github_manager = MultiRepoGitHubStarManager(
                github_token=self.github_token,
                default_repo=self.default_repo,
                group_repo_map=self.group_repo_map,
            )

            # 初始化数据库
            await self.github_manager.init_database()

            # 检查默认仓库的数据库状态（如果配置了默认仓库）
            if has_default:
                stars_count = await self.github_manager.get_stars_count_for_repo(
                    self.default_repo
                )
                if stars_count == 0:
                    logger.info(
                        f"[GitHub Star Verify] 检测到默认仓库 {self.default_repo} 数据库为空，请使用 /github sync 命令同步Star用户"
                    )
                else:
                    logger.info(
                        f"[GitHub Star Verify] GitHub管理器已初始化，默认仓库: {self.default_repo}，数据库中有 {stars_count} 个Star用户"
                    )
            else:
                logger.info(
                    "[GitHub Star Verify] GitHub管理器已初始化，未配置默认仓库，仅使用群组仓库映射"
                )

            # 显示群组配置信息
            if self.group_repo_map:
                logger.info(f"[GitHub Star Verify] 群组仓库映射: {self.group_repo_map}")

        return True

    async def sync_stargazers(self, repo: str = None):
        """同步GitHub Star用户到数据库"""
        if not await self._ensure_github_manager():
            return False

        if repo:
            # 同步指定仓库
            return await self.github_manager.sync_stargazers_for_repo(repo)
        else:
            # 同步所有仓库
            results = await self.github_manager.sync_all_repos()
            return all(results.values())

    async def sync_all_repos(self):
        """同步所有配置的仓库"""
        if not await self._ensure_github_manager():
            return {}

        return await self.github_manager.sync_all_repos()

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
        gid = str(raw.get("group_id"))

        # 检查机器人是否为群管理员
        bot_id = str(event.get_self_id())
        try:
            bot_info = await event.bot.api.call_action(
                "get_group_member_info", group_id=int(gid), user_id=int(bot_id)
            )
            bot_role = bot_info.get("role", "member")
            if bot_role not in ["admin", "owner"]:
                logger.warning(
                    f"[GitHub Star Verify] 机器人在群 {gid} 不是管理员，无法发送验证消息和执行踢人操作"
                )
                return
        except Exception as e:
            logger.warning(f"[GitHub Star Verify] 获取机器人权限失败: {e}，跳过验证流程")
            return

        # 获取该群对应的仓库
        repo = self.get_repo_for_group(gid)
        if not repo:
            logger.warning(f"[GitHub Star Verify] 群组 {gid} 没有配置仓库，跳过验证")
            return

        # 检查是否已经验证过该仓库
        existing_github = await self.github_manager.is_qq_bound_to_repo(uid, repo)
        if existing_github:
            logger.info(
                f"[GitHub Star Verify] 用户 {uid} 已绑定GitHub用户 {existing_github} 到仓库 {repo}，跳过验证"
            )
            return

        # 清理旧的验证任务
        if uid in self.timeout_tasks:
            old_task = self.timeout_tasks.pop(uid, None)
            if old_task and not old_task.done():
                old_task.cancel()

        self.pending[uid] = self._group_key(gid)
        logger.info(
            f"[GitHub Star Verify] 用户 {uid} 加入群 {gid}，启动GitHub验证流程，目标仓库: {repo}"
        )

        # 获取用户昵称
        nickname = uid
        try:
            user_info = await event.bot.api.call_action(
                "get_group_member_info", group_id=int(gid), user_id=int(uid)
            )
            nickname = user_info.get("card", "") or user_info.get("nickname", uid)
        except Exception as e:
            logger.warning(f"[GitHub Star Verify] 获取用户 {uid} 昵称失败: {e}")

        # 发送验证提示
        prompt_message = self.join_prompt.format(
            member_name=f"[CQ:at,qq={uid}]",
            timeout=self.verification_timeout // 60,
            repo=repo,
        )

        await event.bot.api.call_action(
            "send_group_msg", group_id=int(gid), message=prompt_message
        )

        # 创建超时任务
        task = asyncio.create_task(self._timeout_kick(uid, int(gid), nickname, repo))
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
        gid = str(raw.get("group_id"))

        # 获取该群对应的仓库
        repo = self.get_repo_for_group(gid)
        if not repo:
            logger.warning(f"[GitHub Star Verify] 群组 {gid} 没有配置仓库，跳过验证消息处理")
            return

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
                group_id=int(gid),
                message=self.invalid_github_message.format(at_user=f"[CQ:at,qq={uid}]"),
            )
            return

        # 先用数据库快速判定，再调用GitHub API兜底验证
        is_star = await self.github_manager.is_stargazer(github_username, repo)
        if not is_star:
            is_star = await self.github_manager.check_user_starred_directly(
                github_username, repo
            )
            # 记录到数据库
            if is_star:
                await self.github_manager.record_stargazer(github_username, repo)
        if not is_star:
            await event.bot.api.call_action(
                "send_group_msg",
                group_id=int(gid),
                message=self.not_star_message.format(
                    at_user=f"[CQ:at,qq={uid}]", repo=repo
                ),
            )
            return

        # 检查GitHub用户名是否已被绑定到该仓库
        is_bound = await self.github_manager.is_github_id_bound_to_repo(
            github_username, repo
        )
        if is_bound:
            await event.bot.api.call_action(
                "send_group_msg",
                group_id=int(gid),
                message=self.already_bound_message.format(at_user=f"[CQ:at,qq={uid}]"),
            )
            return

        # 绑定GitHub用户名和QQ到指定仓库
        bind_success = await self.github_manager.bind_github_qq_to_repo(
            github_username, uid, repo
        )
        if not bind_success:
            await event.bot.api.call_action(
                "send_group_msg", group_id=int(gid), message="绑定失败，请稍后重试。"
            )
            return

        # 验证成功，清理任务
        task = self.timeout_tasks.pop(uid, None)
        if task and not task.done():
            task.cancel()

        self.pending.pop(uid, None)

        # 发送欢迎消息
        welcome_msg = self.welcome_message.format(
            at_user=f"[CQ:at,qq={uid}]", repo=repo
        )

        await event.bot.api.call_action(
            "send_group_msg", group_id=int(gid), message=welcome_msg
        )

        logger.info(
            f"[GitHub Star Verify] 用户 {uid} 使用GitHub用户名 {github_username} 验证成功，仓库: {repo}"
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
            logger.info(f"[GitHub Star Verify] 待验证用户 {uid} 已离开群聊，清理验证状态")

    async def _timeout_kick(self, uid: str, gid: int, nickname: str, repo: str):
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
                    f"[GitHub Star Verify] 用户 {uid} ({nickname}) GitHub验证超时，已从群 {gid} 踢出"
                )

                # 发送踢出消息
                kick_msg = self.kick_message.format(member_name=nickname)
                await bot.api.call_action(
                    "send_group_msg", group_id=gid, message=kick_msg
                )

            except Exception as e:
                logger.error(f"[GitHub Star Verify] 踢出用户 {uid} 时发生错误: {e}")

        except asyncio.CancelledError:
            logger.info(f"[GitHub Star Verify] 用户 {uid} 验证成功，踢出任务已取消")
        finally:
            self.pending.pop(uid, None)
            self.timeout_tasks.pop(uid, None)

    # GitHub 指令组
    @filter.command_group("github", alias={"gh"})
    def github_commands(self):
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @github_commands.command("sync")
    async def sync_command(self, event: AstrMessageEvent, repo: str = ""):
        """同步GitHub Star用户数据"""
        # 如果提供了 repo，则同步指定仓库
        if repo:
            yield event.plain_result(f"开始同步仓库 {repo} 的Star用户数据...")
            success = await self.sync_stargazers(repo)
            if success:
                stars_count = await self.github_manager.get_stars_count_for_repo(repo)
                bound_count = await self.github_manager.get_bound_count_for_repo(repo)
                yield event.plain_result(
                    f"同步完成！仓库 {repo} 数据库中共有 {stars_count} 个Star用户，其中 {bound_count} 个已绑定QQ号。"
                )
            else:
                yield event.plain_result(f"同步仓库 {repo} 失败，请检查日志。")
            return

        # 未提供 repo，则同步所有仓库
        yield event.plain_result("开始同步所有仓库的Star用户数据...")
        success = await self.sync_stargazers()
        if success:
            # 显示所有仓库的统计
            result_msg = "同步完成！各仓库统计：\n"

            # 默认仓库（如果配置了）
            if self.default_repo:
                default_stars = await self.github_manager.get_stars_count_for_repo(
                    self.default_repo
                )
                default_bound = await self.github_manager.get_bound_count_for_repo(
                    self.default_repo
                )
                result_msg += f"📦 {self.default_repo}: {default_stars} Star用户，{default_bound} 已绑定\n"

            # 群组配置的仓库
            unique_repos = set(self.group_repo_map.values())
            for repo in unique_repos:
                if repo and repo != self.default_repo:
                    stars = await self.github_manager.get_stars_count_for_repo(repo)
                    bound = await self.github_manager.get_bound_count_for_repo(repo)
                    result_msg += f"📦 {repo}: {stars} Star用户，{bound} 已绑定\n"

            yield event.plain_result(result_msg.strip())
        else:
            yield event.plain_result("同步失败，请检查日志。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @github_commands.command("status")
    async def status_command(self, event: AstrMessageEvent):
        """查看插件状态"""
        if not await self._ensure_github_manager():
            yield event.plain_result("GitHub管理器未初始化。")
            return

        pending_count = len(self.pending)

        # 获取当前群组信息
        group_id = event.get_group_id()
        if group_id:
            current_repo = self.get_repo_for_group(group_id)
        else:
            current_repo = self.default_repo or "未配置"

        status_msg = f"""GitHub Star验证插件状态：
📦 默认仓库: {self.default_repo or "未配置"}
🔗 群组仓库映射: {len(self.group_repo_map)} 个群组
⏳ 等待验证: {pending_count}
🎯 当前群组仓库: {current_repo}

仓库统计:"""

        # 默认仓库统计（如果配置了）
        if self.default_repo:
            default_stars = await self.github_manager.get_stars_count_for_repo(
                self.default_repo
            )
            default_bound = await self.github_manager.get_bound_count_for_repo(
                self.default_repo
            )
            status_msg += f"\n📊 {self.default_repo}: {default_stars} Star用户，{default_bound} 已绑定"

        # 群组配置的仓库统计
        unique_repos = set(self.group_repo_map.values())
        for repo in unique_repos:
            if repo and repo != self.default_repo:
                stars = await self.github_manager.get_stars_count_for_repo(repo)
                bound = await self.github_manager.get_bound_count_for_repo(repo)
                status_msg += f"\n📊 {repo}: {stars} Star用户，{bound} 已绑定"

        yield event.plain_result(status_msg)

    @github_commands.command("bind", alias={"绑定"})
    async def bind_github_command(self, event: AstrMessageEvent, github_username: str):
        """绑定GitHub ID"""
        if event.get_platform_name() != "aiocqhttp":
            return

        if not await self._ensure_github_manager():
            yield event.plain_result("GitHub管理器未初始化，请联系管理员。")
            return

        if not github_username:
            yield event.plain_result("请提供GitHub用户名。格式：/github [bind|绑定] <GitHub用户名>")
            return

        uid = str(event.get_sender_id())
        group_id = event.get_group_id()

        # 确定要绑定的仓库
        if group_id:
            repo = self.get_repo_for_group(group_id)
        else:
            repo = self.default_repo

        if not repo:
            yield event.plain_result("无法确定要绑定的仓库，请在配置了仓库映射的群组中使用此命令。")
            return

        # 验证GitHub用户名格式
        github_username = self._extract_github_username(github_username)
        if not github_username:
            yield event.plain_result("请提供有效的GitHub用户名。")
            return

        # 检查用户是否已经在当前仓库绑定了其他GitHub ID
        existing_github = await self.github_manager.is_qq_bound_to_repo(uid, repo)
        if existing_github:
            yield event.plain_result(
                f"你已经在仓库 {repo} 绑定了GitHub用户 {existing_github}，如需更换请使用 /github unbind 先解绑。"
            )
            return

        # 检查GitHub用户是否在数据库中（即是否为Star用户）
        is_star = await self.github_manager.is_stargazer(github_username, repo)
        if not is_star:
            yield event.plain_result(
                f"用户 {github_username} 不在仓库 {repo} 的Star用户数据库中，无法绑定。请先确保已Star该仓库。"
            )
            return

        # 检查GitHub用户名是否已被其他人在该仓库绑定
        is_bound = await self.github_manager.is_github_id_bound_to_repo(
            github_username, repo
        )
        if is_bound:
            yield event.plain_result(
                f"GitHub用户 {github_username} 已被其他QQ号在仓库 {repo} 绑定。"
            )
            return

        # 执行绑定
        bind_success = await self.github_manager.bind_github_qq_to_repo(
            github_username, uid, repo
        )
        if bind_success:
            yield event.plain_result(
                f"✅ 成功绑定GitHub用户 {github_username} 到仓库 {repo}！"
            )
        else:
            yield event.plain_result("❌ 绑定失败，请稍后重试。")

    @github_commands.command("unbind", alias={"解绑"})
    async def unbind_github_command(self, event: AstrMessageEvent):
        """解绑GitHub ID"""
        if event.get_platform_name() != "aiocqhttp":
            return

        if not await self._ensure_github_manager():
            yield event.plain_result("GitHub管理器未初始化，请联系管理员。")
            return

        uid = str(event.get_sender_id())
        group_id = event.get_group_id()

        # 确定要解绑的仓库
        if group_id:
            repo = self.get_repo_for_group(group_id)
        else:
            repo = self.default_repo

        if not repo:
            yield event.plain_result("无法确定要解绑的仓库，请在配置了仓库映射的群组中使用此命令。")
            return

        # 检查用户是否已经绑定
        existing_github = await self.github_manager.is_qq_bound_to_repo(uid, repo)
        if not existing_github:
            yield event.plain_result(f"你在仓库 {repo} 还没有绑定任何GitHub用户。")
            return

        # 执行解绑
        unbind_success = await self.github_manager.unbind_qq_from_repo(uid, repo)
        if unbind_success:
            yield event.plain_result(
                f"✅ 成功从仓库 {repo} 解绑GitHub用户 {existing_github}！"
            )
        else:
            yield event.plain_result("❌ 解绑失败，请稍后重试。")

    @github_commands.command("mystatus", alias={"状态"})
    async def user_status_command(self, event: AstrMessageEvent):
        """查看自己的绑定状态"""
        if event.get_platform_name() != "aiocqhttp":
            return

        if not await self._ensure_github_manager():
            yield event.plain_result("GitHub管理器未初始化，请联系管理员。")
            return

        uid = event.get_sender_id()
        group_id = event.get_group_id()

        # 获取用户在所有仓库的绑定状态
        bound_repos = await self.github_manager.get_qq_bound_repos(uid)

        if bound_repos:
            status_msg = "🔗 你的GitHub绑定状态:\n"
            for repo in bound_repos:
                github_id = await self.github_manager.is_qq_bound_to_repo(uid, repo)
                status_msg += f"📦 {repo}: {github_id}\n"

            # 显示当前群组信息
            if group_id:
                current_repo = self.get_repo_for_group(group_id)
                if current_repo:
                    current_binding = await self.github_manager.is_qq_bound_to_repo(
                        uid, current_repo
                    )
                    if current_binding:
                        status_msg += f"\n🎯 当前群组 ({group_id}) 仓库: {current_repo}\n✅ 已绑定: {current_binding}"
                    else:
                        status_msg += (
                            f"\n🎯 当前群组 ({group_id}) 仓库: {current_repo}\n❌ 未绑定"
                        )
                else:
                    status_msg += f"\n🎯 当前群组 ({group_id}): 未配置仓库"

            yield event.plain_result(status_msg.strip())
        else:
            if group_id:
                current_repo = self.get_repo_for_group(group_id)
            else:
                current_repo = self.default_repo

            current_repo_display = current_repo or "未配置"
            yield event.plain_result(
                f"❌ 你还没有绑定任何GitHub用户。\n🎯 当前仓库: {current_repo_display}\n使用 /github bind <用户名> 进行绑定。"
            )

    @github_commands.command("help", alias={"帮助"})
    async def user_help_command(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_msg = """GitHub用户命令：
/github [bind|绑定] <用户名> - 绑定GitHub用户名到当前群组仓库
/github [unbind|解绑] - 解绑当前群组仓库的GitHub用户
/github [mystatus|状态] - 查看绑定状态
/github [help|帮助] - 显示帮助信息

管理员命令：
/github sync [仓库] - 同步GitHub Star用户数据
/github status - 查看插件状态

注意：
- 只能绑定已经Star过对应仓库的GitHub用户
- 每个QQ号在每个仓库只能绑定一个GitHub用户
- 每个GitHub用户在每个仓库只能被一个QQ号绑定
- 不同群组可以配置不同的GitHub仓库进行验证"""

        yield event.plain_result(help_msg)

    async def __aenter__(self):
        await self._ensure_github_manager()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.github_manager:
            await self.github_manager.close()
