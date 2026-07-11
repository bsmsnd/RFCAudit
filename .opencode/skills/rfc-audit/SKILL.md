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
