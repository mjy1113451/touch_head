import asyncio
import base64
import logging
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image
import aiohttp

from astrbot.api import star, logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.message_components import Image as AstrImage
from astrbot.api.star import StarTools


class TouchHeadPlugin(star.Star):
    """ 摸头杀插件主类。 严格遵循AstrBot生命周期，使用线程池处理CPU密集型任务， 确保异步事件循环不被阻塞。 """

    def __init__(self, context: star.Context):
        super().__init__(context)
        logger.info("摸头杀插件正在初始化...")

        # 1. 使用规范的数据持久化目录
        self.data_dir = Path(StarTools.get_data_dir())
        self.output_dir = self.data_dir / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 2. 资源路径（模板图片）使用插件目录
        self.assets_dir = Path(__file__).parent / "assets"
        if not self.assets_dir.exists():
            self.assets_dir.mkdir(parents=True, exist_ok=True)
            logger.warning(f"资源目录不存在，已创建空目录: {self.assets_dir}")

        # 3. 初始化异步任务管理
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_terminating = False  # 用于优雅关闭

        # 4. 复用aiohttp session
        self._session: Optional[aiohttp.ClientSession] = None

        logger.info("摸头杀插件初始化完成。")

    async def on_astrbot_loaded(self):
        """ 插件加载完成后的生命周期钩子。 启动后台清理任务，并正确管理其生命周期。 """
        logger.info("摸头杀插件已加载，启动后台清理任务...")
        self._cleanup_task = asyncio.create_task(self._cleanup_old_gifs())

    async def terminate(self):
        """ 插件卸载/停止时的生命周期钩子。 取消后台任务，确保资源释放，避免任务泄漏。 """
        logger.info("摸头杀插件正在终止...")
        self._is_terminating = True

        # 安全取消后台任务
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                logger.info("后台清理任务已取消。")
            except Exception as e:
                logger.error(f"取消清理任务时出错: {e}")

        # 关闭aiohttp session
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("aiohttp session已关闭。")

        logger.info("摸头杀插件已终止。")

    # --- 核心功能实现 ---

