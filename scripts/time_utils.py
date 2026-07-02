"""JST (日本標準時, UTC+9) の日時ユーティリティ。

GitHub Actions 上でも常に JST で時刻を扱うために使用する。
"""
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9), "JST")


def now_jst() -> datetime:
    """現在時刻を JST で返す。"""
    return datetime.now(JST)


def today_jst() -> datetime:
    """本日の 0:00 JST を返す。"""
    return now_jst().replace(hour=0, minute=0, second=0, microsecond=0)


def format_jst_datetime(dt: datetime | None = None, fmt: str = "%Y/%m/%d %H:%M") -> str:
    """JST 日時を指定フォーマットの文字列に変換する。dt 省略時は現在時刻。"""
    if dt is None:
        dt = now_jst()
    # tzinfo が無い場合は JST とみなす
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST).strftime(fmt)


def format_jst_iso(dt: datetime | None = None) -> str:
    """JST 日時を ISO 文字列に変換する。"""
    if dt is None:
        dt = now_jst()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST).isoformat()
