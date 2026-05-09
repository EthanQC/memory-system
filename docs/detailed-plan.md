# Detailed Plan: Local Memory and Context System

Last updated: 2026-05-09

## 1. Background

The current discussion started from a review of a `mcp-memory-service` based installation package and a set of memory-related open-source repositories. The package is useful as a reference, but it should not define the final architecture.

The target is a complete local memory and context system that can be split into its own repository and integrated into the broader project management system. The system must support Claude Code, Codex, and OpenClaw as first-class clients.

The user wants to preserve the normal user experience of those tools. The memory system should not require a new daily workflow such as always launching tools through a wrapper command.

## 2. Requirements Confirmed in Conversation

### 2.1 Deployment

- Each person runs their own local deployment.
- The system is personal/local-first, even if it may later be distributed to more people.
- The first version does not need a central server or shared team database.

### 2.2 Data and Storage

- SQLite is acceptable as the primary structured store.
- Markdown/JSON export is useful for audit, backup, portability, and review.
- Full session transcript/source archive may be stored in the database.
- Full transcript should be locally encrypted or otherwise protected when sensitive.
- Full transcript should not be injected into model context by default.

### 2.3 Capture and Review

- The system should support automatic capture.
- However, the user does not want to review memory after every conversation.
- The desired behavior is fewer, higher-value candidates.
- Automatic working memory can be captured without review.
- Formal long-term memory should be promoted selectively.
- Conversation-based approval is preferred when review is needed.
- Dashboard can exist, but it should not be the only review surface.

### 2.4 Memory Types

Formal durable memory should not be a flat note pile. It should include at least:

- Global preference.
- Project preference.
- Project fact.
- Decision.
- Task summary.
- Workflow.
- Warning or failure pattern.
- Code context.
- Temporary context.
- Sensitive note.

Preferences must distinguish global scope from project scope to avoid cross-project pollution.

### 2.5 Sensitive Memory

- Sensitive notes may be stored locally.
- Agents must request permission before reading sensitive content.
- Permissions should support allow once, allow for this session, or allow for this task.
- Sensitive access must be logged.

### 2.6 Code Context

The memory system should include code context, not just conversation memory.

The code context target is broader than simple file search:

- Find relevant files and symbols.
- Connect decisions to code.
- Explain why files/modules changed.
- Recommend context files before an agent starts work.
- Share code context across Claude Code, Codex, and OpenClaw.

### 2.7 Client Requirements

First-class clients:

- Claude Code.
- Codex.
- OpenClaw.

Required client capabilities:

- Automatic capture.
- Memory read/write.
- Recall during normal use.
- Minimal disruption to native UX.
- Shared project memory across clients.

Claude Desktop is optional and should not drive the first implementation.

## 3. Revised Capture Model

The earlier idea of asking the user to review candidates after each session is too heavy.

The revised model has three layers:

### 3.1 Working Memory

Working memory is automatically generated from sessions/turns.

Characteristics:

- Captured automatically.
- Summarized.
- Searchable.
- Per project/workspace.
- Does not require approval.
- Useful for "what did we do last time".
- Can include links to transcript/source archive.

This layer is where `memsearch` fits best.

### 3.2 Durable Memory

Durable memory is structured and higher signal.

Characteristics:

- Promoted from working memory or manual user instruction.
- Low volume.
- Typed and scoped.
- Important enough to influence future agent behavior.
- May be approved in conversation or in periodic digest.

Examples:

- "The memory system should preserve native Claude Code/Codex/OpenClaw usage."
- "Use memsearch as the first reuse candidate for three-client capture."
- "Do not review every session; keep memory promotion low-noise."

### 3.3 Sensitive Memory

Sensitive memory is separate from both working and durable memory.

Characteristics:

- Locally encrypted or protected.
- Not automatically injected.
- Requires explicit user authorization before an agent can read content.
- Audited.

## 4. Repository Reuse Evaluation

### 4.1 memsearch

Decision: directly evaluate and likely reuse as the capture/recall substrate.

Why:

