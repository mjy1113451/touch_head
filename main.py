from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from typing import Optional, List
import httpx
import re

@register(
    "pat_head_gif",
    "YourName",
    "一个自动回复'摸头'并生成摸头杀GIF的插件",
    "1.0.0"
)
class PatHeadGifPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 初始化时可以配置一些参数，例如API密钥或默认模板
        self.gif_api_url = "https://api.example.com/pat-head"  # 替换为实际的GIF生成API
        self.api_key = "your_api_key"  # 如果API需要认证
        self.headers = {
            "User-Agent": "AstrBot-PatHeadGif/1.0",
            "Authorization": f"Bearer {self.api_key}"
        }

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE | filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_message_received(self, event: AstrMessageEvent):
        """
        监听所有消息，检查是否包含'摸头'并@用户
        """
        message_str = event.message_str  # 获取消息的纯文本内容<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-5' data-url='https://docs.astrbot.app/dev/star/guides/listen-message-event.html' data-id='turn0fetch0'><span data-allow-html class='source-item-num' data-group-key='source-group-5' data-id='turn0fetch0'><span class='source-item-num-name' data-allow-html>astrbot.app/dev/star/guides/listen-message-event.html</span></span></span>
        message_chain = event.message_obj.message  # 获取完整的消息链<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-6' data-url='https://docs.astrbot.app/dev/star/guides/listen-message-event.html' data-id='turn0fetch0'><span data-allow-html class='source-item-num' data-group-key='source-group-6' data-id='turn0fetch0'><span class='source-item-num-name' data-allow-html>astrbot.app/dev/star/guides/listen-message-event.html</span></span></span>
        
        # 检查是否包含'摸头'关键词（不区分大小写）
        if re.search(r"摸头", message_str, re.IGNORECASE):
            # 提取消息链中的@信息（如果存在）
            at_users = self.extract_at_users(message_chain)
            
            if at_users:
                # 找到被@的用户，生成并发送摸头GIF
                at_user_id = at_users[0]  # 取第一个被@的用户
                await self.generate_and_send_pat_gif(event, at_user_id)
            else:
                # 消息包含'摸头'但未@任何用户，可以提示用户或回复通用摸头GIF
                await event.send("❓ 请@一个用户来生成摸头杀GIF，或直接发送'摸头'获取通用摸头GIF")
                # 这里也可以选择发送一个通用的摸头GIF
                await self.generate_and_send_pat_gif(event, None)

    def extract_at_users(self, message_chain: List) -> List[str]:
        """
        从消息链中提取被@的用户ID列表
        """
        at_users = []
        for component in message_chain:
            # 检查消息段类型是否为At（提及）
            if hasattr(component, 'type') and component.type.name == 'At':
                at_users.append(component.qq)  # 获取被@用户的QQ号
        return at_users

    async def generate_and_send_pat_gif(self, event: AstrMessageEvent, at_user_id: Optional[str]):
        """
        生成摸头GIF并通过event对象发送
        """
        try:
            # 准备API请求参数
            params = {
                "text": "摸摸头~",  # GIF上的文字
                "template": "pat_head",  # 使用的模板ID或名称
            }
            if at_user_id:
                # 如果有@用户，可以尝试获取其昵称或头像，这里简化处理
                params["target_user"] = at_user_id
            
            # 异步调用外部API生成GIF（使用httpx库）
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.gif_api_url,
                    params=params,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()  # 检查请求是否成功
                
                # 假设API返回的是GIF图片的二进制数据
                gif_data = response.content
                
                # 使用AstrBot的消息发送方法发送图片<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-7' data-url='https://docs.astrbot.app/dev/star/guides/listen-message-event.html' data-id='turn0fetch0'><span data-allow-html class='source-item-num' data-group-key='source-group-7' data-id='turn0fetch0'><span class='source-item-num-name' data-allow-html>astrbot.app/dev/star/guides/listen-message-event.html</span></span></span>
                # 注意：这里需要根据AstrBot的发送图片API进行调整
                # 可能需要将图片上传到图床或直接发送二进制数据
                await event.send(
                    message=f"✨ 摸头杀GIF已生成！",
                    image=gif_data  # 假设event.send()支持image参数接收二进制数据
                )
                
        except httpx.RequestError as e:
            await event.send("❌ 生成GIF时网络错误，请稍后重试")
            self.logger.error(f"GIF生成失败: 网络错误 - {e}")
        except httpx.HTTPStatusError as e:
            await event.send("❌ 生成GIF时服务错误，请联系管理员")
            self.logger.error(f"GIF生成失败: HTTP状态错误 - {e}")
        except Exception as e:
            await event.send("❌ 生成GIF时发生未知错误")
            self.logger.error(f"GIF生成失败: 未知错误 - {e}")
