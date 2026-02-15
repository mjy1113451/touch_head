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


TRIGGER_WORD = "\u6478\u6478"
DEFAULT_CONFIG = {
    "interval": 0.06,
}


@register("astrbot_plugin_petpet", "codex", "petpet gif plugin", "1.0.1")
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
        logger.info("[petpet] plugin loaded, cleanup task started")
        missing = self._missing_assets()
        if missing:
            logger.error(
                f"[petpet] missing assets in {self.assets_dir}: {', '.join(missing)}"
            )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = self._get_text(event).strip()
        if not text:
            return

        if text.startswith(".petset"):
            if not await self._is_admin_or_owner(event):
                yield event.plain_result("\u4f60\u6ca1\u6709\u6743\u9650\u4f7f\u7528\u8be5\u547d\u4ee4\uff08\u4ec5\u673a\u5668\u4eba\u7ba1\u7406\u5458\u6216\u7fa4\u4e3b\uff09\u3002")
                return
            msg = self._handle_petset(text)
            yield event.plain_result(msg)
            return

        if not (text == TRIGGER_WORD or text.startswith(TRIGGER_WORD + " ")):
            return

        missing = self._missing_assets()
        if missing:
            logger.error(
                f"[petpet] assets missing in {self.assets_dir}: {', '.join(missing)}"
            )
            yield event.plain_result(
                "petpet \u7d20\u6750\u7f3a\u5931\uff0c\u8bf7\u68c0\u67e5\u63d2\u4ef6\u76ee\u5f55 "
                "data/petpet/frame0~4.png \u662f\u5426\u5b58\u5728"
            )
            return

        target_user_id = self._resolve_target_user_id(event)
        if not target_user_id:
            yield event.plain_result("\u8bf7\u4f7f\u7528\u201c\u6478\u6478 @\u67d0\u4eba\u201d\uff0c\u6216\u56de\u590d\u67d0\u4eba\u6d88\u606f\u540e\u53d1\u9001\u201c\u6478\u6478\u201d\u3002")
            return

        avatar = await self._resolve_avatar(event, target_user_id)
        if avatar is None:
            yield event.plain_result("\u672a\u80fd\u83b7\u53d6\u76ee\u6807\u5934\u50cf\uff08\u4ec5\u652f\u6301\u672c\u5730\u8def\u5f84/\u5b57\u8282/base64\uff0c\u4e0d\u8fdb\u884c\u7f51\u7edc\u4e0b\u8f7d\uff09\u3002")
            return

        try:
            gif_path = await asyncio.to_thread(
                self._build_petpet_gif, avatar, float(self.config["interval"])
            )
        except Exception:
            logger.exception("[petpet] gif generation failed")
            yield event.plain_result("\u751f\u6210 petpet GIF \u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002")
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
                logger.exception("[petpet] failed to read config.json, using defaults")
        self._normalize_and_save_config(cfg)
        return self.config

    def _normalize_and_save_config(self, cfg: dict):
        try:
            interval = float(cfg.get("interval", DEFAULT_CONFIG["interval"]))
        except Exception:
            interval = DEFAULT_CONFIG["interval"]
        interval = max(0.02, min(1.0, interval))
        self.config = {
            "trigger": TRIGGER_WORD,
            "interval": interval,
        }
        try:
            self.config_path.write_text(
                json.dumps(self.config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("[petpet] failed to write config.json")

    def _handle_petset(self, text: str) -> str:
        m = re.match(r"^\.petset\s+\u901f\u5ea6\s+(.+?)\s*$", text)
        if not m:
            return "\u7528\u6cd5\uff1a.petset \u901f\u5ea6 0.06"

        value = m.group(1).strip()
        try:
            interval = float(value)
        except Exception:
            return "\u901f\u5ea6\u5fc5\u987b\u662f\u6570\u5b57\uff0c\u4f8b\u5982\uff1a.petset \u901f\u5ea6 0.06"
        if interval <= 0:
            return "\u901f\u5ea6\u5fc5\u987b\u5927\u4e8e 0\u3002"
        self.config["interval"] = interval
        self._normalize_and_save_config(self.config)
        return f"\u5df2\u8bbe\u7f6e\u6478\u5934\u901f\u5ea6\uff08\u5e27\u95f4\u9694\uff09\u4e3a {self.config['interval']:.3f}s"

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
            seg_type = seg.__class__.__name__.lower()
            if seg_type == "at" and at_uid is None:
                at_uid = self._first_attr(seg, ("qq", "user_id", "id", "target"))
            if seg_type in {"reply", "quote"} and reply_uid is None:
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
        for path in paths:
            cur = raw
            ok = True
            for key in path:
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
            for key in ("avatar", "avatar_url", "face", "icon"):
                value = getattr(sender, key, None)
                if value:
                    candidates.append(value)

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
            path = Path(text)
            if path.exists() and path.is_file():
                try:
                    return Image.open(path).convert("RGBA")
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
            with Image.open(self.assets_dir / f"frame{i}.png") as hand_img:
                hand = hand_img.convert("RGBA")
            canvas = Image.new("RGBA", hand.size, (255, 255, 255, 0))
            left, top, right, bottom = boxes[i]
            width, height = max(1, right - left), max(1, bottom - top)
            face = avatar.resize((width, height), Image.Resampling.LANCZOS)
            canvas.paste(face, (left, top), face)
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
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[petpet] cleanup loop failed")
            await asyncio.sleep(3600)

    def _cleanup_old_gifs(self, max_age_seconds: int):
        now = time.time()
        for file_path in self.output_dir.glob("petpet_*.gif"):
            try:
                if now - file_path.stat().st_mtime > max_age_seconds:
                    file_path.unlink(missing_ok=True)
            except Exception:
                continue

    def _missing_assets(self) -> list[str]:
        missing = []
        for i in range(5):
            filename = f"frame{i}.png"
            if not (self.assets_dir / filename).exists():
                missing.append(filename)
        return missing

    def _image_result(self, event: AstrMessageEvent, path: Path):
        if hasattr(event, "make_result"):
            result = event.make_result()
            if hasattr(result, "image"):
                result.image(str(path))
                return result
        return event.image_result(str(path))

    def _get_text(self, event: AstrMessageEvent) -> str:
        value = getattr(event, "message_str", None)
        if isinstance(value, str):
            return value
        msg_obj = getattr(event, "message_obj", None)
        value2 = getattr(msg_obj, "message_str", "")
        return value2 if isinstance(value2, str) else ""

    @staticmethod
    def _first_attr(obj: Any, keys: tuple[str, ...]) -> Optional[Any]:
        if obj is None:
            return None
        for key in keys:
            value = getattr(obj, key, None)
            if value is not None and value != "":
                return value
        return None
