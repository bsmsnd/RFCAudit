---
name: rfc-audit
description: 审计 C/C++/Java/Python/Rust 代码实现与 RFC 或规范文档的一致性，检测不一致问题。用于检查代码与 RFC 的合规性、发现实现与规范的偏差、或生成协议代码摘要。触发关键词：RFC 审计、规范合规、代码-文档不一致、协议实现检查。
---

# RFCAudit — 代码与 RFC 规范审计

检测代码库与其 RFC/规范文档之间的不一致。三个阶段顺序执行：处理 RFC（A）、将代码目录映射到 RFC 章节（B）、审计不一致（C）。所有产物统一输出到 `audit/` 目录。

## 执行规则

**全程不得向用户提问。** 从 Phase A 到 Phase C 连续执行，不在阶段之间暂停、不请求确认、不征求许可。遇到不确定之处时自行做出合理判断并继续，而非询问用户。仅在以下唯一情况停止：前置条件不满足（目标项目无 `.codegraph/` 索引）——此时告知用户运行 `codegraph init` 后停止。

## 前置条件

代码仓库**默认为当前仓库**（当前工作目录 / git 根目录），无需用户指定。

目标仓库**必须**有 `.codegraph/` 索引。检查仓库根目录下是否存在 `.codegraph/` 目录。若不存在，告知用户运行 `codegraph init` 后停止。

所有代码查询使用 `codegraph_explore` MCP 工具——函数定义、调用关系、类型/结构体/宏定义。它替代 tree-sitter 解析。`codegraph_explore` 的 `projectPath` 参数传入当前仓库根路径。

## 输入

从用户消息和上下文中获取以下参数（不询问，自行推断）：
- `protocol` — 协议名，用于输出目录命名（如 `ipv6`）
- `doc_list` — **文档列表**，用户提供一个包含多篇文档的列表（Markdown 表格、URL 列表、或本地路径列表）。每篇文档可能是在线 URL（需下载）或本地文件路径。skill 在 Phase A.0 负责下载/整理并统一转为 Markdown。

## 输出目录

所有产物统一输出到 `audit/{protocol}/`：

```
audit/{protocol}/
├── raw/                    # A.0：下载/整理的原始文档（Markdown）
├── sections/               # A.1：切分后的章节全文
├── rfc_sections.json       # A.1-A.2：章节索引 + 摘要
├── code_map.json           # B.4：目录摘要 + RFC 关联
└── inconsistencies.json    # C.6：确认的不一致
```

## Phase A — RFC 文档处理

目标：获取并格式化文档列表中的所有文档，逐一切分为 2 级章节，摘要，全文与索引分开归档。

### A.0 文档获取与格式化

对 `doc_list` 中的每一篇文档：

1. **判断来源类型：**
   - URL（如 `https://rfc-editor.org/rfc/rfc2460`）→ 用 `webfetch` 下载内容，转为 Markdown。
   - 本地文件路径 → 读取文件内容，若非 `.md` 则转为 Markdown（去除多余格式标记，保留标题和正文结构）。
2. **保存：** 将每篇文档以 Markdown 格式保存到 `audit/{protocol}/raw/{DOC_ID}.md`（`DOC_ID` 从文档名或 URL 推断，如 `RFC2460`）。
3. **汇总：** 所有文档获取完成后，得到 `audit/{protocol}/raw/` 下的一组 `.md` 文件，供 A.1 逐篇切分。

### A.1 切分章节

对 `audit/{protocol}/raw/` 中的**每一篇**文档，运行辅助脚本确定性地清洗并切分（无 LLM）：

```bash
python .opencode/skills/rfc-audit/scripts/split_rfc.py audit/{protocol}/raw/{DOC_ID}.md audit/{protocol}/ --rfc-id {DOC_ID}
```

脚本会**合并**写入 `audit/{protocol}/rfc_sections.json`——多次运行（每篇文档一次）自动累积，不会覆盖之前的结果。

脚本处理所有切分逻辑：
1. **首选——编号章节：** 匹配 `^(\d+(\.\d+)*)\s+(.+)`。原子粒度 = **2 级**（如 `2.1`）。更深层（如 `2.1.1`）并入其 2 级父节（`2.1`）。无子节的顶层章节（如 `2`）保留为独立单元。
2. **降级——Markdown 标题：** 若文档不含编号章节，按 `##`（h2）为原子单元切分。
3. **最后手段：** 整篇文档作为单一章节。

