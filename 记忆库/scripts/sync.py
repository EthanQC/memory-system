#!/usr/bin/env python3
"""
筑真记忆系统 - 同步工具
用途：将本机 SQLite-vec 数据库 export 为 JSON / 从 JSON import 回数据库
替代不存在的 HTTP API 端点（C1 修复）

用法:
  sync.py export --output memories.json [--db PATH]
  sync.py import --input  memories.json [--db PATH] [--dry-run]

数据库默认路径按平台自动选：
  Mac:     ~/Library/Application Support/mcp-memory/sqlite_vec.db
  Windows: %LOCALAPPDATA%\\mcp-memory\\sqlite_vec.db
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 依赖 pip install "mcp-memory-service[sqlite]" 已安装
try:
    from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage
    from mcp_memory_service.sync.exporter import MemoryExporter
    from mcp_memory_service.sync.importer import MemoryImporter
except ImportError as e:
    print(f"错误: 需要先安装 mcp-memory-service。运行:", file=sys.stderr)
    print(f"  pip install --user 'mcp-memory-service[sqlite]'", file=sys.stderr)
    print(f"详细: {e}", file=sys.stderr)
    sys.exit(2)


def default_db_path() -> Path:
    """按平台确定默认 SQLite 路径（和 mcp-memory-service 内部逻辑一致）。"""
    env = os.environ.get("MCP_MEMORY_SQLITE_PATH")
    if env:
        return Path(env)

    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "mcp-memory"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "mcp-memory"
    else:
        base = Path.home() / ".local" / "share" / "mcp-memory"
    return base / "sqlite_vec.db"


async def do_export(db_path: Path, output: Path, include_embeddings: bool = False) -> int:
    if not db_path.exists():
        print(f"[WARN] 数据库不存在: {db_path}（首次运行此属正常，export 空 JSON）", file=sys.stderr)
        # 写空 JSON 让 hook 和坚果云都有东西同步
        output.write_text('{"export_metadata": {"note": "empty"}, "memories": []}\n', encoding="utf-8")
        return 0

    storage = SqliteVecMemoryStorage(str(db_path))
    await storage.initialize()
    exporter = MemoryExporter(storage)
    try:
        await exporter.export_to_json(
            output_file=output,
            include_embeddings=include_embeddings,
        )
    finally:
        # 关闭存储连接（SQLite WAL checkpoint 等）
        if hasattr(storage, "close"):
            close = storage.close()
            if asyncio.iscoroutine(close):
                await close
    print(f"[OK] 已 export 到 {output}")
    return 0


async def do_import(db_path: Path, input_file: Path, dry_run: bool = False) -> int:
    if not input_file.exists():
        print(f"[FAIL] JSON 文件不存在: {input_file}", file=sys.stderr)
        return 1

    # 确保父目录存在
    db_path.parent.mkdir(parents=True, exist_ok=True)

    storage = SqliteVecMemoryStorage(str(db_path))
    await storage.initialize()
    importer = MemoryImporter(storage)
    try:
        result = await importer.import_from_json(
            json_files=[input_file],
            deduplicate=True,
            add_source_tags=True,
            dry_run=dry_run,
        )
    finally:
        if hasattr(storage, "close"):
            close = storage.close()
            if asyncio.iscoroutine(close):
                await close
    print(f"[OK] import 完成: {result}")
    return 0


async def main_async(args: argparse.Namespace) -> int:
    db = args.db or default_db_path()
    if args.cmd == "export":
        return await do_export(db, args.output, args.include_embeddings)
    if args.cmd == "import":
        return await do_import(db, args.input, args.dry_run)
    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="筑真记忆同步工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="从 SQLite 导出 JSON")
    e.add_argument("--output", type=Path, required=True, help="输出 JSON 路径")
    e.add_argument("--db", type=Path, help="SQLite 路径（默认按平台）")
    e.add_argument("--include-embeddings", action="store_true")

    i = sub.add_parser("import", help="从 JSON 导入到 SQLite")
    i.add_argument("--input", type=Path, required=True, help="输入 JSON 路径")
    i.add_argument("--db", type=Path, help="SQLite 路径（默认按平台）")
    i.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
