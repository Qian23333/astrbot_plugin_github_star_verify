import aiosqlite
import httpx
import asyncio
import time
import os
from typing import List, Optional, Dict
from astrbot.api import logger
from astrbot.api.star import StarTools

# 数据库文件路径
DB_PATH = str(StarTools.get_data_dir("github_star_verify") / "github_stars.db")


async def init_database():
    """初始化数据库表结构"""
    # 确保数据库目录存在
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as conn:
        # 创建GitHub Star用户表，使用复合主键
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS github_stars (
                github_id TEXT NOT NULL,
                repo TEXT NOT NULL,
                qq_id TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (github_id, repo)
            )
        """)

        # 创建索引（主键字段会自动创建索引，这里只需要为其他字段创建）
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_github_stars_qq_id ON github_stars(qq_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_github_stars_repo ON github_stars(repo)
        """)

        await conn.commit()

    logger.info(f"[GitHub Star Verify] 数据库初始化完成: {DB_PATH}")


class GitHubStarManager:
    """单仓库GitHub Star管理器"""

    def __init__(
        self,
        github_token: str,
        github_repo: str,
        http_client: httpx.AsyncClient,
    ):
        self.github_token = github_token
        self.github_repo = github_repo
        self.http_client = http_client

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

        logger.info(f"[GitHub Star Verify] 开始获取仓库 {self.github_repo} 的Star用户...")

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
                                f"[GitHub Star Verify] 解析JSON失败（页 {page}）: {e}"
                            )
                            data = None

                        if not data:  # 没有更多数据
                            if page == 1:
                                logger.warning(
                                    f"[GitHub Star Verify] 仓库 {self.github_repo} 暂时没有Star用户"
                                )
                            logger.info(
                                f"[GitHub Star Verify] 已获取完所有页面，共 {len(stargazers)} 个Star用户"
                            )
                            return stargazers

                        for user in data:
                            if user and user.get("login"):
                                stargazers.append(user.get("login"))

                        logger.info(
                            f"[GitHub Star Verify] 获取第 {page} 页，{len(data)} 个用户，累计: {len(stargazers)}"
                        )
                        page += 1
                        await asyncio.sleep(0.1)
                        break  # 当前页成功，跳出重试循环

                    elif response.status_code == 401:
                        logger.error(
                            f"[GitHub Star Verify] 认证失败: {response.text[:500]}"
                        )
                        return stargazers

                    elif response.status_code == 403:
                        remaining = response.headers.get(
                            "X-RateLimit-Remaining", "unknown"
                        )

                        # 检查是否是API限制还是权限问题
                        if remaining == "0" or "rate limit" in response.text.lower():
                            logger.warning(
                                f"[GitHub Star Verify] API限制，已收集到 {len(stargazers)} 个Star用户"
                            )
                        else:
                            logger.error(
                                f"[GitHub Star Verify] 权限不足: {response.text[:500]}"
                            )
                        return stargazers

                    elif response.status_code == 404:
                        logger.error(
                            f"[GitHub Star Verify] 仓库不存在: {response.text[:500]}"
                        )
                        return stargazers

                    elif response.status_code == 422:
                        # 页码超出范围，正常结束
                        logger.info(
                            f"[GitHub Star Verify] 获取完成，共 {len(stargazers)} 个Star用户"
                        )
                        return stargazers

                    elif 500 <= response.status_code < 600:
                        # 服务端错误，重试
                        if attempt < max_retries:
                            await asyncio.sleep(backoff_base * attempt)
                            continue
                        else:
                            logger.error(
                                f"[GitHub Star Verify] 服务器错误: {response.text[:500]}"
                            )
                            return stargazers

                    else:
                        logger.error(
                            f"[GitHub Star Verify] 请求失败: {response.status_code} - {response.text[:500]}"
                        )
                        return stargazers

                except httpx.TimeoutException:
                    if attempt < max_retries:
                        await asyncio.sleep(backoff_base * attempt)
                        continue
                    else:
                        logger.error("[GitHub Star Verify] 请求超时")
                        return stargazers
                except Exception as e:
                    logger.error(f"[GitHub Star Verify] 请求异常: {e}")
                    return stargazers

            else:
                # 所有重试都失败
                logger.error("[GitHub Star Verify] 重试失败，停止获取")
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

            logger.info(f"[GitHub Star Verify] 开始检查用户 {github_username} 的Star列表")

            page = 1
            user_starred = False
            checked_count = 0
            star_time = None

            # 通过 Link 响应头判断是否还有下一页，直到没有下一页为止
            while True:
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
                                f"[GitHub Star Verify] 用户 {github_username} 已Star仓库 {self.github_repo} (时间: {star_time})"
                            )
                            user_starred = True
                            break  # 找到仓库后立即跳出当前页的循环

                    if user_starred:
                        break  # 找到仓库后跳出分页循环

                    # 若 Link 头存在 next 则继续翻页，否则结束
                    link_header = response.headers.get("Link", "")
                    if 'rel="next"' in link_header:
                        page += 1
                        await asyncio.sleep(0.1)  # 避免API限制
                        continue
                    else:
                        break

                elif response.status_code == 401:
                    logger.error(f"[GitHub Star Verify] 认证失败: {response.text[:500]}")
                    return False
                elif response.status_code == 403:
                    logger.warning(
                        f"[GitHub Star Verify] API限制或权限不足: {response.text[:500]}"
                    )
                    return False
                elif response.status_code == 404:
                    logger.warning(
                        f"[GitHub Star Verify] 用户 {github_username} 不存在或仓库不可见"
                    )
                    return False
                else:
                    logger.error(
                        f"[GitHub Star Verify] 检查Star状态失败: {response.status_code} - {response.text[:500]}"
                    )
                    return False

            # 根据是否找到仓库返回结果
            if user_starred:
                return True
            else:
                logger.info(
                    f"[GitHub Star Verify] 用户 {github_username} 在其 {checked_count} 个Star仓库中未找到 {self.github_repo}"
                )
                return False

        except Exception as e:
            logger.error(f"[GitHub Star Verify] 检查Star状态异常: {e}")
            return False

    async def record_stargazer(self, github_username: str) -> bool:
        """将找到的Star用户保存到数据库"""
        try:
            current_time = int(time.time())
            async with aiosqlite.connect(DB_PATH) as conn:
                # 使用 UPSERT：若(github_id, repo)已存在，仅更新updated_at，保留既有的qq_id与created_at
                await conn.execute(
                    """
                    INSERT INTO github_stars (github_id, repo, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(github_id, repo) DO UPDATE SET
                        updated_at = excluded.updated_at
                    """,
                    (github_username, self.github_repo, current_time, current_time),
                )
                await conn.commit()
                logger.info(f"[GitHub Star Verify] 已将用户 {github_username} 保存到数据库")
                return True
        except Exception as e:
            logger.warning(f"[GitHub Star Verify] 保存用户到数据库失败: {e}")
            return False

    async def sync_stargazers(self, stargazers: List[str]):
        """同步Star用户到数据库"""
        current_time = int(time.time())

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                # 获取数据库中现有的GitHub用户（针对当前仓库）
                async with conn.execute(
                    "SELECT github_id FROM github_stars WHERE repo = ?",
                    (self.github_repo,),
                ) as cursor:
                    rows = await cursor.fetchall()
                    existing_users = {row[0] for row in rows}

                # 添加新的Star用户
                new_users = set(stargazers) - existing_users
                for github_id in new_users:
                    await conn.execute(
                        """
                        INSERT OR IGNORE INTO github_stars (github_id, repo, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                    """,
                        (github_id, self.github_repo, current_time, current_time),
                    )

                await conn.commit()
                logger.info(
                    f"[GitHub Star Verify] 同步完成: 新增 {len(new_users)} 个Star用户到仓库 {self.github_repo}"
                )

        except Exception as e:
            logger.error(f"[GitHub Star Verify] 同步数据失败: {e}")

    async def is_stargazer_for_repo(self, github_id: str, repo: str) -> bool:
        """检查用户是否为指定仓库的Star用户"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT 1 FROM github_stars WHERE github_id = ? AND repo = ?",
                    (github_id, repo),
                ) as cursor:
                    result = await cursor.fetchone()
                    return result is not None
        except Exception as e:
            logger.error(f"[GitHub Star Verify] 检查Star状态失败: {e}")
            return False

    async def is_github_id_bound_to_repo(
        self, github_id: str, repo: str
    ) -> Optional[str]:
        """检查GitHub ID是否已被绑定到指定仓库，返回绑定的QQ号"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT qq_id FROM github_stars WHERE github_id = ? AND repo = ? AND qq_id IS NOT NULL",
                    (github_id, repo),
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"[GitHub Star Verify] 检查绑定状态失败: {e}")
            return None

    async def is_qq_bound_to_repo(self, qq_id: str, repo: str) -> Optional[str]:
        """检查QQ号是否已绑定到指定仓库的GitHub ID，返回绑定的GitHub ID"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT github_id FROM github_stars WHERE qq_id = ? AND repo = ?",
                    (qq_id, repo),
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"[GitHub Star Verify] 检查QQ绑定状态失败: {e}")
            return None

    async def bind_github_qq_to_repo(
        self, github_id: str, qq_id: str, repo: str
    ) -> bool:
        """绑定GitHub ID和QQ号到指定仓库"""
        current_time = int(time.time())

        try:
            # 先检查QQ号是否已经绑定了其他GitHub ID（在同一个仓库）
            existing_github = await self.is_qq_bound_to_repo(qq_id, repo)
            if existing_github and existing_github != github_id:
                logger.warning(
                    f"[GitHub Star Verify] QQ号 {qq_id} 已绑定GitHub用户 {existing_github} 在仓库 {repo}"
                )
                return False

            async with aiosqlite.connect(DB_PATH) as conn:
                # 更新绑定关系
                cursor = await conn.execute(
                    """
                    UPDATE github_stars
                    SET qq_id = ?, updated_at = ?
                    WHERE github_id = ? AND repo = ?
                """,
                    (qq_id, current_time, github_id, repo),
                )

                await conn.commit()
                success = cursor.rowcount > 0

                if success:
                    logger.info(
                        f"[GitHub Star Verify] 成功绑定: GitHub用户 {github_id} <-> QQ号 {qq_id} 在仓库 {repo}"
                    )
                else:
                    logger.warning(
                        f"[GitHub Star Verify] 绑定失败: GitHub用户 {github_id} 不存在于仓库 {repo}"
                    )

                return success

        except Exception as e:
            logger.error(f"[GitHub Star Verify] 绑定失败: {e}")
            return False

    async def unbind_qq_from_repo(self, qq_id: str, repo: str) -> bool:
        """从指定仓库解绑QQ号"""
        current_time = int(time.time())

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                cursor = await conn.execute(
                    """
                    UPDATE github_stars
                    SET qq_id = NULL, updated_at = ?
                    WHERE qq_id = ? AND repo = ?
                """,
                    (current_time, qq_id, repo),
                )

                await conn.commit()
                success = cursor.rowcount > 0

                if success:
                    logger.info(f"[GitHub Star Verify] 成功解绑QQ号: {qq_id} 从仓库 {repo}")

                return success

        except Exception as e:
            logger.error(f"[GitHub Star Verify] 解绑失败: {e}")
            return False

    async def get_stars_count_for_repo(self, repo: str) -> int:
        """获取指定仓库的Star用户总数"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT COUNT(*) FROM github_stars WHERE repo = ?", (repo,)
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else 0
        except Exception as e:
            logger.error(f"[GitHub Star Verify] 获取Star用户数量失败: {e}")
            return 0

    async def get_bound_count_for_repo(self, repo: str) -> int:
        """获取指定仓库已绑定QQ号的用户数量"""
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT COUNT(*) FROM github_stars WHERE qq_id IS NOT NULL AND repo = ?",
                    (repo,),
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else 0
        except Exception as e:
            logger.error(f"[GitHub Star Verify] 获取绑定用户数量失败: {e}")
            return 0

    def __str__(self):
        return f"GitHubStarManager(repo={self.github_repo}, db={DB_PATH})"


