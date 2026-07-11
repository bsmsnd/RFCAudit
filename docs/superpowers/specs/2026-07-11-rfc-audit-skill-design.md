# RFCAudit opencode Skill 设计方案

- **日期**: 2026-07-11
- **可视化版本**: `docs/rfc-audit-skill-design.html`
- **方案**: Approach A（codegraph-native skill），项目级安装
- **状态**: 已确认，待实施

## 1. 目标

把 RFCAudit 仓库中调用 LLM 的 Python 脚本（`init.py`、`repo.py`、`diff.py`、`query_repo_recursive.py`）转化为一个 opencode 原生 skill。opencode 自身替代 OpenAI API 调用，codegraph 替代 tree-sitter 代码解析，扁平子代理编排替代 autogen 多智能体。

## 2. 脚本 → Skill 替换映射

| 原脚本 | 替换为 |
|---|---|
| `init.py` askLLM / OpenAI client | opencode 自身模型（无需代码） |
| `repo.py` 层次化摘要 | Phase B 目录级摘要（k 路并行） |
| `diff.py` explore / select（LLM 定位） | Phase A+B 的章节-目录匹配 |
| `diff.py` autogen GroupChat（analyze→executor→critic） | Phase C 扁平编排（主 agent 派发分析 + critic 子代理） |
| `query_repo_recursive.py` tree-sitter query_name/caller | `codegraph_explore`（含调用路径/动态分发） |

## 3. 安装位置

```
RFCAudit/
├── .opencode/
│   ├── skills/rfc-audit/SKILL.md      # 主方法论
│   └── agent/rfc-critic.md            # critic 子代理（mode: subagent）
```

## 4. 总流水线

三阶段顺序执行：A（RFC 处理）→ B（代码切分+匹配）→ C（审计）。

### Phase A — RFC 切分与摘要

执行方：主 agent，单线程。

**切分规则：**
1. 首选按章节号正则切割：`^(\d+(\.\d+)*)\s+(标题)`，原子粒度为 2 级（如 2.1、2.2、3.2）。
2. 更深层（如 2.1.1）内容并入其 2 级父节（2.1）；仅有顶层无子节的（如 2）也保留为独立单元。
3. **降级方案**：若文档不含章节号，按 Markdown 标题层级切分，以 `##`（h2）为原子单元；连标题也无则整篇作单一单元。
4. 对每个单元，LLM 生成一段摘要，概括该章节描述的行为与约束。

**产物**（全文与 JSON 分离，JSON 只存 title / summary / content_path）：
- `RFC/{protocol}/sections/{RFC_ID}_{section}.md` — 章节全文
- `RFC/{protocol}/rfc_sections.json` — 索引

```jsonc
{ "RFC 2460": {
    "3": { "title": "IPv6 Header Format",
           "summary": "定义40字节固定头...",
           "content_path": "RFC/ipv6/sections/RFC2460_3.md" } } }
```

### Phase B — 代码切分、摘要与匹配

执行方：主 agent 预扫描 → k 路并行子代理。

**源码识别（多语言）：**
- C/C++: `.c .h .cpp .hpp .cc .cxx .hh`
- Java: `.java`
- Python: `.py`
- Rust: `.rs`

排除非源码：`CMakeLists.txt`、`*.cmake`、`Makefile`、`*.mk`、`*.sh`、`*.json/yaml/xml/toml`、`*.md`、`*.conf`、构建产物。排除非工程目录：`test*`、`benchmark*`、`.opencode`、`doc*`。

**目录切分规则：**
1. 根目录 = 第 1 级。默认切分到第 3 级目录为原子单元。
2. 若某目录源码文件 >100，下沉到第 4 级；仍 >100 拆到第 5 级（上限）。
3. 纯确定性预扫描（文件计数，无 LLM），主 agent 先产出完整目录清单。

**k 路并行均分：**
- 预扫描得有序目录列表 `dirs[0..N-1]`，并行度 `k`（默认 5）。
- 第 `i` 个分片取 `dirs[i*N/k .. (i+1)*N/k)`，按**目录个数**均分（成本驱动是待摘要目录数量）。
- 分片边界对齐目录树连续区间，保持同子树目录在同一分片（共享上下文）。

每个子代理对分配的每个目录执行：① 读头文件/关键源码（codegraph_explore 采样）② 写目录摘要 ③ 对照 RFC 章节摘要判断关联度 ④ 打置信度分。

**置信度阈值：**

| 等级 | 判定 | 处理 |
|---|---|---|
| high | 目录明确实现该 RFC 章节描述的行为 | 记入 code_map，纳入 Phase C 审计 |
| medium | 含该行为的支撑代码（共享结构/调用路径依赖） | 记入 code_map，纳入 Phase C 审计 |
| low | 仅边缘引用 | 进 `candidates` 候选池，不纳入审计 |
| none | 无关 | 不记录 |

**产物**：`summary/{protocol}_code_map.json`