@filter.command("摸头杀")
    async def handle_command(self, event: AstrMessageEvent):
        """ 处理“摸头杀”命令。 1. 异步获取头像（支持多种来源）。 2. 将CPU密集型GIF生成任务卸载到线程池，避免阻塞事件循环。 """
        sender_name = event.message_event_obj.sender.nickname
        logger.info(f"收到来自 {sender_name} 的摸头杀命令。")

        try:
            # 第一步：异步获取用户头像图片
            user_image = await self._get_user_avatar(event)
            if user_image is None:
                return event.set_result(
                    MessageEventResult().message("抱歉，无法获取您的头像，无法生成摸头杀图片。")
                )

            # 第二步：将CPU密集型任务卸载到线程池
            # 这是解决事件循环阻塞的关键
            gif_path = await asyncio.to_thread(
                self._build_petpet_gif, user_image, sender_name
            )

            if gif_path and gif_path.exists():
                # 使用异步方式发送图片（模拟，实际框架可能提供异步发送）
                await event.send_message(AstrImage.fromFilePath(str(gif_path)))
            else:
                await event.send_message("生成摸头杀图片失败，请稍后再试。")

        except Exception as e:
            logger.error(f"处理摸头杀命令时发生错误: {e}", exc_info=True)
            await event.send_message("发生内部错误，无法处理您的请求。")

    async def _get_user_avatar(self, event: AstrMessageEvent) -> Optional[Image.Image]:
        """ 获取用户头像，兼容多种来源： 1. 事件上下文中的头像URL（常见形式）。 2. 事件上下文中的头像Base64数据。 3. 通过框架API获取。 4. 作为fallback尝试下载QQ头像。 """
        # 尝试从事件上下文获取（框架不同字段名可能不同，需适配）
        avatar_url = getattr(event.message_event_obj.sender, "avatar", None)
        avatar_base64 = getattr(event.message_event_obj.sender, "avatar_base64", None)

        if avatar_url and isinstance(avatar_url, str) and avatar_url.startswith(("http://", "https://")):
            logger.info(f"从事件URL获取头像: {avatar_url}")
            return await self._download_image(avatar_url)
        elif avatar_base64 and isinstance(avatar_base64, str):
            logger.info("从事件Base64获取头像。")
            try:
                image_data = base64.b64decode(avatar_base64)
                if len(image_data) > 5 * 1024 * 1024:
                    logger.warning("Base64头像过大，超过5MB限制")
                    return None
                img = Image.open(BytesIO(image_data))
                img.verify()
                img = Image.open(BytesIO(image_data))
                if img.width * img.height > 2000 * 2000:
                    img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                return img
            except Exception as e:
                logger.error(f"解析Base64头像失败: {e}")

        # 尝试通过框架API获取（这是更标准的方式）
        try:
            # 假设框架提供了获取头像的方法，需根据实际API调整
            # 例如: avatar_bytes = await event.context.get_user_avatar(event.sender.user_id)
            # 以下为示意代码
            avatar_bytes = await self._get_avatar_via_framework(event)
            if avatar_bytes:
                if len(avatar_bytes) > 5 * 1024 * 1024:
                    logger.warning("框架头像过大，超过5MB限制")
                    return None
                img = Image.open(BytesIO(avatar_bytes))
                img.verify()
                img = Image.open(BytesIO(avatar_bytes))
                if img.width * img.height > 2000 * 2000:
                    img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                return img
        except AttributeError:
            logger.debug("框架未提供标准头像获取方法。")
        except Exception as e:
            logger.error(f"通过框架获取头像失败: {e}")

        # Fallback: 尝试下载QQ头像（原始逻辑，但增加安全限制）
        try:
            qq_id = getattr(event.message_event_obj.sender, "user_id", "")
            if qq_id:
                qq_avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={qq_id}&s=640"
                logger.info(f"Fallback: 尝试下载QQ头像: {qq_avatar_url}")
                return await self._download_image(qq_avatar_url)
        except Exception as e:
            logger.error(f"下载QQ头像失败: {e}")

        return None

    async def _download_image(self, url: str) -> Optional[Image.Image]:
        """ 安全下载网络图片。 增加Content-Type、大小限制，防止恶意文件导致内存或安全问题。 """
        try:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        logger.error(f"下载图片失败，HTTP状态码: {response.status}")
                        return None

                    # 1. 检查Content-Type
                    content_type = response.headers.get("Content-Type", "")
                    if "image" not in content_type:
                        logger.warning(f"非图片Content-Type: {content_type}")
                        return None

                    # 2. 限制下载数据大小 (例如：5MB)
                    max_size = 5 * 1024 * 1024  # 5MB
                    if response.content_length and response.content_length > max_size:
                        logger.warning(f"图片过大，超过限制: {response.content_length} bytes")
                        return None

                    image_data = await response.read()
                    if len(image_data) > max_size:
                        logger.warning(f"实际下载图片过大，已截断")
                        return None

                    # 3. 验证并打开图片
                    img = Image.open(BytesIO(image_data))
                    img.verify()  # 验证图片完整性
                    img = Image.open(BytesIO(image_data))  # 重新打开，因为verify()会关闭文件
                    
                    # 4. 可选：限制图片像素尺寸，防止内存压力
                    max_pixels = 2000 * 2000
                    if img.width * img.height > max_pixels:
                        logger.warning(f"图片像素过大，将进行缩放。")
                        img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                    
                    return img

        except asyncio.TimeoutError:
            logger.error("下载图片超时。")
        except aiohttp.ClientError as e:
            logger.error(f"下载图片网络错误: {e}")
        except Exception as e:
            logger.error(f"处理下载图片时发生意外错误: {e}")

        return None

    def _build_petpet_gif(self, user_image: Image.Image, username: str) -> Optional[Path]:
        """ CPU密集型：生成摸头杀GIF。 此函数在单独的线程中运行，不会阻塞事件循环。 使用 `with` 语句确保资源句柄释放。 """
        if self._is_terminating:
            return None

        logger.info(f"开始为用户 {username} 生成GIF...")

        # 1. 准备输出文件路径 - 清洗用户名防止路径注入
        timestamp = int(time.time() * 1000)
        safe_username = re.sub(r'[/\\<>:"\'|?*\x00-\x1f]', '_', username)
        safe_username = safe_username[:50]  # 限制长度
        output_filename = f"petpet_{safe_username}_{timestamp}.gif"
        output_path = self.output_dir / output_filename

        try:
            # 2. 调整用户头像尺寸，与模板匹配
            # 假设模板帧尺寸已知，或在此定义
            template_size = (120, 120)  # 示例尺寸，需根据实际模板调整
            user_image = user_image.resize(template_size, Image.Resampling.LANCZOS)

            # 3. 加载所有模板帧并处理
            frames = []
            frame_files = sorted(self.assets_dir.glob("frame*.png"))
            
            if not frame_files:
                logger.error(f"在 {self.assets_dir} 中未找到任何模板帧(frame*.png)。")
                return None

            for frame_path in frame_files:
                # 使用上下文管理器确保文件句柄被正确释放
                with Image.open(frame_path) as frame_img:
                    # 复制模板帧，避免修改原始文件
                    new_frame = frame_img.copy()
                    # 将用户头像粘贴到指定位置（需根据实际模板调整位置参数）
                    # 以下为示意位置，实际应从模板配置中读取
                    new_frame.paste(user_image, (70, 15))  # 示例坐标
                    frames.append(new_frame)

            # 4. 保存为GIF
            if frames:
                frames[0].save(
                    output_path,
                    save_all=True,
                    append_images=frames[1:],
                    duration=100,  # 每帧持续时间（毫秒）
                    loop=0,  # 无限循环
                    optimize=True,
                    disposal=2  # 优化GIF大小
                )
                logger.info(f"GIF已生成并保存到: {output_path}")
                return output_path
            else:
                logger.error("未能生成任何帧。")
                return None

        except Exception as e:
            logger.error(f"生成GIF过程中发生错误: {e}", exc_info=True)
            # 清理可能创建的不完整文件
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass
            return None

    async def _cleanup_old_gifs(self):
        """ 后台任务：定期清理旧的GIF文件，防止磁盘空间无限增长。 设置为每小时运行一次。 """
        while not self._is_terminating:
            try:
                await asyncio.sleep(3600)  # 每小时运行一次
                logger.info("执行GIF清理任务...")

                # 清理超过24小时的文件
                cutoff_time = 24 * 3600
                count = 0
                for gif_file in self.output_dir.glob("*.gif"):
                    try:
                        stat = gif_file.stat()
                        age = time.time() - stat.st_mtime
                        if age > cutoff_time:
                            gif_file.unlink()
                            count += 1
                            logger.debug(f"已清理旧文件: {gif_file.name}")
                    except Exception as e:
                        logger.error(f"清理文件 {gif_file.name} 时出错: {e}")

                if count > 0:
                    logger.info(f"本次清理了 {count} 个旧GIF文件。")
            except asyncio.CancelledError:
                # 任务被取消，正常退出
                raise
            except Exception as e:
                logger.error(f"清理任务发生错误: {e}", exc_info=True)

    # 以下为辅助方法示例，需根据实际框架API补充
    async def _get_avatar_via_framework(self, event: AstrMessageEvent) -> Optional[bytes]:
        """ 通过AstrBot框架提供的API获取用户头像。 这是一个占位方法，实际实现需要根据您使用的AstrBot版本和API文档进行调整。 """
        try:
            # 示例：假设框架在上下文中提供了用户头像获取方法
            # if hasattr(self.context, 'get_user_avatar'):
            # return await self.context.get_user_avatar(event.sender.user_id)
            # 请替换为实际的框架API调用
            logger.debug("_get_avatar_via_framework: 需根据实际框架API实现。")
            return None
        except Exception as e:
            logger.error(f"通过框架获取头像失败: {e}")
            return None