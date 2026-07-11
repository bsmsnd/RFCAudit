# RFCAudit Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create an opencode skill (`rfc-audit`) and subagent (`rfc-critic`) that replace RFCAudit's LLM-calling Python scripts, using codegraph for code lookup and opencode's native model for reasoning.

**Architecture:** Two markdown config files encode the full 3-phase methodology (RFC processing → code mapping → audit). No Python, no external API. The skill instructs the main agent; the critic is a subagent invoked during Phase C. Flat orchestration — no nested subagents.

**Tech Stack:** opencode skill frontmatter (YAML), Markdown instruction body, codegraph MCP tool, `task` tool for parallel subagent dispatch.

**Spec:** `docs/superpowers/specs/2026-07-11-rfc-audit-skill-design.md`

## Global Constraints

- Skill name: `rfc-audit` (lowercase, hyphen-separated, ≤64 chars, matches folder name)
- Agent name: `rfc-critic` (matches filename `rfc-critic.md`)
- Skill frontmatter: `name` required, `description` required (covers what + when, third person, front-loads trigger keywords)
- Agent frontmatter: `description` required, `mode: subagent` required
- Agent permissions: critic is read-only + no task dispatch (`edit: deny`, `bash: deny`, `task: deny`)
- No fix suggestions anywhere — problem identification only
- No project-specific examples (no f-stack references) in the skill content
- Target project must have `.codegraph/` index (skill checks; instructs `codegraph init` if absent)
- After saving config files, user must restart opencode for changes to take effect

## File Structure

| File | Responsibility |
|---|---|
| `.opencode/skills/rfc-audit/SKILL.md` | Main methodology: Phase A (RFC split+summarize), Phase B (code map, k-way parallel), Phase C (audit, batch parallel). Frontmatter triggers on RFC audit / spec compliance. |
| `.opencode/agent/rfc-critic.md` | Critic subagent: reviews analysis results, filters false positives, confirms valid inconsistencies. Read-only, no task dispatch. |

These are pure opencode config files (Markdown + YAML frontmatter) — no executable code, no tests in the traditional sense. Verification is structural (frontmatter validity, required sections present) + a load check (opencode recognizes the skill).

---

### Task 1: Create SKILL.md with frontmatter, intro, prerequisites, and Phase A

**Files:**
- Create: `.opencode/skills/rfc-audit/SKILL.md`

**Interfaces:**
- Produces: the skill file with valid frontmatter, Phase A instructions (RFC split + summarize + archive). Tasks 2 and 3 append to this same file.

- [ ] **Step 1: Create the directory structure**

Run:
```bash
mkdir -p .opencode/skills/rfc-audit
```

- [ ] **Step 2: Write SKILL.md with frontmatter + intro + prerequisites + Phase A**

Create `.opencode/skills/rfc-audit/SKILL.md` with this exact content:

```markdown
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
```

- [ ] **Step 3: Verify frontmatter and Phase A are present**

Run:
```bash
head -5 .opencode/skills/rfc-audit/SKILL.md
grep -c "^## Phase A" .opencode/skills/rfc-audit/SKILL.md
grep -c "^### A.3 Archive" .opencode/skills/rfc-audit/SKILL.md
```
Expected: frontmatter shows `name: rfc-audit` and `description:`; Phase A count = 1; A.3 Archive count = 1.

- [ ] **Step 4: Commit**

```bash
git add .opencode/skills/rfc-audit/SKILL.md
git commit -m "feat(rfc-audit): add SKILL.md with frontmatter and Phase A (RFC processing)"
```

---

### Task 2: Add Phase B (code mapping) to SKILL.md

**Files:**
- Modify: `.opencode/skills/rfc-audit/SKILL.md` (append after Phase A)

**Interfaces:**
- Consumes: `RFC/{protocol}/rfc_sections.json` from Phase A (section summaries for matching)
- Produces: `summary/{protocol}_code_map.json` — directory → summary + RFC associations

- [ ] **Step 1: Append Phase B content to SKILL.md**

Add the following section to `.opencode/skills/rfc-audit/SKILL.md`, immediately after the Phase A section (after the A.3 Archive block):

```markdown

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
```

