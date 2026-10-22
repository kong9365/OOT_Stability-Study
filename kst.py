# -*- coding: utf-8 -*-
"""한국 시간(KST) — 컨테이너 시계 설정(axhub 는 UTC)과 상관없이 세계시+9시간으로 잰다.

알람 실행 시각('매일 07:31')·로그·메일 제목의 시각이 한국 시간이 되게 한다(넘김 파일 oot_export 와 같은 기준).
"""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


def now() -> datetime:
    """지금 한국 시각(시간대 정보 없는 naive datetime — 기존 코드의 datetime.now() 자리에 그대로)."""
    return datetime.now(KST).replace(tzinfo=None)
