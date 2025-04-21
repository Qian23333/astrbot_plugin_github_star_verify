from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import asyncio
from typing import Dict, Any

@register(
    "qq_member_verify",
    "huotuo146",
    "QQ群成员验证插件",
    "1.2.1",  # 版本号提升
    "https://github.com/huntuo146/astrbot_plugin_Group-Verification"
)
class QQGroupVerifyPlugin(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.context = context
        
        self.verification_word = config.get("verification_word", "进行验证")
        self.verification_timeout = config.get("verification_timeout", 300)
        self.kick_delay = config.get("kick_delay", 60)
        
        self.join_prompt = config.get(
            "join_prompt", 
            "欢迎 {member_name} 加入本群！请在 {timeout} 分钟内 @我 并回复“{verification_word}”完成验证，否则将被踢出群聊。"
        )
        # --- 修复: 调整默认欢迎语，使其包含@占位符，避免硬编码拼接 ---
        self.welcome_message = config.get(
            "welcome_message", 
            "{at_user} 验证成功，欢迎你的加入！"
        )
        self.failure_message = config.get("failure_message", "验证超时，你将在 {countdown} 秒后被请出本群。")
        self.kick_message = config.get("kick_message", "{member_name} 因未在规定时间内完成验证，已被请出本群。")

        self.pending: Dict[str, int] = {}
        self.timeout_tasks: Dict[str, asyncio.Task] = {}

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
        raw = event.message_obj.raw_message
        uid = str(raw.get("user_id"))
        gid = raw.get("group_id")
        
        if uid in self.timeout_tasks:
            old_task = self.timeout_tasks.pop(uid, None)
            if old_task and not old_task.done():
                old_task.cancel()
        
        self.pending[uid] = gid
        logger.info(f"[QQ Verify] 用户 {uid} 加入群 {gid}，启动验证流程。")

        nickname = uid
        try:
            user_info = await event.bot.api.call_action("get_group_member_info", group_id=gid, user_id=int(uid))
            nickname = user_info.get("card", "") or user_info.get("nickname", uid)
        except Exception as e:
            logger.warning(f"[QQ Verify] 获取用户 {uid} 在群 {gid} 的昵称失败: {e}，将使用UID作为昵称。")

        # --- 修复: 格式化 member_name 时仅使用CQ码，避免昵称重复 ---
        prompt_message = self.join_prompt.format(
            member_name=f"[CQ:at,qq={uid}]", # CQ码会自动渲染为@昵称
            timeout=self.verification_timeout // 60,
            verification_word=self.verification_word
        )
        
        await event.bot.api.call_action(
            "send_group_msg",
            group_id=gid,
            message=prompt_message
        )

        task = asyncio.create_task(self._timeout_kick(uid, gid, nickname))
        self.timeout_tasks[uid] = task

    async def _process_verification_message(self, event: AstrMessageEvent):
        """处理群聊消息验证的逻辑"""
        uid = str(event.get_sender_id())
        if uid not in self.pending:
            return
        
        text = event.message_str.strip()
        raw = event.message_obj.raw_message
        gid = raw.get("group_id")

        bot_id = str(event.get_self_id())
        at_me = any(seg.get("type") == "at" and str(seg.get("data", {}).get("qq")) == bot_id for seg in raw.get("message", []))

        if at_me and self.verification_word in text:
            task = self.timeout_tasks.pop(uid, None)
            if task and not task.done():
                task.cancel()
                logger.info(f"[QQ Verify] 用户 {uid} 验证成功，踢出任务已取消。")
            
            self.pending.pop(uid, None)

            nickname = uid
            try:
                sender_info = raw.get("sender", {})
                nickname = sender_info.get("card", "") or sender_info.get("nickname", uid)
            except Exception:
                pass

            # --- 修复: 让消息模板完全控制输出，传递at_user和member_name供其选择使用 ---
            welcome_msg_formatted = self.welcome_message.format(
                at_user=f"[CQ:at,qq={uid}]",
                member_name=nickname
            )
            
            await event.bot.api.call_action(
                "send_group_msg",
                group_id=gid,
                message=welcome_msg_formatted
            )
            logger.info(f"[QQ Verify] 用户 {uid} 在群 {gid} 验证成功。")
            event.stop_event()

    async def _process_member_decrease(self, event: AstrMessageEvent):
        """处理成员减少的逻辑"""
        raw = event.message_obj.raw_message
        uid = str(raw.get("user_id"))

        if uid in self.pending:
            self.pending.pop(uid, None)
            task = self.timeout_tasks.pop(uid, None)
            if task and not task.done():
                task.cancel()
            logger.info(f"[QQ Verify] 待验证用户 {uid} 已离开群聊，清理其验证状态。")

    async def _timeout_kick(self, uid: str, gid: int, nickname: str):
        """在超时后执行踢人操作的协程"""
        try:
            await asyncio.sleep(self.verification_timeout)

            if uid not in self.pending:
                logger.debug(f"[QQ Verify] 踢出任务唤醒，但用户 {uid} 已不在待验证列表，任务终止。")
                return

            bot = self.context.get_platform("aiocqhttp").get_client()
            
            try:
                failure_msg_formatted = self.failure_message.format(countdown=self.kick_delay)
                await bot.api.call_action("send_group_msg", group_id=gid, message=failure_msg_formatted)
                
                await asyncio.sleep(self.kick_delay)

                if uid not in self.pending:
                    logger.info(f"[QQ Verify] 准备踢出 {uid} 前的最后检查发现其已验证/离开，取消踢出。")
                    return
                
                await bot.api.call_action("set_group_kick", group_id=gid, user_id=int(uid), reject_add_request=False)
                logger.info(f"[QQ Verify] 用户 {uid} ({nickname}) 验证超时，已从群 {gid} 踢出。")
                
                kick_msg_formatted = self.kick_message.format(member_name=nickname)
                await bot.api.call_action("send_group_msg", group_id=gid, message=kick_msg_formatted)
            
            except Exception as e:
                logger.error(f"[QQ Verify] 在为用户 {uid} 执行踢出流程时发生错误: {e}")

        except asyncio.CancelledError:
            logger.info(f"[QQ Verify] 踢出任务被取消：用户 {uid} 已验证或已离开。")
        finally:
            self.pending.pop(uid, None)
            self.timeout_tasks.pop(uid, None)