```jsonc
{ "src/net/ipv6/": {
    "summary": "IPv6 协议栈核心：报文收发、扩展头、地址自动配置",
    "file_count": 57, "level": 3,
    "related_sections": [
      { "rfc": "RFC 2460", "section": "3", "confidence": "high" } ],
    "candidates": [] } }
```

### Phase C — 审计（核心）

执行方：主 agent 编排，扁平派发（无嵌套）。

**关键约束**：子代理工具集无 `task`（实验验证），无法派发子代理。因此 analyze↔critic 交叉验证由主 agent 顺序编排。

**工作单元** = 一个目录（携带其全部 high/medium 关联的 RFC 章节）。同一目录只探索一次，对照其所有关联章节逐一检查。

**范围限缩原则**：Phase B 已为每个目录标注关联 RFC 章节。审计时 codegraph 探索**以该目录为边界**，只取目录内符号。调用路径跟随若跨出目录，仅取该调用点作上下文佐证，**不展开成对越界目录的全面审计**。越界关联应由 Phase B 匹配体现，审计不自行扩大范围。

**分析子代理职责：**
1. 理解规范 — 从关联章节提取强制行为、约束、要求；只考虑显式声明的，不推断。
2. 限定范围探索代码 — codegraph_explore **仅在该目录范围内**取相关函数/宏/类型定义；取调用者上下文作佐证。
3. 严格比对 — 只报告对强制行为的显式违反；检查调用点是否已保证前置条件。

不报告：可选/未定义行为、合理的实现选择、日志 vs 静默处理差异。**只识别问题，不出修复建议。**

**critic 子代理职责：**
1. 验证探索充分性 — 确认所有相关代码路径都经 codegraph 探索。
2. 校验每条不一致 — 确认是对规范强制行为的明确违反；排除误报。
3. 最终裁决 — 有效→确认；无效→附理由驳回；存疑→建议进一步调查路径。

排除误报来源：可选/未定义行为、可接受实现策略、日志差异、推断出的非规范要求、调用方已保证的前置条件。

**多目录 × 多章节并行处理：**
- 从 code_map 取出待审计目录列表（N 个），按 `N/batch_size` 分批（默认 batch_size = 5）。
- **批量同步并行**：每批内——
  - Round 1：并行派发 batch_size 个分析子代理（一条消息多个 task），等待全部返回。
  - Round 2：并行派发对应数量 critic 子代理，等待全部返回。
  - 合并确认结果写入 JSON，进入下一批。
- 分析与批判分两轮，因 critic 需读取对应分析结果，二者不可在同一轮并行。
- 按目录而非（目录×章节）对聚合，避免同一目录重复 codegraph 探索。目录过大时可降级为按章节拆分。

**codegraph 在审计中的角色：**

| 原 tree-sitter 操作 | codegraph_explore 替代 |
|---|---|
| `query_function(name)` | 按函数名取定义源码（同时给出调用关系） |
| `query_caller(name)` | blast radius / 调用路径（含动态分发跳点） |
| `query_type / query_def` | 按结构体/宏名取定义（含类型引用图） |
| `init(project)` 全量解析 | 索引已存在，即查即用 |

codegraph 能力上可跨任意目录追踪调用路径（相对 tree-sitter 的优势），但审计策略上以 Phase B 映射目录为边界。

**产物**：`inconsistencies_{protocol}.json`（仅识别问题，不含修复建议）

```jsonc
[ { "RFC chunk ID": "RFC 5722 §4 ...",
    "original context": "<相关函数源码>",
    "additional context": "<codegraph 探索到的调用方>",
    "inconsistencies": [
      { "summary": "RFC 5722 要求丢弃重叠分片，但实现未检查重叠" } ] } ]
```

## 5. 文件布局（对齐 RFCAudit 约定）

```
RFCAudit/
├── RFC/
│   ├── docs.txt                          # 输入 RFC 原文
│   └── {protocol}/
│       ├── sections/{RFC_ID}_{section}.md
│       └── rfc_sections.json
├── summary/
│   └── {protocol}_code_map.json
└── inconsistencies_{protocol}.json
```

## 6. 关键约束与决策

1. **扁平编排（无嵌套）**：子代理工具集无 `task`。并行只在一层发生（主 agent 同时派 N 个独立子代理）；analyze↔critic 是顺序两步派发。可通过 `experimental.primary_tools` + `permission.task` 实验性开启子代理 task 工具，但有递归爆炸风险。
2. **前置条件**：目标项目须有 `.codegraph/` 索引。skill 首步检查；若无指示运行 `codegraph init`。
3. **config.yaml 不再需要**：协议名、项目路径、RFC 文件路径由用户调用时以参数给出。
4. **裁剪策略**：采用 LLM 摘要匹配（Phase B）替代纯关键字/图可达性裁剪——更可解释，摘要可复用。
5. **只识别问题**：审计阶段只报告不一致，不提出修复建议。
