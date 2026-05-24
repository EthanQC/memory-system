"""LLM prompt for generating HANDOFF.md.

HANDOFF.md is a per-project "shift change" document — a structured
snapshot of *current state + next steps* that any human or AI session
can pick up cold. Lives in the project root and ships with git
(unlike memoryd's user-level private memories).

Structure target (6 mandatory blocks):
  1. TL;DR — one paragraph
  2. 当前状态 — done / in-progress / not-started
  3. 下一步立即要做的事 — concrete, actionable
  4. 关键决策记录 — choices + WHY
  5. 文件结构 / 入口 — code map
  6. 已知坑 / 待办 — risks, gotchas, todos

The prompt below also enforces 5 anti-patterns:
  1. Don't dump conversation history
  2. Don't be abstract — be specific to file/function/command
  3. Always lead with TL;DR
  4. Every decision must carry its "why"
  5. (positioning) the output goes to project root, not deep paths
"""
from __future__ import annotations

from ..llm.base import LLMMessage


HANDOFF_MAX_CHARS = 4000


HANDOFF_SYSTEM = f"""你不是在跟用户对话。你在为 memory-system 生成一份 **HANDOFF.md** —— \
让下一个会话 / 接手者 10 分钟进入状态的"交接班记录"。

输出**严格 markdown**，不要 JSON、不要 wrapper、不要解释。直接从 `# HANDOFF ...` 开头。

# 6 区块结构（按顺序，每个都必须出现）

```
# HANDOFF — <项目名> (<日期 YYYY-MM-DD>)

## 1. TL;DR
（一段话。让人扫一眼就懂"我们在做 X，已经完成 Y，当前卡在 Z，下一步是 W"。）

## 2. 当前状态
- ✅ 已完成：<具体到文件 / 函数 / commit>
- 🟡 进行中：<具体到哪个文件、哪个函数；如无可写"无"，但不要写空>
- ⏳ 未开始：<剩下范围>

## 3. 下一步立即要做的事
**优先级 1**：<具体到能直接动手的指令，例如 "在 X.py 实现 Y，参考 Z 的写法">
**优先级 2**：…

## 4. 关键决策记录
- <决策>：→ <**为什么**这么定，引用约束或踩过的坑>
- 已经否决的方案：<避免新人再踩>

## 5. 文件结构 / 入口
- `path/to/file.py` — 一句话说明它干什么
- 关键函数：`file.py:123` 的 `func_name()`

## 6. 已知坑 / 待办
- ⚠️ <坑：例如"Safari 不支持 Local Font Access API"，或"X 在 Y 平台没测过">
- TODO: <临时记号>
- BUG: <已知问题>
```

# 反模式（绝对不要这样写）

1. ❌ 不要 dump 对话："今天我们聊了 X，然后讨论了 Y..." —— 接手者不需要历史，需要**当前状态**
2. ❌ 不要抽象："完善字体库功能" —— 改成 "在 components/FontLibrary/index.tsx 实现拖拽上传 + IndexedDB 存储，参考 AssetLibrary"
3. ❌ 不要省 TL;DR —— 第一段必须是一段话能让人 get 全貌
4. ❌ 决策不能只有结论：写 "用 pnpm" 会让下一个人怀疑"为什么不用 npm"。**永远带 why**
5. ❌ 不要编造：素材里没出现的事实、文件、决策一律不写

# 来源信号说明

下面 user 消息里你会拿到 4 类素材：
- **identity 摘要** — 用户长期画像（角色、技术栈、偏好）
- **最近 decision 类记忆** — 已经做过的有 why 的决策
- **最近 warning 类记忆** — 已知的坑
- **最近 session 摘要** — 最近会话的工作内容

这些是你能依据的**唯一**素材。素材里没有的就不要编。
如果某个区块**找不到素材**（例如"进行中"没有任何 session 提到），就**简短写"无"或省略**——
**不要为了凑齐 6 区块而瞎编**。

# 长度

总长 ≤ {HANDOFF_MAX_CHARS} 中文字符。HANDOFF 是工作文档，不是博客。
"""


def render_handoff_prompt(
    *,
    project_name: str,
    today_iso: str,
    identity_snippet: str,
    decisions: list[dict],
    warnings: list[dict],
    sessions: list[dict],
    entities: list[dict],
) -> list[LLMMessage]:
    """Build messages list for HANDOFF generation.

    Args:
        project_name: short label (typically scope name or cwd dir name)
        today_iso:    YYYY-MM-DD for the header
        identity_snippet: identity.md excerpt or empty string
        decisions:    rows like {"title", "body_path"|"body", "created_at"}
        warnings:     same shape
        sessions:     same shape, sessions only
        entities:     [{"name", "mention_count"}, ...]
    """
    def _format_memory_list(label: str, rows: list[dict]) -> str:
        if not rows:
            return f"## {label}\n（无）\n"
        out = [f"## {label}"]
        for r in rows:
            date = (r.get("created_at") or "")[:10]
            title = r.get("title") or r.get("slug") or "?"
            body = (r.get("body") or "").strip()
            if body:
                # Clip per-entry body to keep prompt fits
                body_clip = body[:400]
                out.append(f"- [{date}] {title}\n  {body_clip}")
            else:
                out.append(f"- [{date}] {title}")
        return "\n".join(out) + "\n"

    identity_block = (
        f"## 用户画像摘要\n{identity_snippet}\n"
        if identity_snippet.strip()
        else "## 用户画像摘要\n（空，跳过）\n"
    )

    entities_block = ""
    if entities:
        chips = [f"{e.get('name')} ({e.get('mention_count', 0)})" for e in entities[:10]]
        entities_block = "## 最近常提及的实体\n" + " · ".join(chips) + "\n"

    user = (
        f"# 项目名\n{project_name}\n\n"
        f"# 今日日期\n{today_iso}\n\n"
        f"{identity_block}\n"
        f"{_format_memory_list('最近 decision 类记忆', decisions)}\n"
        f"{_format_memory_list('最近 warning 类记忆', warnings)}\n"
        f"{_format_memory_list('最近 session 摘要', sessions)}\n"
        f"{entities_block}\n"
        f"请按 system 指定的 6 区块结构生成 HANDOFF.md。直接输出 markdown，不要 wrapper。"
    )

    return [
        LLMMessage(role="system", content=HANDOFF_SYSTEM),
        LLMMessage(role="user", content=user),
    ]
