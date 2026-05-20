# memoryd

Python daemon —— `memory-system` 仓库的核心引擎。本地优先的个人记忆系统，给 Claude Code / Codex / OpenClaw 三端 AI 提供同一份会自动学习的记忆底座。

## 安装

```bash
cd /path/to/memory-system/memoryd
uv venv && source .venv/bin/activate
uv pip install -e .
```

入口三个：

- `memoryd` —— 主 CLI（capture / search / list / sync / sensitive / setup ...）
- `memoryd-mcp` —— 19 个 `mem_*` MCP 工具的 stdio + http server
- `memoryd-server` —— 旧版单工具 MCP server（向后兼容）

## 完整文档

不在这里。看仓库根 [README.md](../README.md) + 文档站：

**https://EthanQC.github.io/memory-system/**

- [让 AI 帮你装](https://EthanQC.github.io/memory-system/user/install-via-ai/)
- [5 分钟开始](https://EthanQC.github.io/memory-system/getting-started/quickstart/)
- [CLI 参考](https://EthanQC.github.io/memory-system/reference/cli/) · [MCP 工具](https://EthanQC.github.io/memory-system/reference/mcp-tools/)
- [架构全景](https://EthanQC.github.io/memory-system/architecture/overview/)

## 跑测试

```bash
uv run pytest -v
```

具体测试组织 + 覆盖率见 [开发 · 测试](https://EthanQC.github.io/memory-system/development/testing/)。

## License

MIT（同仓库根 `LICENSE`）。fork 自上游的文件在文件头标注 path + 上游 license。