脚本将章节文件写入 `audit/{protocol}/sections/`，JSON 索引骨架写入 `audit/{protocol}/rfc_sections.json`（`title` 和 `content_path` 已填充，`summary` 留空）。

### A.2 逐章摘要

对索引中的每个章节，撰写一段摘要，描述该章节规定的行为与约束，填入 `rfc_sections.json` 的 `summary` 字段。此摘要驱动 Phase B 的匹配。

### A.3 归档

切分脚本（A.1）已完成归档。JSON 仅存储 `title`、`summary`、`content_path`——全文保存在独立的 `.md` 文件中。A.2 填充摘要后，索引即完整。

索引 schema：
```json
{ "RFC2460": {
    "3": {
      "title": "IPv6 Header Format",
      "summary": "定义 40 字节固定头...",
      "content_path": "sections/RFC2460_3.md"
    }
  }
}
```

## Phase B — 代码映射

目标：将代码库切分为目录单元，逐一摘要，并匹配到 RFC 章节。此阶段同时产出可复用的代码摘要和 Phase C 的审计范围。

### B.1 源码文件识别

各语言源码扩展名：
- C/C++：`.c .h .cpp .hpp .cc .cxx .hh`
- Java：`.java`
- Python：`.py`
- Rust：`.rs`

排除非源码文件：`CMakeLists.txt`、`*.cmake`、`Makefile`、`*.mk`、`*.sh`、`*.json`、`*.yaml`、`*.xml`、`*.toml`、`*.md`、`*.conf`、构建产物。

排除非工程目录：名称匹配 `test*`、`benchmark*`、`.opencode`、`doc*`、`audit*` 的目录。

**关键约束：预扫描与 RFC 无关（RFC-agnostic）。** B.1/B.2 必须覆盖**整个代码库的所有源码目录**——不得基于 RFC 主题、协议名称或先验知识提前筛选目录。例如审计 IPv6 RFC 时，仍必须扫描 `dpdk/`、`app/`、`lib/` 等所有源码目录，而非仅扫描看似与 IPv6 相关的目录。哪些目录真正与 RFC 相关，由 B.3 的 LLM 匹配和 B.4 的置信度过滤来决定——预扫描阶段不做任何相关性判断。

### B.2 目录切分（确定性预扫描，无 LLM）

1. 根目录 = 第 1 级。默认原子单元为**第 3 级**目录。
2. 对每个目录，按上述扩展名统计源码文件数。
3. 若某目录源码文件超过 100 个，下沉到第 4 级；若第 4 级仍超过 100，继续拆到第 5 级（上限）。
4. 产出**完整的**有序目录清单，涵盖代码库中所有含源码的目录。纯文件计数，无 LLM 调用，无 RFC 相关性过滤。

### B.3 k 路并行摘要 + 匹配

将目录列表按**目录个数**均分为 `k` 个分片（默认 `k = 5`），不按文件数均分——成本驱动是待摘要的目录数量：
- 第 `i` 个分片取 `dirs[i*N/k .. (i+1)*N/k)`。
- 分片边界对齐连续子树，使同子树的目录尽量在同一分片（共享上下文）。

通过 `task` 工具并行派发 `k` 个子代理——一条消息发出 `k` 个 `task` 调用（`subagent_type: "general"`）。每个子代理收到其目录列表以及 `rfc_sections.json` 中的 RFC 章节摘要。对分配的每个目录，子代理执行：
1. 读关键头文件/源码；用 `codegraph_explore` 采样该目录的符号。
2. 撰写目录摘要——该目录实现了什么？
3. 将目录摘要与 Phase A 的所有 RFC 章节摘要逐一比对。
4. 为每个（目录 × RFC 章节）打置信度：
   - **high** — 该目录明确实现了该 RFC 章节描述的行为。
   - **medium** — 该目录含该行为的支撑代码（共享数据结构、调用路径依赖）。
   - **low** — 仅边缘引用。
   - **none** — 无关。

### B.4 合并并写入 code_map

