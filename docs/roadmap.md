# Project Memory System Roadmap

Last updated: 2026-05-09

## Product Direction

This repository is for an independent local-first memory and context system for personal agent work. The project management system will integrate with this memory system, but the memory system must remain usable as a standalone local service.

The first-class clients are:

- Claude Code
- Codex
- OpenClaw

Claude Desktop is optional and should not drive the first version.

The primary product requirement is to preserve the native usage experience of Claude Code, Codex, and OpenClaw. Users should continue using those tools normally. The memory system should integrate through plugins, hooks, MCP tools, and background indexing rather than requiring a new wrapper command for daily work.

## Current Strategic Decision

The system should not be built from scratch at the interaction layer.

The preferred reuse strategy is:

- Use `memsearch` as the baseline cross-client capture and recall layer.
- Use `claude-context` as the main reference for codebase indexing and semantic code search.
- Use `engram` as a reference for local SQLite, FTS, MCP, CLI, and TUI patterns.
- Use `claude-mem` as a reference for Claude Code summarization, worker service, and progressive disclosure UX.
- Use `mem0` as a reference for long-term memory concepts, entity-scoped memory, decay, graph memory, and API design, but not as the first-version core.

## Product Principles

1. Local-first.
   Each person deploys their own local instance. There is no centralized SaaS requirement for the first version.

2. Native-client experience.
   Claude Code, Codex, and OpenClaw must keep their normal user experience. The memory system should be ambient and low-friction.

3. Low-review burden.
   The system should generate fewer, higher-value durable memory suggestions. The user should not be asked to review memory after every conversation.

4. Working memory and durable memory are separate.
   Automatic session summaries can be captured without review as working memory. Long-term structured memories should be promoted selectively.

5. Source archive is not model context.
   Full transcripts may be stored locally and encrypted, but raw transcripts should not be injected into model context by default.

6. Sensitive data requires explicit access.
   Sensitive memories may be locally encrypted, but agents must request permission before reading sensitive content.

7. Code context is part of the memory system.
   The system must connect project memory, codebase indexing, file/symbol search, and historical decisions.

## Roadmap

### Phase 0: Repository Setup and Evidence Collection

Status: in progress.

Goals:

- Create the GitHub remote repository under the `zhuzhen-team` organization.
- Unpack the existing reference materials into this repository.
- Record the current conversation decisions in roadmap and detailed plan documents.
- Keep the original reference documents available for future review.

Inputs now present in this repository:

- `记忆系统设计/`: earlier design research and decision documents.
- `记忆库/`: mcp-memory-service based installation package.
- `记忆系统设计.zip`: original design archive.
- `记忆系统安装包.tar(1).gz`: original installation archive.

### Phase 1: Reuse Spike

Goal: verify whether `memsearch` can be reused directly as the three-client capture and recall substrate.

Required checks:

- Install and run memsearch with Claude Code.
- Install and run memsearch with Codex.
- Install and run memsearch with OpenClaw.
- Confirm normal tool usage is preserved.
- Confirm session/turn summaries are created automatically.
- Confirm the three clients share memory for the same project directory.
- Confirm transcript drill-down works or document exact limitations.
- Confirm OpenClaw non-default agent and channel limitations in the user's environment.
- Confirm Codex hook behavior, especially `Stop` behavior and transcript path availability.

Exit criteria:

- If memsearch works cleanly across the three clients, keep it as the capture and recall layer.
- If one client is weak, fork or patch only that adapter.
- If the architecture is incompatible with our long-term goals, preserve the plugin/hook learnings and implement our own adapter layer.

### Phase 2: Working Memory Layer

Goal: provide low-friction automatic memory without frequent user review.

Scope:

- Daily/session memory generated automatically from agent sessions.
- Per-project memory isolation.
- Cross-client recall through shared project memory.
- Progressive recall: search, expand, transcript drill-down.
- Recent memory injection or hinting at session start.

Important boundary:

- Working memory does not need approval.
- Working memory is not the same as formal durable memory.
- Working memory is allowed to be noisy within limits, but should remain summarized and searchable.

### Phase 3: Durable Memory Promotion

Goal: promote only important information from working memory into structured long-term memory.

Promotion candidates:

- Stable global preferences.
- Project-level preferences.
- Project facts.
- Decisions and reasons.
- Reusable workflows.
- Warnings and failure patterns.
- Important code context.
- Temporary context with TTL.

User experience:

- Do not ask the user to approve after every session.
- Support conversation-based approval when an agent identifies an important candidate.
- Support periodic digest approval, such as daily or weekly.
- Support manual commands like "remember this" or "promote this decision".

### Phase 4: Structured Memory and Governance

Goal: add the structure and safety that memsearch alone does not provide.

Required capabilities:

- Memory types.
- Global vs project scope.
- Source attribution.
- Confidence and importance.
- TTL and expiration.
- Supersede relationships for decisions.
- Sensitive memory classification.
- Sensitive access requests and audit log.
- Rejection or deletion workflows.
- Export and backup.

### Phase 5: Code Context Integration

Goal: integrate codebase indexing with project memory.

Core capabilities:

- Repo indexing.
- File/chunk search.
- Symbol extraction.
- Semantic code search.
- Links between decisions, tasks, and files.
- Recommended context bundle for agent task startup.

Reference:

- `claude-context` should be evaluated as the primary source for code indexing architecture and implementation reuse.

### Phase 6: Project Management System Integration

Goal: connect this memory system to the broader project management system.

Responsibilities:

- Project and task namespace mapping.
- Active task context.
- Task completion summary ingestion.
- Memory-aware task startup.
- Evidence and review handoff.
- OpenClaw runner integration through the generic agent/runner API.

Boundary:

- The memory system is not the project management system.
- It provides context, memory, retrieval, and evidence services to the project management system.

## First-Version Non-Goals

- No centralized SaaS.
- No multi-user shared database.
- No automatic promotion of all conversations into formal long-term memory.
- No default injection of raw transcript into model context.
- No mandatory wrapper command for normal Claude Code, Codex, or OpenClaw usage.
- No dependency on Docker, Milvus server, or other heavy external infrastructure unless the reuse spike proves it is necessary and acceptable.
- No deep Claude Desktop automation in the first version.

## Open Questions

- Whether to keep memsearch Markdown as the working-memory source of truth while using SQLite for structured durable memory.
- Whether to fork memsearch or treat it as an external dependency.
- How strict the durable memory promotion threshold should be.
- Whether periodic digest approval should be daily, weekly, or triggered by important project milestones.
- How the project management system will expose active task context to the memory system.
