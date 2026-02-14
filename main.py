import asyncio
import base64
import inspect
import io
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


DEFAULT_CONFIG = {
    "trigger": "摸摸",
    "interval": 0.06,
}


@register("astrbot_plugin_petpet", "codex", "摸头杀 petpet GIF 插件", "1.0.0")
class PetPetPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.base_dir = Path(__file__).resolve().parent
        self.assets_dir = self.base_dir / "data" / "petpet"
        self.output_dir = self.assets_dir / "output"
        self.config_path = self.base_dir / "config.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config = self._load_or_create_config()
        self._cleanup_task: Optional[asyncio.Task] = None

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_gif_loop())
        logger.info("[petpet] 插件已加载，定时清理任务已启动")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = self._get_text(event).strip()
        if not text:
            return

        if text.startswith(".petset"):
            if not await self._is_admin_or_owner(event):
                yield event.plain_result("你没有权限使用该命令（仅机器人管理员或群主）。")
                return
            msg = self._handle_petset(text)
            yield event.plain_result(msg)
            return

        trigger = str(self.config.get("trigger", DEFAULT_CONFIG["trigger"])).strip()
        if not (text == trigger or text.startswith(trigger + " ")):
            return

        if not self._assets_ready():
            logger.error("[petpet] 缺少素材，请检查 data/petpet/frame0.png ~ frame4.png")
            yield event.plain_result("petpet 素材缺失，请联系管理员检查插件目录下 data/petpet/frame0~4.png")
            return

        target_user_id = self._resolve_target_user_id(event)
        if not target_user_id:
            yield event.plain_result("请使用“摸摸 @某人”，或回复某人消息后发送“摸摸”。")
            return

        avatar = await self._resolve_avatar(event, target_user_id)
        if avatar is None:
            yield event.plain_result("未能获取目标头像（仅支持本地路径/字节/base64，不进行网络下载）。")
            return

        try:
            gif_path = self._build_petpet_gif(avatar, float(self.config["interval"]))
        except Exception:
            logger.exception("[petpet] 生成 GIF 失败")
            yield event.plain_result("生成 petpet GIF 失败，请稍后再试。")
            return

        yield self._image_result(event, gif_path)

    def _load_or_create_config(self) -> dict:
        cfg = dict(DEFAULT_CONFIG)
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    cfg.update(loaded)
            except Exception:
                logger.exception("[petpet] 读取 config.json 失败，将使用默认配置")
        self._normalize_and_save_config(cfg)
        return self.config

    def _normalize_and_save_config(self, cfg: dict):
        trigger = str(cfg.get("trigger", DEFAULT_CONFIG["trigger"])).strip() or DEFAULT_CONFIG["trigger"]
        try:
            interval = float(cfg.get("interval", DEFAULT_CONFIG["interval"]))
        except Exception:
            interval = DEFAULT_CONFIG["interval"]
        interval = max(0.02, min(1.0, interval))
        self.config = {"trigger": trigger, "interval": interval}
        self.config_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")

    def _handle_petset(self, text: str) -> str:
        m = re.match(r"^\.petset\s+(速度|指令)\s+(.+?)\s*$", text)
        if not m:
            return "用法：.petset 速度 0.06 或 .petset 指令 揉揉"
        key, value = m.group(1), m.group(2).strip()
        if key == "速度":
            try:
                interval = float(value)
            except Exception:
                return "速度必须是数字，例如：.petset 速度 0.06"
            if interval <= 0:
                return "速度必须大于 0。"
            self.config["interval"] = interval
            self._normalize_and_save_config(self.config)
            return f"已设置摸头速度（帧间隔）为 {self.config['interval']:.3f}s"
        if not value:
            return "触发词不能为空。"
        self.config["trigger"] = value
        self._normalize_and_save_config(self.config)
        return f"已设置触发词为：{self.config['trigger']}"

    async def _is_admin_or_owner(self, event: AstrMessageEvent) -> bool:
        sender = getattr(getattr(event, "message_obj", None), "sender", None)
        role = str(getattr(sender, "role", "")).lower()
        if role in {"owner", "admin"}:
            return True

        for name in ("is_admin", "is_owner"):
            checker = getattr(event, name, None)
            if callable(checker):
                try:
                    ret = checker()
                    if inspect.isawaitable(ret):
                        ret = await ret
                    if bool(ret):
                        return True
                except Exception:
                    continue
        return False

    def _resolve_target_user_id(self, event: AstrMessageEvent) -> Optional[str]:
        msg_obj = getattr(event, "message_obj", None)
        chain = getattr(msg_obj, "message", None) or []
        at_uid = None
        reply_uid = None

        for seg in chain:
            t = seg.__class__.__name__.lower()
            if t == "at" and at_uid is None:
                at_uid = self._first_attr(seg, ("qq", "user_id", "id", "target"))
            if t in {"reply", "quote"} and reply_uid is None:
                reply_uid = self._first_attr(seg, ("user_id", "qq", "id", "target"))

        if reply_uid is None:
            raw = getattr(msg_obj, "raw_message", None)
            reply_uid = self._extract_reply_uid(raw)

        return str(at_uid or reply_uid) if (at_uid or reply_uid) else None

    def _extract_reply_uid(self, raw: Any) -> Optional[str]:
        if not isinstance(raw, dict):
            return None
        paths = [
            ("reply", "user_id"),
            ("reply", "sender_id"),
            ("reply", "sender", "user_id"),
            ("quote", "user_id"),
            ("quote", "sender", "user_id"),
            ("reference", "author", "id"),
        ]
        for p in paths:
            cur = raw
            ok = True
            for key in p:
                if not isinstance(cur, dict) or key not in cur:
                    ok = False
                    break
                cur = cur[key]
            if ok and cur:
                return str(cur)
        return None

    async def _resolve_avatar(self, event: AstrMessageEvent, user_id: str) -> Optional[Image.Image]:
        candidates = []
        for name in ("get_user_avatar", "get_avatar", "get_target_avatar", "get_sender_avatar"):
            fn = getattr(event, name, None)
            if callable(fn):
                try:
                    data = fn() if name == "get_sender_avatar" else fn(user_id)
                    if inspect.isawaitable(data):
                        data = await data
                    candidates.append(data)
                except Exception:
                    continue

        sender = getattr(getattr(event, "message_obj", None), "sender", None)
        sender_uid = self._first_attr(sender, ("user_id", "id"))
        if sender and sender_uid and str(sender_uid) == str(user_id):
            for k in ("avatar", "avatar_url", "face", "icon"):
                v = getattr(sender, k, None)
                if v:
                    candidates.append(v)

        for data in candidates:
            img = self._to_image(data)
            if img is not None:
                return img.convert("RGBA")
        return None

    def _to_image(self, data: Any) -> Optional[Image.Image]:
        if data is None:
            return None
        if isinstance(data, Image.Image):
            return data
        if isinstance(data, (bytes, bytearray)):
            try:
                return Image.open(io.BytesIO(data)).convert("RGBA")
            except Exception:
                return None
        if isinstance(data, str):
            text = data.strip()
            if text.startswith("http://") or text.startswith("https://"):
                return None
            if text.startswith("data:image"):
                try:
                    raw = base64.b64decode(text.split(",", 1)[1])
                    return Image.open(io.BytesIO(raw)).convert("RGBA")
                except Exception:
                    return None
            p = Path(text)
            if p.exists() and p.is_file():
                try:
                    return Image.open(p).convert("RGBA")
                except Exception:
                    return None
        return None

    def _build_petpet_gif(self, avatar: Image.Image, interval: float) -> Path:
        boxes = [
            (27, 31, 86, 90),
            (22, 36, 91, 90),
            (18, 41, 95, 90),
            (22, 41, 91, 91),
            (27, 28, 86, 91),
        ]
        frames = []
        for i in range(5):
            hand = Image.open(self.assets_dir / f"frame{i}.png").convert("RGBA")
            canvas = Image.new("RGBA", hand.size, (255, 255, 255, 0))
            l, t, r, b = boxes[i]
            w, h = max(1, r - l), max(1, b - t)
            face = avatar.resize((w, h), Image.Resampling.LANCZOS)
            canvas.paste(face, (l, t), face)
            merged = Image.alpha_composite(canvas, hand)
            frames.append(merged.convert("P", palette=Image.Palette.ADAPTIVE))

        out_path = self.output_dir / f"petpet_{uuid.uuid4().hex}.gif"
        frames[0].save(
            out_path,
            save_all=True,
            append_images=frames[1:],
            duration=max(20, int(interval * 1000)),
            loop=0,
            optimize=False,
            disposal=2,
        )
        return out_path

    async def _cleanup_gif_loop(self):
        while True:
            try:
                self._cleanup_old_gifs(max_age_seconds=6 * 3600)
            except Exception:
                logger.exception("[petpet] 定时清理失败")
            await asyncio.sleep(3600)

    def _cleanup_old_gifs(self, max_age_seconds: int):
        now = time.time()
        for f in self.output_dir.glob("petpet_*.gif"):
            try:
                if now - f.stat().st_mtime > max_age_seconds:
                    f.unlink(missing_ok=True)
            except Exception:
                continue

    def _assets_ready(self) -> bool:
        return all((self.assets_dir / f"frame{i}.png").exists() for i in range(5))

    def _image_result(self, event: AstrMessageEvent, path: Path):
        if hasattr(event, "make_result"):
            result = event.make_result()
            if hasattr(result, "image"):
                result.image(str(path))
                return result
        return event.image_result(str(path))

    def _get_text(self, event: AstrMessageEvent) -> str:
        v = getattr(event, "message_str", None)
        if isinstance(v, str):
            return v
        msg_obj = getattr(event, "message_obj", None)
        v2 = getattr(msg_obj, "message_str", "")
        return v2 if isinstance(v2, str) else ""

    @staticmethod
    def _first_attr(obj: Any, keys: tuple[str, ...]) -> Optional[Any]:
        if obj is None:
            return None
        for k in keys:
            v = getattr(obj, k, None)
            if v is not None and v != "":
                return v
        return None