将所有分片结果合并到 `audit/{protocol}/code_map.json`：
- `high` 和 `medium` 关联记入 `related_sections`。
- `low` 关联记入 `candidates`（供 Phase C 按需扩展，默认不审计）。
- `none` 不记录。

Schema：
```json
{ "src/net/ipv6/": {
    "summary": "IPv6 协议栈核心：报文收发、扩展头、地址自动配置",
    "file_count": 57,
    "level": 3,
    "related_sections": [
      { "rfc": "RFC2460", "section": "3", "confidence": "high" }
    ],
    "candidates": []
  }
}
```

## Phase C — 审计

目标：对每个有 high/medium RFC 关联的目录，找出代码与规范之间的显式不一致。**仅识别问题，不提出修复建议。**

### C.1 工作单元

工作单元 = **一个目录**，携带其全部 high/medium 关联的 RFC 章节。该目录只探索一次，所有关联章节逐一检查。这避免了对同一目录的重复 codegraph 探索。

若某目录非常大（关联章节极多），可以拆分为按章节的分析任务——但默认按目录聚合。

### C.2 范围限缩

审计期间的 codegraph 探索**以 code_map 中的目录为边界**：
- 只查询**该目录内**的符号。
- 若调用路径延伸到目录外（如调用方在另一目录），仅取该调用点作为上下文佐证。**不展开**对越界目录的全面审计。
- 跨目录的关联必须由 Phase B 匹配体现。审计不自行扩大范围。

### C.3 批量同步并行处理

1. 从 code_map 收集所有有 `high` 或 `medium` 关联的目录，总数记为 `N`。
2. 按 `batch_size`（默认 5）分批处理。

每批：
- **第一轮——分析：** 并行派发 `batch_size` 个分析子代理（一条消息，多个 `task` 调用，`subagent_type: "general"`）。每个子代理收到目录路径及其关联 RFC 章节内容（通过 `content_path` 加载）。等待该批所有子代理返回。
- **第二轮——批判：** 并行派发 `batch_size` 个 critic 子代理（一条消息，多个 `task` 调用，`subagent_type: "rfc-critic"`）。每个 critic 收到一份分析结果以及原始 RFC 章节文本和相关代码。等待全部返回。
- 将确认的不一致合并到输出 JSON，然后处理下一批。

分析与批判分两轮，因为每个 critic 需要其对应的分析结果——二者不能在同一轮并行。

### C.4 分析子代理指令

将以下指令连同目录路径和关联 RFC 章节内容传递给每个分析子代理：

1. **理解规范。** 从关联章节提取强制行为、约束和要求。只考虑显式声明的行为——不推断或假设任何未文档化的内容。
2. **在范围内探索代码。** 用 `codegraph_explore` 获取**目录边界内**的相关函数、宏和类型定义。获取调用者上下文作为佐证。在目录内先最大化覆盖再下结论。
3. **严格比对。** 只报告对强制行为的显式违反。考虑调用点保证——若某前置条件在调用前已满足，被调用方无需重复检查。

不报告：可选或未定义行为、合理或预期的实现选择、日志 vs 静默处理的差异。**此阶段仅识别问题，不提出修复建议。**

以列表形式返回候选不一致，每条包含：违反的 RFC 章节、相关代码位置、一句话违规摘要。

### C.5 Critic 子代理指令

派发 `rfc-critic` 子代理（定义见 `.opencode/agents/rfc-critic.md`）。它每次审查一份分析结果，只返回通过审查的不一致。完整规则见 critic 代理定义。

### C.6 输出

将确认的不一致写入 `audit/{protocol}/inconsistencies.json`：

主代理组装最终输出：每条通过 critic 审查的不一致，包装上其 RFC 章节标识、原始上下文（分析的源代码）、附加上下文（codegraph 探索的调用方证据），按 RFC 章节分组。

"RFC chunk ID" 标识被检查的 RFC 章节——格式：RFC 编号 + 章节（如 `RFC 5722 §4`）。

```json
[
  {
    "RFC chunk ID": "RFC 5722 §4（章节描述）",
    "original context": "<相关函数源代码>",
    "additional context": "<codegraph 探索的调用方上下文>",
    "inconsistencies": [
      { "summary": "RFC 要求 X，但实现未检查 X" }
    ]
  }
]
```

注：不输出修复建议字段。本 skill 仅识别问题。
