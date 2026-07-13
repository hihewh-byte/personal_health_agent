#!/usr/bin/env python3
"""P0 selfcheck: Response Language Policy (RLP) resolution + directive injection."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.chat_message_stack import PHA_MEDICAL_SOUL_SYSTEM_PROMPT
from pha.response_language import (
    append_language_directive,
    build_language_directive,
    detect_explicit_locale_request,
    detect_message_locale_heuristic,
    resolve_response_locale,
)


def main() -> int:
    ok = True

    if resolve_response_locale("hello", request_locale=None) != "en":
        print("FAIL default locale should be en")
        ok = False

    os.environ["PHA_RESPONSE_LOCALE"] = "zh"
    if resolve_response_locale("hi", request_locale=None) != "zh":
        print("FAIL PHA_RESPONSE_LOCALE=zh")
        ok = False
    os.environ.pop("PHA_RESPONSE_LOCALE", None)

    if resolve_response_locale("我的 HRV 正常吗", request_locale="en") != "en":
        print("FAIL request_locale=en should beat heuristic zh")
        ok = False

    if resolve_response_locale("Analyze this report", request_locale="zh") != "zh":
        print("FAIL request_locale=zh should beat heuristic en")
        ok = False

    if detect_explicit_locale_request("reply in English please") != "en":
        print("FAIL explicit en")
        ok = False
    if detect_explicit_locale_request("请用中文回答") != "zh":
        print("FAIL explicit zh")
        ok = False
    if resolve_response_locale("请用英文回答我的血脂", request_locale="zh") != "en":
        print("FAIL explicit should beat request_locale")
        ok = False

    if detect_message_locale_heuristic("What is my LDL trend?") != "en":
        print("FAIL heuristic en")
        ok = False
    if detect_message_locale_heuristic("我的睡眠深睡比例正常吗") != "zh":
        print("FAIL heuristic zh")
        ok = False
    if detect_message_locale_heuristic("谢谢") != "zh":
        print("FAIL short pure-CJK close token should be zh")
        ok = False
    if detect_message_locale_heuristic("好的") != "zh":
        print("FAIL short pure-CJK ack should be zh")
        ok = False
    if resolve_response_locale("谢谢", request_locale=None) != "zh":
        print("FAIL resolve 谢谢 should be zh (not OSS en default)")
        ok = False
    if detect_message_locale_heuristic("ok") is not None:
        print("FAIL short Latin ack should defer to env/default")
        ok = False

    en_dir = build_language_directive("en")
    zh_dir = build_language_directive("zh")
    if "English" not in en_dir or "简体中文" not in zh_dir:
        print("FAIL directive content")
        ok = False

    soul = PHA_MEDICAL_SOUL_SYSTEM_PROMPT.strip()
    assembled = append_language_directive(soul, "en")
    if "默认使用中文" in soul or "请用中文" in soul:
        print("FAIL soul still contains Chinese language mandate")
        ok = False
    if "RESPONSE LANGUAGE" not in assembled:
        print("FAIL missing RESPONSE LANGUAGE block")
        ok = False
    expected_suffix = build_language_directive("en").strip()
    if not assembled.endswith(expected_suffix):
        print("FAIL directive should be appended at end")
        ok = False

    from pha.presentation_filter import polish_user_visible_reply

    zh_leak = polish_user_visible_reply(
        "Patient State shows 低密度脂蛋白 (LDL) elevated.",
        locale="en",
    )
    if "低密度脂蛋白" in zh_leak or "健康记录" in zh_leak:
        print("FAIL en polish should not leave Chinese lipid labels or 健康记录")
        ok = False
    if "health records" not in zh_leak:
        print("FAIL en polish should map Patient State to health records")
        ok = False

    zh_ok = polish_user_visible_reply("Patient State LDL high", locale="zh")
    if "健康记录" not in zh_ok:
        print("FAIL zh polish should map Patient State to 健康记录")
        ok = False

    print("pha_response_language_selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
