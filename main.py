import asyncio
import sqlite3
from contextlib import suppress
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astral import Observer
from astral.sun import sunrise
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools

PLUGIN_NAME = "astrbot_plugin_night_owl"
CHECK_INTERVAL = 60
SEND_TIMEOUT = 20


class NightOwl(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        try:
            self.zone = ZoneInfo(config["timezone"].strip())
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("时区必须是有效的 IANA 时区，例如 Asia/Taipei。") from exc

        latitude = config["latitude"]
        longitude = config["longitude"]
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("纬度须介于 -90 和 90 之间，经度须介于 -180 和 180 之间。")
        self.observer = Observer(latitude=latitude, longitude=longitude)
        self._sunrise_day: date | None = None
        self._sunrise_timestamp: float | None = None
        self._task: asyncio.Task | None = None

    async def initialize(self):
        path = StarTools.get_data_dir(PLUGIN_NAME) / "night_owl.sqlite3"
        self._db = sqlite3.connect(path)
        try:
            with self._db:
                self._db.execute("""
                    CREATE TABLE IF NOT EXISTS candidates (
                        day TEXT NOT NULL,
                        platform_id TEXT NOT NULL,
                        group_id TEXT NOT NULL,
                        destination TEXT NOT NULL,
                        nickname TEXT NOT NULL,
                        message_at REAL NOT NULL,
                        announced INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (day, platform_id, group_id)
                    )
                """)
        except sqlite3.Error:
            self._db.close()
            raise
        self._task = asyncio.create_task(self._run(), name=PLUGIN_NAME)

    async def terminate(self):
        if self._task is None:
            return
        self._task.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await self._task
        finally:
            self._task = None
            self._db.close()

    def _sunrise_at(self, day: date) -> float | None:
        if self._sunrise_day != day:
            self._sunrise_day = day
            try:
                self._sunrise_timestamp = sunrise(
                    self.observer, date=day, tzinfo=self.zone
                ).timestamp()
            except ValueError as exc:
                logger.warning(f"熬夜大王：{day} 无可用日出时间，跳过当天评选。{exc}")
                self._sunrise_timestamp = None
        return self._sunrise_timestamp

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)
    async def record_last_sender(self, event: AstrMessageEvent):
        """记录群里日出前最新一条消息的发送者。"""
        platform = event.get_platform_name()
        if self._task is None or platform in {"qq_official", "qq_official_webhook"}:
            return

        now = datetime.now(self.zone)
        day = now.date()
        sunrise_at = self._sunrise_at(day)
        if sunrise_at is None or now.timestamp() >= sunrise_at:
            return

        message_at = event.message_obj.timestamp
        raw = getattr(event.message_obj, "raw_message", None)
        if platform == "aiocqhttp" and isinstance(raw, dict):
            if raw.get("post_type") != "message":
                return
            # OneBot has the original send time. AstrBot may stamp it on receipt.
            sent_at = raw.get("time")
            if isinstance(sent_at, int):
                message_at = sent_at
        start = datetime.combine(day, time.min, tzinfo=self.zone).timestamp()
        if not start <= message_at < sunrise_at:
            return

        group_id = event.get_group_id()
        sender_id = event.get_sender_id()
        if (
            not group_id
            or not sender_id
            or str(sender_id) == str(event.get_self_id())
            or not event.get_messages()
        ):
            return
        nickname = " ".join((event.get_sender_name() or "").split()) or sender_id

        try:
            with self._db:
                self._db.execute(
                    """
                    INSERT INTO candidates
                        (day, platform_id, group_id, destination, nickname, message_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (day, platform_id, group_id) DO UPDATE SET
                        destination = excluded.destination,
                        nickname = excluded.nickname,
                        message_at = excluded.message_at
                    WHERE candidates.announced = 0
                        AND excluded.message_at >= candidates.message_at
                    """,
                    (
                        day.isoformat(),
                        event.get_platform_id(),
                        group_id,
                        event.unified_msg_origin,
                        nickname,
                        message_at,
                    ),
                )
        except sqlite3.Error:
            logger.exception("熬夜大王：写入候选人失败。")

    async def _run(self):
        last_cleanup = None
        while True:
            now = datetime.now(self.zone)
            day = now.date()
            day_key = day.isoformat()
            delay = CHECK_INTERVAL
            try:
                if last_cleanup != day:
                    with self._db:
                        self._db.execute(
                            "DELETE FROM candidates WHERE day < ?", (day_key,)
                        )
                    last_cleanup = day

                sunrise_at = self._sunrise_at(day)
                if sunrise_at is not None:
                    remaining = sunrise_at - now.timestamp()
                    if remaining <= 0:
                        await self._announce(day, sunrise_at)
                    else:
                        delay = min(CHECK_INTERVAL, remaining)
            except sqlite3.Error:
                logger.exception("熬夜大王：处理日出评选记录失败。")
            await asyncio.sleep(delay)

    async def _announce(self, day: date, sunrise_at: float):
        day_key = day.isoformat()
        pending = self._db.execute(
            """
            SELECT platform_id, group_id, destination, nickname
            FROM candidates WHERE day = ? AND announced = 0 AND message_at < ?
            """,
            (day_key, sunrise_at),
        ).fetchall()
        for platform_id, group_id, destination, nickname in pending:
            if datetime.now(self.zone).date() != day:
                return
            message = MessageChain().message(
                f"🌅 {nickname}是今天的熬夜大王！恭喜！\n"
                "祝熬夜大王身体健康，今天记得好好补觉！"
            )
            try:
                sent = await asyncio.wait_for(
                    self.context.send_message(destination, message),
                    timeout=SEND_TIMEOUT,
                )
            except Exception as exc:
                logger.warning(
                    f"熬夜大王：无法向 {destination} 发送公告，稍后重试。{exc}"
                )
                continue
            if not sent:
                logger.warning(f"熬夜大王：{destination} 的适配器尚不可用，稍后重试。")
                continue

            with self._db:
                self._db.execute(
                    """
                    UPDATE candidates SET announced = 1, nickname = ''
                    WHERE day = ? AND platform_id = ? AND group_id = ?
                    """,
                    (day_key, platform_id, group_id),
                )
