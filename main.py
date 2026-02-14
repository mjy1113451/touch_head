import io
import math
import asyncio
import traceback
import base64
from pathlib import Path
from typing import Optional

import aiohttp
from PIL import Image, ImageDraw, ImageSequence

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image as ImgComp

try:
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
except ImportError:
    AiocqhttpMessageEvent = None


@register("touch_head", "摸头杀插件", "当用户拍机器人时自动生成并发送摸头GIF动图", "1.1.0")
class TouchHeadPlugin(Star):
    QQ_AVATAR_URL = "https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640&img_type=jpg"
    QQ_AVATAR_URL_ALT = "https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
    
    def __init__(self, context: Context):
        super().__init__(context)
        self.data_dir = Path("data/touch_head")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session
    
    async def initialize(self):
        logger.info("摸头杀插件初始化完成")
    
    async def _get_qq_avatar(self, user_id: str) -> Optional[Image.Image]:
        urls = [
            self.QQ_AVATAR_URL.format(user_id=user_id),
            self.QQ_AVATAR_URL_ALT.format(user_id=user_id),
        ]
        
        for url in urls:
            try:
                session = await self._get_session()
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                async with session.get(
                    url, 
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers=headers
                ) as resp:
                    logger.info(f"请求头像URL: {url}, 状态码: {resp.status}")
                    if resp.status == 200:
                        img_data = await resp.read()
                        if len(img_data) > 0:
                            img = Image.open(io.BytesIO(img_data))
                            return img.convert("RGBA")
                        else:
                            logger.warning(f"头像数据为空: {url}")
            except asyncio.TimeoutError:
                logger.error(f"获取QQ头像超时: {url}")
            except aiohttp.ClientError as e:
                logger.error(f"网络请求失败: {e}")
            except Exception as e:
                logger.error(f"获取QQ头像失败: {e}\n{traceback.format_exc()}")
        
        return None
    
    def _generate_petpet_gif(self, avatar: Image.Image) -> bytes:
        canvas_size = 256
        avatar_size = 180
        avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        
        frames = []
        num_frames = 20
        duration = 50
        
        for i in range(num_frames):
            canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
            
            phase = (i / num_frames) * 2 * math.pi
            
            squeeze_factor = 0.08 * math.sin(phase)
            offset_y = 8 * math.sin(phase)
            
            squeeze_w = int(avatar_size * (1 + squeeze_factor))
            squeeze_h = int(avatar_size * (1 - squeeze_factor * 0.5))
            
            squeezed = avatar.resize((squeeze_w, squeeze_h), Image.Resampling.LANCZOS)
            
            paste_x = (canvas_size - squeeze_w) // 2
            paste_y = (canvas_size - squeeze_h) // 2 + int(offset_y)
            
            canvas.paste(squeezed, (paste_x, paste_y), squeezed)
            
            hand_frame = self._draw_hand_frame(i, num_frames, canvas_size)
            canvas = Image.alpha_composite(canvas, hand_frame)
            
            frames.append(canvas.convert("RGB"))
        
        output = io.BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            disposal=2,
        )
        return output.getvalue()
    
    def _draw_hand_frame(self, frame_idx: int, total_frames: int, size: int) -> Image.Image:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        
        phase = (frame_idx / total_frames) * 2 * math.pi
        
        hand_color = (255, 230, 210, 230)
        outline_color = (220, 190, 170, 255)
        
        center_x = size // 2
        base_y = 30
        
        hand_offset_x = 10 * math.sin(phase)
        hand_offset_y = 5 * math.sin(phase + math.pi / 4)
        
        palm_x = center_x + int(hand_offset_x)
        palm_y = base_y + int(hand_offset_y)
        
        palm_w, palm_h = 70, 55
        draw.ellipse(
            [palm_x - palm_w//2, palm_y - palm_h//2,
             palm_x + palm_w//2, palm_y + palm_h//2],
            fill=hand_color,
            outline=outline_color,
            width=3
        )
        
        finger_data = [
            (-28, 25, 18, 40),
            (-10, 30, 16, 48),
            (8, 30, 16, 50),
            (26, 25, 16, 45),
            (38, 10, 14, 30),
        ]
        
        for fx, fy, fw, fh in finger_data:
            finger_x = palm_x + fx
            finger_y = palm_y + fy
            
            finger_offset = 3 * math.sin(phase + fx * 0.1)
            finger_y += int(finger_offset)
            
            draw.ellipse(
                [finger_x - fw//2, finger_y,
                 finger_x + fw//2, finger_y + fh],
                fill=hand_color,
                outline=outline_color,
                width=2
            )
        
        thumb_x = palm_x - 35
        thumb_y = palm_y + 5
        thumb_w, thumb_h = 22, 35
        
        draw.ellipse(
            [thumb_x - thumb_w//2, thumb_y,
             thumb_x + thumb_w//2, thumb_y + thumb_h],
            fill=hand_color,
            outline=outline_color,
            width=2
        )
        
        return canvas
    
    @filter.command("摸头")
    async def touch_head_cmd(self, event: AstrMessageEvent):
        sender_id = event.get_sender_id()
        logger.info(f"手动触发摸头: {sender_id}")
        
        avatar = await self._get_qq_avatar(sender_id)
        if avatar is None:
            yield event.plain_result("获取头像失败，请稍后重试~")
            return
        
        gif_data = self._generate_petpet_gif(avatar)
        gif_base64 = base64.b64encode(gif_data).decode("utf-8")
        
        if AiocqhttpMessageEvent and isinstance(event, AiocqhttpMessageEvent):
            try:
                client = event.bot
                group_id = event.get_group_id()
                image_data = f"base64://{gif_base64}"
                if group_id:
                    await client.api.call_action(
                        "send_group_msg",
                        group_id=group_id,
                        message=[{"type": "image", "data": {"file": image_data}}]
                    )
                else:
                    await client.api.call_action(
                        "send_private_msg",
                        user_id=int(sender_id),
                        message=[{"type": "image", "data": {"file": image_data}}]
                    )
                logger.info(f"摸头GIF已发送给用户 {sender_id}")
            except Exception as e:
                logger.error(f"发送摸头GIF失败: {e}")
                yield event.plain_result("发送失败~")
                return
        else:
            yield event.plain_result("当前平台不支持发送图片~")
            return
        
        yield event.plain_result("")
    
    @filter.platform_adapter_type("aiocqhttp")
    async def on_aiocqhttp_event(self, event: AstrMessageEvent):
        if AiocqhttpMessageEvent is None:
            return
        
        if not isinstance(event, AiocqhttpMessageEvent):
            return
        
        raw_event = getattr(event, "raw_event", None)
        if raw_event is None:
            return
        
        post_type = raw_event.get("post_type")
        if post_type != "notice":
            return
        
        notice_type = raw_event.get("notice_type")
        if notice_type != "notify":
            return
        
        sub_type = raw_event.get("sub_type")
        if sub_type != "poke":
            return
        
        target_id = raw_event.get("target_id")
        user_id = raw_event.get("user_id")
        group_id = raw_event.get("group_id")
        
        if target_id is None or user_id is None:
            return
        
        bot_id = str(raw_event.get("self_id", ""))
        if str(target_id) != bot_id:
            return
        
        logger.info(f"检测到拍一拍事件: 用户 {user_id} 拍了机器人 (群: {group_id})")
        
        avatar = await self._get_qq_avatar(str(user_id))
        if avatar is None:
            logger.warning(f"获取用户 {user_id} 头像失败")
            return
        
        gif_data = self._generate_petpet_gif(avatar)
        gif_base64 = base64.b64encode(gif_data).decode("utf-8")
        image_data = f"base64://{gif_base64}"
        
        try:
            client = event.bot
            if group_id:
                await client.api.call_action(
                    "send_group_msg",
                    group_id=group_id,
                    message=[{"type": "image", "data": {"file": image_data}}]
                )
            else:
                await client.api.call_action(
                    "send_private_msg",
                    user_id=user_id,
                    message=[{"type": "image", "data": {"file": image_data}}]
                )
            logger.info(f"摸头GIF已发送给用户 {user_id}")
        except Exception as e:
            logger.error(f"发送摸头GIF失败: {e}")
    
    async def terminate(self):
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("摸头杀插件已卸载")
