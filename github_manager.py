import aiosqlite
import httpx
import asyncio
import time
import os
from typing import List, Optional
from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

DB_PATH = os.path.join(
    get_astrbot_data_path(),
    "plugin_data",
    "group_verification_github_star",
    "github_star.db",
)


class GitHubStarManager:
    """GitHub Star用户管理器"""

    def __init__(self, github_token: str, github_repo: str):
        self.github_token = github_token
        self.github_repo = github_repo
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def init_database(self):
        """初始化数据库表"""
        # 确保数据库目录存在
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

        async with aiosqlite.connect(DB_PATH) as conn:
            # 创建GitHub Star用户表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS github_stars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    github_id TEXT NOT NULL UNIQUE,
                    qq_id TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(github_id)
                )
            """)

            # 创建索引
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_github_stars_github_id ON github_stars(github_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_github_stars_qq_id ON github_stars(qq_id)
            """)

            await conn.commit()

        logger.info(f"[GitHub Manager] 数据库初始化完成: {DB_PATH}")

    async def fetch_stargazers(self) -> List[str]:
        """获取仓库的所有Star用户"""
        stargazers = []
        page = 1
        per_page = 100
        max_retries = 3
        backoff_base = 1.0

        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AstrBot-GitHub-Verification",
        }

        logger.info(f"[GitHub Manager] 开始获取仓库 {self.github_repo} 的Star用户...")

        while True:
            url = f"https://api.github.com/repos/{self.github_repo}/stargazers"
            params = {"page": page, "per_page": per_page}

            for attempt in range(1, max_retries + 1):
                try:
                    response = await self.http_client.get(
                        url, headers=headers, params=params
                    )

                    if response.status_code == 200:
                        try:
                            data = response.json()
                        except Exception as e:
                            logger.error(
                                f"[GitHub Manager] 解析JSON失败（页 {page}）: {e}"
                            )
                            data = None

                        if not data:  # 没有更多数据
                            if page == 1:
                                logger.warning(
                                    f"[GitHub Manager] 仓库 {self.github_repo} 暂时没有Star用户"
                                )
                            logger.info(
                                f"[GitHub Manager] 已获取完所有页面，共 {len(stargazers)} 个Star用户"
                            )
                            return stargazers

                        for user in data:
                            if user and user.get("login"):
                                stargazers.append(user.get("login"))

                        logger.info(
                            f"[GitHub Manager] 获取第 {page} 页，{len(data)} 个用户，累计: {len(stargazers)}"
                        )
                        page += 1
                        await asyncio.sleep(0.1)
                        break  # 当前页成功，跳出重试循环

                    elif response.status_code == 401:
                        logger.error(
                            f"[GitHub Manager] 认证失败: {response.text[:500]}"
                        )
                        return stargazers

                    elif response.status_code == 403:
                        remaining = response.headers.get(
                            "X-RateLimit-Remaining", "unknown"
                        )

                        # 检查是否是API限制还是权限问题
                        if remaining == "0" or "rate limit" in response.text.lower():
                            logger.warning(
                                f"[GitHub Manager] API限制，已收集到 {len(stargazers)} 个Star用户"
                            )
                        else:
                            logger.error(
                                f"[GitHub Manager] 权限不足: {response.text[:500]}"
                            )
                        return stargazers

                    elif response.status_code == 404:
                        logger.error(
                            f"[GitHub Manager] 仓库不存在: {response.text[:500]}"
                        )
                        return stargazers

                    elif response.status_code == 422:
                        # 页码超出范围，正常结束
                        logger.info(
                            f"[GitHub Manager] 获取完成，共 {len(stargazers)} 个Star用户"
                        )
                        return stargazers

                    elif 500 <= response.status_code < 600:
                        # 服务端错误，重试
                        if attempt < max_retries:
                            await asyncio.sleep(backoff_base * attempt)
                            continue
                        else:
                            logger.error(
                                f"[GitHub Manager] 服务器错误: {response.text[:500]}"
                            )
                            return stargazers

                    else:
                        logger.error(
                            f"[GitHub Manager] 请求失败: {response.status_code} - {response.text[:500]}"
                        )
                        return stargazers

                except httpx.TimeoutException:
                    if attempt < max_retries:
                        await asyncio.sleep(backoff_base * attempt)
                        continue
                    else:
                        logger.error("[GitHub Manager] 请求超时")
                        return stargazers
                except Exception as e:
                    logger.error(f"[GitHub Manager] 请求异常: {e}")
                    return stargazers

            else:
                # 所有重试都失败
                logger.error("[GitHub Manager] 重试失败，停止获取")
                return stargazers

        # 正常完成
        logger.info(f"[GitHub Manager] 获取完成，共 {len(stargazers)} 个Star用户")
        return stargazers

    async def check_user_starred_directly(self, github_username: str) -> bool:
        """直接通过GitHub API检查用户是否Star了仓库"""
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.star+json",  # 包含时间戳
            "User-Agent": "AstrBot-GitHub-Verification",
        }

        try:
            # 使用GitHub API检查特定用户的starred仓库列表
            url = f"https://api.github.com/users/{github_username}/starred"
            params = {"per_page": 100}

            logger.info(f"[GitHub Manager] 开始检查用户 {github_username} 的Star列表")

            page = 1
            user_starred = False
            checked_count = 0
            star_time = None

            while page <= 20:  # 最多检查2000个仓库，避免API调用过多
                params["page"] = page
                response = await self.http_client.get(
                    url, headers=headers, params=params
                )

                if response.status_code == 200:
                    data = response.json()
                    if not data:  # 没有更多数据
                        break

                    # 检查当前页是否包含目标仓库
                    for starred_repo_data in data:
                        starred_repo = starred_repo_data.get("repo", {})
                        repo_full_name = starred_repo.get("full_name", "")
                        checked_count += 1

                        if repo_full_name == self.github_repo:
                            # 获取Star时间戳
                            star_time = starred_repo_data.get("starred_at", "未知时间")
                            logger.info(
                                f"[GitHub Manager] 用户 {github_username} 已Star仓库 {self.github_repo} (时间: {star_time})"
                            )
                            user_starred = True
                            break  # 找到仓库后立即跳出当前页的循环

                    if user_starred:
                        break  # 找到仓库后跳出分页循环

                    page += 1
                    await asyncio.sleep(0.1)  # 避免API限制

                elif response.status_code == 401:
                    logger.error(f"[GitHub Manager] 认证失败: {response.text[:500]}")
                    return False
                elif response.status_code == 403:
                    logger.warning(
                        f"[GitHub Manager] API限制或权限不足: {response.text[:500]}"
                    )
                    return False
                elif response.status_code == 404:
                    logger.warning(
                        f"[GitHub Manager] 用户 {github_username} 不存在或仓库不可见"
                    )
                    return False
                else:
                    logger.error(
                        f"[GitHub Manager] 检查Star状态失败: {response.status_code} - {response.text[:500]}"
                    )
                    return False

            # 根据是否找到仓库返回结果
            if user_starred:
                # 将用户信息写入数据库
                await self._save_user_to_db(github_username)
                return True
            else:
                logger.info(
                    f"[GitHub Manager] 用户 {github_username} 在其 {checked_count} 个Star仓库中未找到 {self.github_repo}"
                )
                return False

        except Exception as e:
            logger.error(f"[GitHub Manager] 检查Star状态异常: {e}")
            return False

    async def _save_user_to_db(self, github_username: str):
        """将找到的Star用户保存到数据库"""
        try:
            current_time = int(time.time())
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO github_stars (github_id, created_at, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (github_username, current_time, current_time),
                )
                await conn.commit()
                logger.info(f"[GitHub Manager] 已将用户 {github_username} 保存到数据库")
        except Exception as e:
            logger.warning(f"[GitHub Manager] 保存用户到数据库失败: {e}")

    async def sync_stargazers(self, stargazers: List[str]):
        """同步Star用户到数据库"""
        current_time = int(time.time())

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                # 获取数据库中现有的GitHub用户
                async with conn.execute("SELECT github_id FROM github_stars") as cursor:
                    rows = await cursor.fetchall()
                    existing_users = {row[0] for row in rows}

                # 添加新的Star用户
                new_users = set(stargazers) - existing_users
                for github_id in new_users:
                    await conn.execute(
                        """
                        INSERT OR IGNORE INTO github_stars (github_id, created_at, updated_at)
                        VALUES (?, ?, ?)
                    """,
                        (github_id, current_time, current_time),
                    )

                # 可选：删除不再是Star用户的记录
                # 注意：这可能会删除已绑定QQ号的用户，谨慎使用
                # removed_users = existing_users - set(stargazers)
                # for github_id in removed_users:
                #     await conn.execute("DELETE FROM github_stars WHERE github_id = ?", (github_id,))

                await conn.commit()
                logger.info(
                    f"[GitHub Manager] 同步完成: 新增 {len(new_users)} 个Star用户"
                )

        except Exception as e:
            logger.error(f"[GitHub Manager] 同步数据失败: {e}")

    async def is_stargazer(self, github_id: str) -> bool:
        """检查用户是否为Star用户"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT 1 FROM github_stars WHERE github_id = ?", (github_id,)
                ) as cursor:
                    result = await cursor.fetchone()
                    return result is not None
        except Exception as e:
            logger.error(f"[GitHub Manager] 检查Star状态失败: {e}")
            return False

    async def is_github_id_bound(self, github_id: str) -> Optional[str]:
        """检查GitHub ID是否已被绑定，返回绑定的QQ号"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT qq_id FROM github_stars WHERE github_id = ? AND qq_id IS NOT NULL",
                    (github_id,),
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"[GitHub Manager] 检查绑定状态失败: {e}")
            return None

    async def is_qq_bound(self, qq_id: str) -> Optional[str]:
        """检查QQ号是否已绑定GitHub ID，返回绑定的GitHub ID"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT github_id FROM github_stars WHERE qq_id = ?", (qq_id,)
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"[GitHub Manager] 检查QQ绑定状态失败: {e}")
            return None

    async def bind_github_qq(self, github_id: str, qq_id: str) -> bool:
        """绑定GitHub ID和QQ号"""
        current_time = int(time.time())

        try:
            # 先检查QQ号是否已经绑定了其他GitHub ID
            existing_github = await self.is_qq_bound(qq_id)
            if existing_github and existing_github != github_id:
                logger.warning(
                    f"[GitHub Manager] QQ号 {qq_id} 已绑定GitHub用户 {existing_github}"
                )
                return False

            async with aiosqlite.connect(DB_PATH) as conn:
                # 更新绑定关系
                cursor = await conn.execute(
                    """
                    UPDATE github_stars
                    SET qq_id = ?, updated_at = ?
                    WHERE github_id = ?
                """,
                    (qq_id, current_time, github_id),
                )

                await conn.commit()
                success = cursor.rowcount > 0

                if success:
                    logger.info(
                        f"[GitHub Manager] 成功绑定: GitHub用户 {github_id} <-> QQ号 {qq_id}"
                    )
                else:
                    logger.warning(
                        f"[GitHub Manager] 绑定失败: GitHub用户 {github_id} 不存在"
                    )

                return success

        except Exception as e:
            logger.error(f"[GitHub Manager] 绑定失败: {e}")
            return False

    async def unbind_qq(self, qq_id: str) -> bool:
        """解绑QQ号"""
        current_time = int(time.time())

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                cursor = await conn.execute(
                    """
                    UPDATE github_stars
                    SET qq_id = NULL, updated_at = ?
                    WHERE qq_id = ?
                """,
                    (current_time, qq_id),
                )

                await conn.commit()
                success = cursor.rowcount > 0

                if success:
                    logger.info(f"[GitHub Manager] 成功解绑QQ号: {qq_id}")

                return success

        except Exception as e:
            logger.error(f"[GitHub Manager] 解绑失败: {e}")
            return False

    async def get_stars_count(self) -> int:
        """获取数据库中Star用户总数"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute("SELECT COUNT(*) FROM github_stars") as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else 0
        except Exception as e:
            logger.error(f"[GitHub Manager] 获取Star用户数量失败: {e}")
            return 0

    async def get_bound_count(self) -> int:
        """获取已绑定QQ号的用户数量"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT COUNT(*) FROM github_stars WHERE qq_id IS NOT NULL"
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else 0
        except Exception as e:
            logger.error(f"[GitHub Manager] 获取绑定用户数量失败: {e}")
            return 0

    async def close(self):
        """关闭HTTP客户端"""
        if self.http_client:
            await self.http_client.aclose()
            logger.debug("[GitHub Manager] HTTP客户端已关闭")

    def __str__(self):
        return f"GitHubStarManager(repo={self.github_repo}, db={DB_PATH})"
