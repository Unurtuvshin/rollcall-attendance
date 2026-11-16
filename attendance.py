"""Attendance rules for one lesson split into two parts (e.g. 45 + 45 minutes); late/early leave apply to each part."""
from datetime import datetime, timedelta

STATUSES = ("present", "late", "absent", "early", "excused")
LABELS = {"present": "出席", "late": "遅刻", "absent": "欠席", "early": "早退", "excused": "公欠"}


def boundaries(session):
    return tuple(datetime.fromisoformat(f"{session['day']}T{session[key]}+09:00")
                 for key in ("first_start", "first_end", "second_start", "second_end"))


def entry_status(session, entered_at):
    first, _, second, _ = boundaries(session)
    if entered_at < first - timedelta(minutes=30):
        raise ValueError("入室の受付は1コマ目開始の30分前からです。")
    if entered_at <= first:
        return "present", "present"
    if entered_at <= first + timedelta(minutes=15):
        return "late", "present"
    if entered_at <= second:
        return "absent", "present"
    if entered_at <= second + timedelta(minutes=15):
        return "absent", "late"
    return "absent", "absent"


def exit_status(session, entered_at, exited_at):
    first, first_end, _, second_end = boundaries(session)
    if exited_at <= entered_at:
        raise ValueError("退室時刻は入室時刻より後にしてください。")
    initial = entry_status(session, entered_at)
    if exited_at < first_end - timedelta(minutes=15):
        return "absent", "absent"
    if exited_at <= first_end:
        return ("absent" if initial[0] == "absent" else "early"), "absent"
    if exited_at < second_end - timedelta(minutes=15):
        return initial[0], "absent"
    if exited_at <= second_end:
        return initial[0], "absent" if initial[1] == "absent" else "early"
    return initial