- [ ] **Step 2: Verify Phase B is present and complete**

Run:
```bash
grep -c "^## Phase B" .opencode/skills/rfc-audit/SKILL.md
grep -c "^### B.4" .opencode/skills/rfc-audit/SKILL.md
grep -c "code_map.json" .opencode/skills/rfc-audit/SKILL.md
```
Expected: Phase B count = 1; B.4 count = 1; code_map.json appears at least once.

- [ ] **Step 3: Commit**

```bash
git add .opencode/skills/rfc-audit/SKILL.md
git commit -m "feat(rfc-audit): add Phase B (code mapping with k-way parallel summarization)"
```

---

### Task 3: Add Phase C (audit) and file layout to SKILL.md

**Files:**
- Modify: `.opencode/skills/rfc-audit/SKILL.md` (append after Phase B)

**Interfaces:**
- Consumes: `summary/{protocol}_code_map.json` (which directories + RFC sections to audit), `RFC/{protocol}/rfc_sections.json` (section full-text paths)
- Produces: `inconsistencies_{protocol}.json` — confirmed inconsistencies (problem ID only, no fixes)
- References: `.opencode/agent/rfc-critic.md` subagent (created in Task 4)

- [ ] **Step 1: Append Phase C content to SKILL.md**

Add the following section to `.opencode/skills/rfc-audit/SKILL.md`, immediately after Phase B:

```markdown

## Phase C — Audit

Goal: for each directory with high/medium RFC associations, find explicit inconsistencies between the code and the specification. **Problem identification only — do NOT propose fixes.**

### C.1 Work unit

The work unit is **one directory** carrying ALL its high/medium associated RFC sections. The directory is explored once; every associated section is checked against it. This avoids redundant codegraph exploration of the same directory for different sections.

If a directory is very large (many associated sections), it MAY be split so each section gets its own analysis task — but the default is per-directory aggregation.

### C.2 Scope confinement

codegraph exploration during audit is **bounded by the directory** from code_map:
- Only query symbols that live WITHIN that directory.
- If a call path leads outside the directory (e.g. a caller in another directory), take only that single call site as context evidence. Do NOT expand into a full audit of the out-of-scope directory.
- Cross-directory relevance must come from Phase B matching. The audit does not self-expand scope.

### C.3 Batch-synchronous parallel processing

1. Collect all directories with `high` or `medium` associations from code_map. Call the count `N`.
2. Process in batches of `batch_size` (default 5).

For each batch:
- **Round 1 — analyze:** dispatch `batch_size` analysis subagents IN PARALLEL (one message, multiple `task` calls using `subagent_type: "general"`). Each subagent receives the directory path plus its associated RFC section contents (loaded via `content_path`). Wait for ALL subagents in the batch to return.
- **Round 2 — critic:** dispatch `batch_size` critic subagents IN PARALLEL (one message, multiple `task` calls using `subagent_type: "rfc-critic"`). Each critic receives one analysis result plus the original RFC section text and the relevant code. Wait for ALL to return.
- Merge the confirmed inconsistencies into the output JSON, then proceed to the next batch.

Analysis and critic are two separate rounds because each critic needs its corresponding analysis result — they cannot overlap in the same round.

### C.4 Analysis subagent instructions

Pass these instructions to each analysis subagent along with the directory path and associated RFC section contents:

1. **Understand the spec.** Extract mandatory behaviors, constraints, and requirements from the associated sections. Consider only explicitly stated behavior — do NOT infer or assume anything undocumented.
2. **Explore code within scope.** Use `codegraph_explore` to retrieve relevant function, macro, and type definitions WITHIN the directory boundary. Retrieve caller context as supporting evidence. Maximize coverage within the directory before concluding.
3. **Compare rigorously.** Report ONLY explicit violations of mandatory behavior. Account for call-site guarantees — if a precondition is satisfied before a call, the callee need not recheck it.

Do NOT report: optional or undefined behavior, valid or intended implementation choices, logging vs silent handling differences. **This phase identifies problems only — do NOT propose fixes.**

Return candidate inconsistencies as a list, each with: the RFC section it violates, the relevant code location, and a one-sentence summary of the violation.

### C.5 Critic subagent instructions

Dispatch the `rfc-critic` subagent (defined in `.opencode/agent/rfc-critic.md`). It reviews one analysis result at a time and returns only the inconsistencies that survive review. See the critic agent definition for its full rules.

### C.6 Output

Write confirmed inconsistencies to `inconsistencies_{protocol}.json`:

```json
[
  {
    "RFC chunk ID": "RFC 5722 §4 (description of the section)",
    "original context": "<relevant function source code>",
    "additional context": "<codegraph-explored caller context>",
    "inconsistencies": [
      { "summary": "RFC requires X, but the implementation does not check X" }
    ]
  }
]
```

Note: there is no `proposed_fix` field. This skill identifies problems only.

## File Layout Summary

```
RFC/{protocol}/sections/{RFC_ID}_{section}.md   # Phase A: section full text
RFC/{protocol}/rfc_sections.json                 # Phase A: title + summary + content_path
summary/{protocol}_code_map.json                 # Phase B: directory → summary + RFC associations
inconsistencies_{protocol}.json                  # Phase C: confirmed inconsistencies
```
```

