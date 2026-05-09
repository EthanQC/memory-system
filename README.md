# Project Management Personal Memory System

This repository collects the reference materials, extracted prototype packages, roadmap, and implementation planning for a local-first personal memory and context system.

The intended system is an independent memory/context repository that can be integrated by a broader project management system while remaining usable by Claude Code, Codex, and OpenClaw.

## Repository Contents

- `docs/roadmap.md`: current product direction and phased roadmap.
- `docs/detailed-plan.md`: detailed requirements, boundaries, open-source reuse evaluation, and spike plan.
- `记忆系统设计/`: earlier design documents and research notes.
- `记忆库/`: extracted mcp-memory-service based installation package for reference.
- `记忆系统设计.zip`: original archive for the design documents.
- `记忆系统安装包.tar(1).gz`: original archive for the installation package.

## Current Direction

The current preferred approach is to preserve native Claude Code, Codex, and OpenClaw usage while reusing existing open-source work where possible:

- Evaluate `memsearch` as the cross-client working-memory capture and recall layer.
- Evaluate `claude-context` as the codebase indexing/reference layer.
- Use `engram`, `claude-mem`, and `mem0` as references for storage, UX, and long-term memory model design.