- It already provides adapters for Claude Code, Codex, OpenClaw, and OpenCode.
- It is designed to preserve normal client usage through hooks/plugins.
- It writes standard Markdown daily memory logs.
- It supports cross-platform sharing when the same project directory maps to the same collection.
- It supports progressive recall: search, expand, transcript drill-down.
- It defaults to local ONNX embeddings and does not require an API key.

Important implementation details observed:

- Claude Code plugin uses shell hooks: `SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd`.
- Codex plugin uses `SessionStart`, `UserPromptSubmit`, and `Stop` because Codex does not have the same `SessionEnd` hook.
- OpenClaw plugin uses native TypeScript plugin APIs, `agent_end`, `before_agent_start`, and memory tools.
- OpenClaw plugin requires conversation access permission.
- Codex transcript path may be missing on current builds, so memsearch falls back to history and last assistant message.
- Milvus Lite locking can limit continuous watch behavior; server mode and lite mode differ.

Limitations:

- Markdown is the source of truth, whereas our structured durable memory likely wants SQLite.
- It is primarily a working-memory system, not a full governed durable memory system.
- It does not handle sensitive memory authorization.
- It does not provide project-management task binding.
- It does not fully solve durable memory type governance.

Planned use:

- Use memsearch for Phase 1 spike.
- Keep it as working memory if it passes.
- Build durable memory and governance on top of or alongside it.

### 4.2 claude-context

Decision: evaluate as code context/indexing source.

Why:

- It is focused on codebase semantic search.
- It includes MCP and VS Code extension packages.
- It uses AST/splitting concepts useful for code context.
- It is orthogonal to conversation memory.

Limitations:

- It is not a durable user/project memory system.
- It may depend on Milvus/Zilliz-style backend assumptions.
- It should not be the only memory layer.

Planned use:

- Reuse or adapt code indexing, chunking, and MCP search concepts.
- Integrate with project memory so decisions and code references can be linked.

### 4.3 engram

Decision: use as a local-first architecture reference, not as the main capture layer.

Why:

- Go single-binary local deployment is attractive.
- SQLite and FTS5 match the local-first requirement.
- It includes MCP server, CLI, TUI, relations, sync, and diagnostics.
- It is useful as a reference if SQLite becomes the structured durable store.

Limitations:

- It does not provide the same three-client automatic capture layer as memsearch.
- It overlaps with the durable memory layer but does not solve native Claude Code/Codex/OpenClaw UX on its own.

Planned use:

- Study storage schema, relation handling, CLI/TUI, diagnostics, and local deployment patterns.
- Avoid running engram and memsearch as two competing memory cores.

### 4.4 claude-mem

Decision: use as a Claude Code UX and summarization reference, not as the main system.

Why:

- Strong Claude Code memory UX.
- Good reference for automatic compression, progressive disclosure, UI, and worker-service concepts.
- Its repository also contains Claude Code plugin and Codex/OpenClaw related structures, but its main advantage is still Claude Code memory experience.

Limitations:

- It is more Claude Code centered than the target system.
- It overlaps with memsearch.
- It is not the best cross-client substrate for this project.

Planned use:

- Borrow ideas for summarization prompts, status UI, progressive disclosure, and possibly viewer experience.
- Do not use as the core memory backend in the first design.

### 4.5 mem0

Decision: use as conceptual/API reference, not first-version core dependency.

Why:

- Strong long-term memory model.
- Useful concepts: memory APIs, entity scoping, graph memory, decay, advanced retrieval, export, and feedback.
- Python and Node SDKs are useful references.

Limitations:

- More platform/SaaS/multi-user oriented.
- Higher complexity than needed for local personal deployment.
- Existing concerns around junk memory and multilingual retrieval quality need careful validation.
- It does not preserve native Claude Code/Codex/OpenClaw experience by itself.

Planned use:

- Borrow memory model and API ideas.
- Do not make it the first-version core.

## 5. Target Architecture

The preferred architecture is layered.

```text
Claude Code plugin/hooks  \
Codex hooks               -> memsearch working-memory layer -> daily session memory
OpenClaw plugin/hooks    /

daily session memory -> memoryd structured layer
                     -> durable typed memories
                     -> sensitive memory authorization
                     -> project/task mapping
                     -> code context index
                     -> unified MCP/API
```