class MultiRepoGitHubStarManager:
    """多仓库GitHub Star管理器"""

    def __init__(self, github_token: str, default_repo: str, group_repo_map: Dict[str, str]):
        self.github_token = github_token
        self.default_repo = default_repo
        self.group_repo_map = group_repo_map or {}
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._managers_cache: Dict[str, GitHubStarManager] = {}

    async def init_database(self):
        """初始化数据库 - 桥接方法"""
        await init_database()

    def get_manager_for_repo(self, repo: str) -> GitHubStarManager:
        """获取指定仓库的管理器实例"""
        if repo not in self._managers_cache:
            self._managers_cache[repo] = GitHubStarManager(
                github_token=self.github_token,
                github_repo=repo,
                http_client=self.http_client,
            )
        return self._managers_cache[repo]

    def get_repo_for_group(self, group_id: str) -> Optional[str]:
        """根据群组ID获取对应的仓库"""
        repo = self.group_repo_map.get(group_id)
        if repo:
            return repo
        elif self.default_repo:
            return self.default_repo
        else:
            return None

    async def sync_stargazers_for_repo(self, repo: str) -> bool:
        """同步指定仓库的Star用户"""
        try:
            manager = self.get_manager_for_repo(repo)
            stargazers = await manager.fetch_stargazers()

            if stargazers:
                logger.info(
                    f"[GitHub Star Verify] 成功获取 {len(stargazers)} 个Star用户，开始同步到数据库..."
                )
                await manager.sync_stargazers(stargazers)
                return True
            else:
                logger.info(
                    f"[GitHub Star Verify] 仓库 {repo} 当前没有Star用户，数据库已初始化"
                )
                return True
        except Exception as e:
            logger.error(f"[GitHub Star Verify] 同步仓库 {repo} 的Star用户失败: {e}")
            return False

    async def sync_all_repos(self) -> Dict[str, bool]:
        """同步所有配置的仓库"""
        results = {}

        # 同步默认仓库（如果配置了）
        if self.default_repo:
            results[self.default_repo] = await self.sync_stargazers_for_repo(self.default_repo)

        # 同步所有群组配置的仓库
        unique_repos = set(self.group_repo_map.values())
        for repo in unique_repos:
            if repo and repo != self.default_repo:  # 避免重复同步
                results[repo] = await self.sync_stargazers_for_repo(repo)

        return results

    async def check_user_starred_directly(self, github_username: str, repo: str) -> bool:
        """直接通过GitHub API检查用户是否Star了指定仓库"""
        manager = self.get_manager_for_repo(repo)
        return await manager.check_user_starred_directly(github_username)

    async def record_stargazer(self, github_username: str, repo: str) -> bool:
        """记录Star用户到数据库"""
        manager = self.get_manager_for_repo(repo)
        return await manager.record_stargazer(github_username)

    async def is_stargazer(self, github_id: str, repo: str) -> bool:
        """检查用户是否为指定仓库的Star用户"""
        manager = self.get_manager_for_repo(repo)
        return await manager.is_stargazer_for_repo(github_id, repo)

    async def is_github_id_bound_to_repo(self, github_id: str, repo: str) -> Optional[str]:
        """检查GitHub ID是否已被绑定到指定仓库，返回绑定的QQ号"""
        manager = self.get_manager_for_repo(repo)
        return await manager.is_github_id_bound_to_repo(github_id, repo)

    async def is_qq_bound_to_repo(self, qq_id: str, repo: str) -> Optional[str]:
        """检查QQ号是否已绑定到指定仓库的GitHub ID，返回绑定的GitHub ID"""
        manager = self.get_manager_for_repo(repo)
        return await manager.is_qq_bound_to_repo(qq_id, repo)

    async def bind_github_qq_to_repo(self, github_id: str, qq_id: str, repo: str) -> bool:
        """绑定GitHub ID和QQ号到指定仓库"""
        manager = self.get_manager_for_repo(repo)
        return await manager.bind_github_qq_to_repo(github_id, qq_id, repo)

    async def unbind_qq_from_repo(self, qq_id: str, repo: str) -> bool:
        """从指定仓库解绑QQ号"""
        manager = self.get_manager_for_repo(repo)
        return await manager.unbind_qq_from_repo(qq_id, repo)

    async def get_stars_count_for_repo(self, repo: str) -> int:
        """获取指定仓库的Star用户总数"""
        manager = self.get_manager_for_repo(repo)
        return await manager.get_stars_count_for_repo(repo)

    async def get_bound_count_for_repo(self, repo: str) -> int:
        """获取指定仓库已绑定QQ号的用户数量"""
        manager = self.get_manager_for_repo(repo)
        return await manager.get_bound_count_for_repo(repo)

    async def get_qq_bound_repos(self, qq_id: str) -> List[str]:
        """
        使用单次查询获取该 QQ 绑定的所有 repo，然后按照以下顺序返回：
        1. 如果 default_repo 存在且已绑定，则先返回；
        2. 按照 group_repo_map 的顺序返回已绑定的仓库（去重）；
        3. 将其他未在配置中的仓库追加在最后（按字典顺序保证确定性）。
        """

        try:
            # 一次性查询数据库，获取该 qq_id 绑定的所有 repo
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute(
                    "SELECT DISTINCT repo FROM github_stars WHERE qq_id = ?",
                    (qq_id,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    found = {row[0] for row in rows}
        except Exception as e:
            logger.error(f"[GitHub Star Verify] 查询绑定仓库失败: {e}")
            return []

        if not found:
            return []

        bound_repos: List[str] = []

        # default_repo 优先
        if self.default_repo and self.default_repo in found:
            bound_repos.append(self.default_repo)

        # 按 group_repo_map 的顺序加入已绑定且未加入的仓库
        added = set(bound_repos)
        for r in self.group_repo_map.values():
            if not r:
                continue
            if r in added:
                continue
            if r in found:
                bound_repos.append(r)
                added.add(r)

        # 将数据库中存在但未在配置中的仓库追加（保持确定性，按排序）
        others = sorted(found - added)
        bound_repos.extend(others)

        return bound_repos

    async def close(self):
        """关闭HTTP客户端"""
        if self.http_client:
            await self.http_client.aclose()
            logger.debug("[GitHub Star Verify] HTTP客户端已关闭")

    def __str__(self):
        return f"MultiRepoGitHubStarManager(default_repo={self.default_repo}, group_count={len(self.group_repo_map)})"
