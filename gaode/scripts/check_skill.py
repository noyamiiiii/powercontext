#!/usr/bin/env python3
"""SKILL.md 静态校验（不联网、不替代平台真机评测）。

检查项：
  1. frontmatter 可解析，含 name / description
  2. 题面要求的四类信息有对应章节：名称用途场景、工具调用步骤、回答格式、异常处理
  3. 不含疑似密钥（32 位 hex、sk- 前缀、AMAP_ 环境变量赋值）
  4. 正文引用的高德工具名全部在能力白名单内
  5. 表格列数一致；推荐示例表的行数不超过 3
  6. 题面明令的四条硬约束均有明文规则（超时不入表 / 未核实 / 禁止直线距离 / 不超过 3 条）

用法：python scripts/check_skill.py
退出码 0 表示全部通过。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "SKILL.md"

ALLOWED_TOOLS = {
    "maps_around_search",
    "maps_text_search",
    "maps_search_detail",
    "maps_direction_walking",
    "maps_geo",
    "maps_regeocode",
    "maps_distance",
}

REQUIRED_HEADINGS = {
    "名称与场景": ["适用场景"],
    "工具步骤": ["执行流程", "步行路线"],
    "回答格式": ["回答格式"],
    "异常处理": ["异常与降级"],
}

SECRET_PATTERNS = [
    (r"\b[0-9a-f]{32}\b", "32 位 hex 串（疑似高德 Key）"),
    (r"\bsk-[A-Za-z0-9]{10,}", "sk- 前缀密钥"),
    (r"AMAP[A-Z_]*KEY\s*[=:]\s*\S+", "AMAP Key 赋值"),
    (r"<your[_-]?api[_-]?key>", "密钥占位符未清理"),
]

MAX_ROWS_IN_EXAMPLE = 3


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("文件未以 '---' 开头，缺少 YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("找不到 frontmatter 结束标记 '---'")
    block = text[4:end]
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def find_tables(text: str) -> list[tuple[list[list[str]], bool]]:
    """返回所有 markdown 表格：[(表格行列表, 是否位于代码块内), ...]"""
    tables: list[tuple[list[list[str]], bool]] = []
    current: list[list[str]] = []
    in_fence = False
    fenced_at_start = False

    def flush() -> None:
        if len(current) >= 2:
            tables.append((list(current), fenced_at_start))
        current.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            in_fence = not in_fence
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            if not current:
                fenced_at_start = in_fence
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            current.append(cells)
        else:
            flush()
    flush()
    return tables


def is_separator(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c)


def main() -> int:
    if not SKILL.is_file():
        print(f"[FAIL] 找不到文件：{SKILL}")
        return 1

    text = SKILL.read_text(encoding="utf-8")
    problems: list[str] = []
    notes: list[str] = []

    # 1. frontmatter
    try:
        meta = parse_frontmatter(text)
    except ValueError as exc:
        problems.append(f"frontmatter：{exc}")
        meta = {}
    for key in ("name", "description"):
        if not meta.get(key):
            problems.append(f"frontmatter 缺少 `{key}`")
    name = meta.get("name", "")
    if name and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        problems.append(f"name `{name}` 不是小写连字符格式")
    notes.append(f"skill name = {name or '(缺失)'}")

    # 2. 必需章节
    for group, keywords in REQUIRED_HEADINGS.items():
        missing = [k for k in keywords if k not in text]
        if missing:
            problems.append(f"{group}：缺少关键词 {missing}")

    # 3. 密钥
    for pattern, label in SECRET_PATTERNS:
        hit = re.search(pattern, text)
        if hit:
            problems.append(f"疑似泄露 {label}：{hit.group(0)[:24]}…")
    if "API Key" not in text and "密钥" not in text:
        problems.append("缺少“不要在 Skill 中填写密钥”的说明")

    # 4. 工具名白名单
    used = sorted(set(re.findall(r"`(maps_[a-z_]+)", text)))
    unknown = [t for t in used if t not in ALLOWED_TOOLS]
    if unknown:
        problems.append(f"出现白名单外的工具名：{unknown}")
    for required in ("maps_around_search", "maps_direction_walking"):
        if required not in used:
            problems.append(f"缺少赛题指定的工具 {required}")
    notes.append(f"引用工具 {len(used)} 个：{', '.join(used)}")

    # 5. 表格
    tables = find_tables(text)
    example_rows: list[int] = []
    for idx, (table, fenced) in enumerate(tables, 1):
        header = table[0]
        rows = table[1:]
        if rows and is_separator(rows[0]):
            rows = rows[1:]
        label = f"{'输出模板表' if fenced else '表格'} #{idx}"
        for r in rows:
            if len(r) != len(header):
                problems.append(
                    f"{label}列数不一致：表头 {len(header)} 列，行 `{r[0]}` 为 {len(r)} 列"
                )
                break
        if any("步行距离" in c for c in header):
            example_rows.append(len(rows))
            notes.append(f"{label}：{len(header)} 列 × {len(rows)} 行")
            if len(rows) > MAX_ROWS_IN_EXAMPLE:
                problems.append(f"{label}有 {len(rows)} 行，超过 3 条上限")
    if len(example_rows) < 2:
        problems.append("推荐结果表应同时出现在输出模板和完整范例中")

    # 6. 硬约束
    constraints = {
        "超时地点不得入表": ["超出上限", "不计入推荐"],
        "未核实标注": ["未核实"],
        "禁止直线距离替代": ["直线距离"],
        "数量不超过 3": ["最多 3"],
    }
    for label, keys in constraints.items():
        missing = [k for k in keys if k not in text]
        if missing:
            problems.append(f"硬约束「{label}」缺少表述：{missing}")

    # 输出
    print(f"校验文件：{SKILL}")
    for note in notes:
        print(f"  · {note}")
    if problems:
        print(f"\n[FAIL] {len(problems)} 项不通过：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n[PASS] 全部检查通过。注意：静态校验不等于平台评测，真机效果需在评测端验证。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
