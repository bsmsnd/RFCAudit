---
name: rfc-audit
description: Audit C/C++/Java/Python/Rust implementations against RFC or specification documents to detect inconsistencies. Use when checking code-RFC compliance, finding implementation-vs-spec misalignments, or building protocol code summaries. Triggers on keywords like RFC audit, spec compliance, code-doc inconsistency, protocol implementation check.
---

# RFCAudit — Code vs RFC Specification Audit

Detect misalignments between a codebase and its RFC/specification documentation. Three phases run in order: process the RFC (A), map code directories to RFC sections (B), then audit for inconsistencies (C).

## Prerequisites

The target project MUST have a `.codegraph/` index. Check by looking for a `.codegraph/` directory at the project root. If absent, tell the user to run `codegraph init` in the target project and wait before proceeding.

The `codegraph_explore` MCP tool is used for all code lookups — function definitions, caller relationships, type/struct/macro definitions. It replaces tree-sitter parsing.

## Inputs

Ask the user for these if not already provided:
- `protocol` — protocol name, used in output filenames (e.g. `ipv6`)
- `project_path` — target project root (must have `.codegraph/`)
- `rfc_input` — path to the RFC document (plain text or markdown)

## Phase A — RFC Processing

Goal: split the RFC into 2-level sections, summarize each, archive full text separately from the index.

### A.1 Split into sections

1. **Primary — numbered sections:** match lines matching the regex `^(\d+(\.\d+)*)\s+(.+)`. The atomic unit is **2-level** sections (e.g. `2.1`, `2.2`, `3.2`). Content deeper than 2-level (e.g. `2.1.1`) rolls up into its 2-level parent (`2.1`). A top-level section with no subsections (e.g. `2`) stays as its own unit.
2. **Fallback — Markdown headings:** if the document has NO numbered sections, split by Markdown heading level. Use `##` (h2) as the atomic unit.
3. **Last resort:** if neither numbered sections nor headings exist, treat the entire document as a single section.

### A.2 Summarize each section

For each section unit, write a one-paragraph summary describing the behavior and constraints it specifies. This summary drives matching in Phase B.

### A.3 Archive

- Write each section's full text to `RFC/{protocol}/sections/{RFC_ID}_{section}.md`.
- Write the index to `RFC/{protocol}/rfc_sections.json`. The JSON stores ONLY `title`, `summary`, and `content_path` — full text lives in the separate `.md` files.

Index schema:
```json
{ "RFC 2460": {
    "3": {
      "title": "IPv6 Header Format",
      "summary": "Defines the 40-byte fixed header...",
      "content_path": "RFC/{protocol}/sections/RFC2460_3.md"
    }
  }
}
```

## Phase B — Code Mapping

Goal: split the codebase into directory units, summarize each, and match to RFC sections. This produces both a reusable code summary AND the scope for Phase C.

### B.1 Source file identification

Source extensions by language:
- C/C++: `.c .h .cpp .hpp .cc .cxx .hh`
- Java: `.java`
- Python: `.py`
- Rust: `.rs`

EXCLUDE non-source files: `CMakeLists.txt`, `*.cmake`, `Makefile`, `*.mk`, `*.sh`, `*.json`, `*.yaml`, `*.xml`, `*.toml`, `*.md`, `*.conf`, and build artifacts.

EXCLUDE non-engineering directories: any directory whose name matches `test*`, `benchmark*`, `.opencode`, or `doc*`.

### B.2 Directory splitting (deterministic prescan, no LLM)

1. Root directory = level 1. The default atomic unit is a **level 3** directory.
2. For each directory, count source files using the extensions above.
3. If a directory has more than 100 source files, split deeper to level 4. If a level-4 directory still has more than 100, split to level 5 (the maximum depth).
4. Produce the complete ordered list of directories to summarize. This is pure file counting — no LLM calls.

### B.3 k-way parallel summarization + matching

Partition the directory list into `k` shards (default `k = 5`) by **directory count**, not file count — the cost driver is the number of directories to summarize:
- Shard `i` takes directories `dirs[i*N/k .. (i+1)*N/k)`.
- Shard boundaries align to consecutive subtrees so directories from the same subtree stay in the same shard (shared context).

Dispatch `k` subagents in parallel via the `task` tool — issue one message with `k` `task` calls. Each subagent, for each assigned directory, does:
1. Read key header/source files; use `codegraph_explore` to sample the directory's symbols.
2. Write a directory summary — what does this directory implement?
3. Compare the directory summary against ALL RFC section summaries from Phase A.
4. Assign a confidence per (directory × RFC section):
   - **high** — the directory clearly implements the behavior described in that RFC section.
   - **medium** — the directory contains supporting code for that behavior (shared data structures, call-path dependencies).
   - **low** — only a tangential reference.
   - **none** — unrelated.

### B.4 Merge and write code_map

Merge all shard results into `summary/{protocol}_code_map.json`:
- Record `high` and `medium` associations in `related_sections`.
- Record `low` associations in `candidates` (available for Phase C to optionally expand, but not audited by default).
- Omit `none`.

Schema:
```json
{ "src/net/ipv6/": {
    "summary": "IPv6 protocol stack core: packet I/O, extension headers, address autoconfiguration",
    "file_count": 57,
    "level": 3,
    "related_sections": [
      { "rfc": "RFC 2460", "section": "3", "confidence": "high" }
    ],
    "candidates": []
  }
}
```
