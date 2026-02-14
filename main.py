from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Image
from typing import Optional, List
import httpx
import re
import subprocess
import sys
import asyncio
import os
import signal

@register(
    "pat_head_gif",
    "mjy1113451",
    "一个自动回复'摸头'并生成摸头杀GIF的插件",
    "1.0.0"
)
class PatHeadGifPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.meme_api_url = self.config.get("api_url", "http://127.0.0.1:2233")
        self.petpet_endpoint = f"{self.meme_api_url}/memes/petpet/"
        self.auto_start = self.config.get("auto_start_api", True)
        self.api_port = self.config.get("api_port", 2233)
        self.api_process: Optional[subprocess.Popen] = None
        self._api_started_by_plugin = False

    async def _install_meme_generator(self) -> bool:
        try:
            self.logger.info("正在安装 meme-generator...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "meme-generator", "-q"],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                self.logger.info("meme-generator 安装成功")
                return True
            else:
                self.logger.error(f"meme-generator 安装失败: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            self.logger.error("meme-generator 安装超时")
            return False
        except Exception as e:
            self.logger.error(f"meme-generator 安装异常: {e}")
            return False

    def _check_meme_generator_installed(self) -> bool:
        try:
            import meme_generator
            return True
        except ImportError:
            return False

    async def _check_api_running(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.meme_api_url}/memes/list",
                    timeout=5.0
                )
                return response.status_code == 200
        except:
            return False

    async def _start_api_server(self) -> bool:
        if await self._check_api_running():
            self.logger.info("meme-generator API 服务已在运行")
            return True

        if not self._check_meme_generator_installed():
            self.logger.info("未检测到 meme-generator，正在自动安装...")
            if not await self._install_meme_generator():
                return False

        try:
            self.logger.info(f"正在启动 meme-generator API 服务 (端口: {self.api_port})...")
            
            self.api_process = subprocess.Popen(
                [sys.executable, "-m", "meme_generator.app"],
                env={**os.environ, "MEME_PORT": str(self.api_port)},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            
            for _ in range(30):
                await asyncio.sleep(1)
                if await self._check_api_running():
                    self._api_started_by_plugin = True
                    self.logger.info("meme-generator API 服务启动成功")
                    return True
            
            self.logger.error("meme-generator API 服务启动超时")
            return False
            
        except Exception as e:
            self.logger.error(f"启动 meme-generator API 服务失败: {e}")
            return False

    def _stop_api_server(self):
        if self.api_process and self._api_started_by_plugin:
            try:
                self.api_process.terminate()
                self.api_process.wait(timeout=5)
                self.logger.info("meme-generator API 服务已停止")
            except subprocess.TimeoutExpired:
                self.api_process.kill()
                self.logger.info("meme-generator API 服务已强制停止")
            except Exception as e:
                self.logger.error(f"停止 API 服务时出错: {e}")
            finally:
                self.api_process = None
                self._api_started_by_plugin = False

    async def _init_api(self):
        if self.auto_start:
            success = await self._start_api_server()
            if not success:
                self.logger.warning("自动启动 meme-generator API 失败，请手动启动服务")

    async def initialize(self):
        await self._init_api()

    async def terminate(self):
        self._stop_api_server()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE | filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_message_received(self, event: AstrMessageEvent):
        message_str = event.message_str
        message_chain = event.message_obj.message
        
        if re.search(r"摸头", message_str, re.IGNORECASE):
            at_users = self.extract_at_users(message_chain)
            
            if at_users:
                at_user_id = at_users[0]
                await self.generate_and_send_pat_gif(event, at_user_id)
            else:
                await event.send("❓ 请@一个用户来生成摸头杀GIF")

    def extract_at_users(self, message_chain: List) -> List[str]:
        at_users = []
        for component in message_chain:
            if hasattr(component, 'type') and component.type.name == 'At':
                if hasattr(component, 'qq'):
                    at_users.append(component.qq)
                elif hasattr(component, 'user_id'):
                    at_users.append(component.user_id)
        return at_users

    async def get_user_avatar(self, user_id: str) -> bytes:
        avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
        async with httpx.AsyncClient() as client:
            response = await client.get(avatar_url, timeout=10.0)
            response.raise_for_status()
            return response.content

    async def generate_and_send_pat_gif(self, event: AstrMessageEvent, at_user_id: Optional[str]):
        try:
            if not at_user_id:
                await event.send("❌ 请@一个有效的用户")
                return
            
            if not await self._check_api_running():
                await event.send("❌ meme-generator API 服务未运行，请检查配置或手动启动")
                return
            
            avatar_data = await self.get_user_avatar(at_user_id)
            
            files = [("images", ("avatar.jpg", avatar_data, "image/jpeg"))]
            data = {"texts": "[]", "args": "{}"}
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.petpet_endpoint,
                    files=files,
                    data=data,
                    timeout=30.0
                )
                response.raise_for_status()
                
                gif_data = response.content
                
                await event.send(
                    Image(file=gif_data),
                    message="✨ 摸头杀GIF已生成！"
                )
                
        except httpx.ConnectError:
            await event.send("❌ 无法连接到 meme-generator API，请确认服务已启动")
            self.logger.error("无法连接到 meme-generator API")
        except httpx.RequestError as e:
            await event.send("❌ 生成GIF时网络错误，请稍后重试")
            self.logger.error(f"GIF生成失败: 网络错误 - {e}")
        except httpx.HTTPStatusError as e:
            await event.send("❌ 生成GIF时服务错误，请联系管理员")
            self.logger.error(f"GIF生成失败: HTTP状态错误 - {e}")
        except Exception as e:
            await event.send("❌ 生成GIF时发生未知错误")
            self.logger.error(f"GIF生成失败: 未知错误 - {e}")