## 6. Native Client Interaction

The system should avoid requiring a new wrapper command for daily work.

Expected interaction:

- User opens Claude Code normally.
- User opens Codex normally.
- User runs OpenClaw normally.
- Hooks/plugins automatically capture summarized working memory.
- Agents can recall memory when useful.
- Agents can propose durable memory only when high value.
- User can approve durable memory inside the conversation or through a later digest.

## 7. Durable Memory Promotion Policy

The system should be conservative.

Promote only when the information is:

- Stable.
- Future-useful.
- Clearly stated or evidenced.
- Not merely transient discussion.
- Not easily reconstructed from raw transcript.

Good promotion candidates:

- Decisions.
- User preferences.
- Project facts.
- Reusable workflows.
- Known failure patterns.
- Important code-context summaries.

Poor promotion candidates:

- Casual confirmations.
- Temporary uncertainty.
- Raw tool output.
- Repeated summaries of the same fact.
- Every session's entire work log.

## 8. Review UX

The user prefers conversation-based review.

Desired interaction:

```text
Agent: I found 2 durable memory candidates from this discussion.

1. [decision] Use memsearch as the initial three-client capture substrate.
2. [requirement] Avoid per-session review; use low-volume durable promotion.

Approve, edit, or skip?
```

The system should also support:

- "Remember this" manual command.
- "Do not remember this" command.
- "Show pending durable memory candidates."
- "Approve candidate 1."
- "Reject all from this session."
- Periodic digest review.

## 9. Storage Direction

Current direction:

- Use memsearch Markdown and vector index for working memory if the spike succeeds.
- Use SQLite for structured durable memory, governance, sensitive notes, access grants, audit logs, and project/task mapping.
- Provide JSON/Markdown export for portability and review.

Open design issue:

- Whether durable memory should live in the same repository directory, a user-level app data directory, or both.

## 10. Required Spike Plan

### 10.1 Claude Code Spike

Verify:

- Plugin installs without disrupting normal Claude Code use.
- Hooks fire correctly.
- Stop hook summarizes turns asynchronously.
- Recent memory is injected or hinted correctly.
- Memory recall works naturally.
- Transcript drill-down works.

### 10.2 Codex Spike

Verify:

- Hooks install into Codex without breaking existing settings.
- Normal Codex use remains unchanged.
- `Stop` hook captures each completed turn.
- Missing `transcript_path` fallback works.
- Child `codex exec` summarization does not recurse.
- Memory recall works from Codex.

### 10.3 OpenClaw Spike

Verify:

- Plugin installs into the user's OpenClaw environment.
- Conversation access permission is set.
- `agent_end` fires in the user's normal agent mode.
- Feishu/channel limitations are understood.
- Memory tools work.
- OpenClaw memory is shared with Claude Code and Codex for the same project.

### 10.4 Cross-Client Spike

Verify:

- Claude Code writes working memory and Codex can recall it.
- Codex writes working memory and OpenClaw can recall it.
- OpenClaw writes working memory and Claude Code can recall it.
- Same project maps to same collection.
- Different projects remain isolated.

## 11. Current Boundary Decisions

In scope:

- Local memory service.
- Working memory.
- Durable memory promotion.
- Sensitive memory permission flow.
- Code context indexing.
- Cross-client memory sharing.
- Project/task integration later.

Out of scope for first version:

- Centralized SaaS.
- Shared team database.
- Claude Desktop deep automation.
- Mandatory wrapper-based workflow.
- Heavy external infrastructure as a first requirement.
- Full automatic durable memory promotion.

## 12. Next Discussion Topics

The next design discussion should focus on:

1. Whether memsearch should be an external dependency, fork, or embedded subsystem.
2. How durable memory should sync with memsearch working memory.
3. What UI should handle periodic memory promotion digest.
4. How project/task identity should be provided by the project management system.
5. How sensitive-memory authorization should appear inside Claude Code, Codex, and OpenClaw.
6. How much of claude-context should be reused for code indexing.