- [ ] **Step 2: Verify Phase C and file layout are present**

Run:
```bash
grep -c "^## Phase C" .opencode/skills/rfc-audit/SKILL.md
grep -c "^### C.6 Output" .opencode/skills/rfc-audit/SKILL.md
grep -c "^## File Layout Summary" .opencode/skills/rfc-audit/SKILL.md
grep -c "proposed_fix" .opencode/skills/rfc-audit/SKILL.md
```
Expected: Phase C = 1; C.6 = 1; File Layout = 1; proposed_fix count = 0 (must be absent).

- [ ] **Step 3: Commit**

```bash
git add .opencode/skills/rfc-audit/SKILL.md
git commit -m "feat(rfc-audit): add Phase C (scoped batch-parallel audit) and file layout"
```

---

### Task 4: Create the rfc-critic subagent

**Files:**
- Create: `.opencode/agent/rfc-critic.md`

**Interfaces:**
- Consumes: one analysis result (candidate inconsistencies) + RFC section text + code, passed via the `task` prompt by the main agent during Phase C Round 2
- Produces: a filtered list of confirmed inconsistencies (those that survive review)

- [ ] **Step 1: Create the agent directory**

Run:
```bash
mkdir -p .opencode/agent
```

- [ ] **Step 2: Write rfc-critic.md**

Create `.opencode/agent/rfc-critic.md` with this exact content:

```markdown
---
description: Reviews RFCAudit analysis results during Phase C to verify correctness, filter false positives, and confirm only valid inconsistencies. Invoked only by the rfc-audit workflow.
mode: subagent
permission:
  edit: deny
  bash: deny
  task: deny
---

You are a **critic agent** responsible for reviewing the analysis performed by an analysis agent. Your objective is to verify the correctness, completeness, and validity of identified inconsistencies between a source code implementation and its documented specification.

You receive: the analysis result (candidate inconsistencies), the original RFC section text, and the relevant code.

## Your task

1. **Verify Exploration**
   - Ensure all relevant code paths were explored via codegraph.
   - Confirm the analysis covered call-site logic and constraints, not just surface-level definitions.

2. **Validate Reported Inconsistencies**
   - Confirm each issue is a clear violation of MANDATORY behavior explicitly stated in the specification.
   - Filter out false positives arising from:
     - Optional or undefined behavior
     - Acceptable implementation strategies
     - Logging vs silent behavior differences
     - Requirements inferred by the analysis agent but NOT present in the spec
     - Feasibility checks or constraints that are already enforced by callers (call-site guarantees)

3. **Final Judgment**
   - If the inconsistency is **valid**, confirm it — keep it in the output.
   - If the inconsistency is **not valid**, refute it with a one-sentence reason — remove it from the output.
   - If the analysis is **inconclusive**, recommend further investigation paths instead of confirming.

## Constraints

- Identify problems only. Do NOT propose fixes.
- Confirm only true, explicitly documented inconsistencies.

## Output

Return a JSON array of confirmed inconsistencies (the ones that survived your review). Each entry has the same shape the analysis agent produced:

```json
[
  { "summary": "RFC requires X, but the implementation does not enforce X" }
]
```

If no inconsistencies survive review, return an empty array `[]`.
```

