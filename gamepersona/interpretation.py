"""Fixed templates, independent levels, and an optional four-letter summary."""
from .storage import content_hash
from .features import DIMENSIONS

PAIRS = (("P", "R"), ("G", "O"), ("M", "N"), ("H", "C"), ("SOLO", "SOCIAL"), ("COMP", "COOP"))
NAMES = {"P": "规划", "R": "反应", "G": "引导", "O": "开放", "M": "机制", "N": "叙事",
         "H": "高压", "C": "舒缓", "SOLO": "独玩", "SOCIAL": "社交", "COMP": "竞争", "COOP": "合作"}


def interpret(percentiles: dict, model: dict) -> dict:
    groups, letters = [], []
    for i, (left, right) in enumerate(PAIRS):
        a, b = percentiles[left]["value"], percentiles[right]["value"]
        if a is None or b is None:
            groups.append({"left": left, "right": right, "difference": None, "intensity": None,
                           "tendency": "pending", "level": None, "text": "参考位置不足，该组待定。"})
            letters.append(None)
            continue
        d = a-b
        tendency = "mixed" if abs(d) <= model["tolerance"] else left if d>0 else right
        level = "double_high" if min(a,b)>=model["high"] else "double_low" if max(a,b)<=model["low"] else None
        text = "两端参考位置接近，呈混合倾向。" if tendency == "mixed" else f"观察证据参考位置相对偏向{NAMES[tendency]}。"
        if level == "double_high":
            text += "两端分别处于较高参考位置。"
        elif level == "double_low":
            text += "两端观察证据参考位置较低，不表示不喜欢。"
        groups.append({"left": left, "right": right, "difference": d, "intensity": (a+b)/2,
                       "tendency": tendency, "level": level, "text": text})
        letters.append(None if tendency == "mixed" else tendency)
    return {"groups": groups, "type": "".join(letters[:4]) if all(letters[:4]) else None}


def share_projection(report: dict) -> dict:
    """Explicit allowlist; no identity, library, or contribution fields."""
    return {"template_version": "share-v1", "label": "评论样本参考分位 · 实验性",
            "type": report["interpretation"]["type"], "groups": report["interpretation"]["groups"],
            "dimensions": {k: {"name": NAMES[k], "value": report['percentiles'][k]["value"], "reason": report['percentiles'][k]["reason"]}
                           for k in DIMENSIONS},
            "versions": report["versions"], "report_sha256": report["report_sha256"]}