- [ ] **Step 3: Verify critic frontmatter and content**

Run:
```bash
head -10 .opencode/agent/rfc-critic.md
grep -c "^mode: subagent" .opencode/agent/rfc-critic.md
grep -c "task: deny" .opencode/agent/rfc-critic.md
grep -c "proposed_fix\|propose fix\|Do NOT propose fixes" .opencode/agent/rfc-critic.md
```
Expected: frontmatter shows `description:`, `mode: subagent`; mode count = 1; task: deny count = 1; the "Do NOT propose fixes" line appears (count ≥ 1) confirming the no-fix rule is present.

- [ ] **Step 4: Commit**

```bash
git add .opencode/agent/rfc-critic.md
git commit -m "feat(rfc-audit): add rfc-critic subagent for Phase C review"
```

---

### Task 5: End-to-end structural validation

**Files:**
- Validate: `.opencode/skills/rfc-audit/SKILL.md`, `.opencode/agent/rfc-critic.md`

This task validates the complete skill package is structurally sound and opencode-recognizable. No code execution — the real functional test happens when the user restarts opencode and invokes the skill on an actual project.

- [ ] **Step 1: Verify all required files exist at correct paths**

Run:
```bash
test -f .opencode/skills/rfc-audit/SKILL.md && echo "SKILL.md OK" || echo "SKILL.md MISSING"
test -f .opencode/agent/rfc-critic.md && echo "rfc-critic.md OK" || echo "rfc-critic.md MISSING"
```
Expected: both print OK.

- [ ] **Step 2: Validate SKILL.md frontmatter required fields**

Run:
```bash
grep -E "^name: rfc-audit$" .opencode/skills/rfc-audit/SKILL.md
grep -E "^description:" .opencode/skills/rfc-audit/SKILL.md
```
Expected: both lines present. `name` matches the folder name `rfc-audit`.

- [ ] **Step 3: Validate all three phases are present and ordered**

Run:
```bash
grep -n "^## Phase A\|^## Phase B\|^## Phase C\|^## File Layout Summary" .opencode/skills/rfc-audit/SKILL.md
```
Expected: four lines in order — Phase A, Phase B, Phase C, File Layout Summary — with increasing line numbers.

- [ ] **Step 4: Confirm no fix proposals anywhere in the package**

Run:
```bash
grep -rin "proposed_fix\|propose.*fix\|suggest.*fix\|修复建议" .opencode/skills/rfc-audit/SKILL.md .opencode/agent/rfc-critic.md | grep -v "do NOT propose\|不提出修复\|不出修复\|NO fix\|no .*fix" || echo "CLEAN: no fix proposals"
```
Expected: prints "CLEAN: no fix proposals" (the only matches are the explicit "do NOT" prohibitions, which the `grep -v` filters out).

- [ ] **Step 5: Confirm no project-specific examples leaked in**

Run:
```bash
grep -ic "f-stack\|freebsd/netinet6\|dpdk/drivers" .opencode/skills/rfc-audit/SKILL.md .opencode/agent/rfc-critic.md
```
Expected: count = 0.

- [ ] **Step 6: Verify the skill folder name matches the frontmatter name**

Run:
```bash
folder=$(basename $(dirname .opencode/skills/rfc-audit/SKILL.md)); name=$(grep "^name:" .opencode/skills/rfc-audit/SKILL.md | sed 's/name: //'); [ "$folder" = "$name" ] && echo "MATCH: $folder" || echo "MISMATCH: folder=$folder name=$name"
```
Expected: prints "MATCH: rfc-audit".

- [ ] **Step 7: Remind user to restart opencode**

Print this message for the user (config is loaded once at startup; the running session will not see the new skill until restart):

```
All skill files created and validated. Quit and restart opencode for the rfc-audit skill and rfc-critic subagent to be loaded.
```

- [ ] **Step 8: Commit the validation (if any uncommitted changes)**

```bash
git status --porcelain || true
```
If clean, skip. If changes exist, commit them with:
```bash
git add -A && git commit -m "chore(rfc-audit): structural validation complete"
```
