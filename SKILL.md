---
name: traceable-literature-screening
description: Use when a research task supplies candidate papers and requires all-record relevance labels, explainable stable ranking, duplicate/version handling, conflict review, or a contract-preserving /app/output/result.json; retain every source record and dynamically validate case_id plus all original output_contract fields.
---

# 可追溯文献筛选与稳定排序

## 触发与适用边界

当输入包含 `/input/case.json`、实际 `task.md`、候选论文/检索结果，且要求相关性分层、筛选、排序、去重、冲突处理或结构化结果时使用。先读实际研究问题、查询、纳排标准、论文元数据和可获得的原文；不得根据文件名、领域标签或本说明中的示例猜答案。

本 Skill 聚焦**已有候选集的全记录筛选与排序**，不负责底层数据库接入、实时检索、全局召回、全文批量获取、论文写作或完整系统综述。九篇论文、合成重复导出或冲突意见等具体输入只作为当次事实处理，不能变成预制答案。没有实际证据时不声称读过全文、完成人工评审或验证数据库覆盖率。

## 输入、输出与依赖

- 输入：`/input/case.json`、Harness 实际提供的 `task.md` 和任务指向的真实材料；优先检查 `/input/task.md`，并读取实际存在的 `environment/resources.yaml`。不得假设资源名称代表已安装实体。
- 工作：`/app/work` 保存清单、评估、命令和日志；最终实际结果与可编辑产物写入 `/app/output`，主文件为 `/app/output/result.json`。
- 脚本：`/skills/weekly-skill/scripts/screen_literature.py` 和 `validate_result.py`。
- 依赖：CPython 3.9+ 标准库，无第三方安装、无网络要求。PDF/其他材料只在环境真实提供且任务需要时读取，记录真实工具、版本、来源定位和失败；脚本本身不解析 PDF。

脚本会复制每条 `source_record`，派生规范值仅用于匹配与排序，不改写原始元数据。默认不联网、不使用随机数、不删除候选，也不把词面命中当作人工相关性结论。

## 一、先保存全记录清单与诚实部分结果

1. 读取 case 的 `case_id`、原始 `output_contract`、研究问题、实际查询和纳排条件；逐条检查候选材料。若候选在独立 JSON 中，使用 `--candidates`；若只需 case 内某个明确列表，使用 JSON Pointer `--candidate-pointer`。不指定时，脚本递归收集常见候选列表并记录每项 `source_locator`；发现实际结构不同时应显式指定，不能靠名称猜测。
2. 先运行一次不带评估的命令，尽早保存部分结果。没有任务依据的评估时，所有记录默认 `uncertain/review`，词面分只作为公开的辅助特征，不应直接交付为最终科学判断。

```bash
python /skills/weekly-skill/scripts/screen_literature.py \
  --case /input/case.json \
  --question "从实际任务逐字摘录的研究问题" \
  --criterion "实际纳入或排除条件；每条重复一次" \
  --output /app/output/result.json
```

候选位于独立文件时增加 `--candidates /actual/candidates.json`；位于 case 的明确指针时增加 `--candidate-pointer /actual/list`。检查 `summary.input_records` 是否等于实际候选总数、`screening_results` 是否覆盖每条记录。空候选与读取失败必须区分。

## 二、按真实证据逐条评估

阅读每条实际标题、摘要、方法、人群/对象、年份、研究设计、来源和可获得的原文，将评估写入 `/app/work/assessments.json`。每条用 `record_key`（优先）或原记录唯一 ID 对齐，不得按排序后的位置对齐。

```json
{
  "assessments": [
    {
      "record_key": "实际记录键",
      "relevance": "direct",
      "decision": "keep",
      "role": "core_evidence",
      "confidence": 0.9,
      "rationale": "研究对象、设计和结局均符合实际纳入条件；说明具体边界。",
      "criteria": {
        "population": "match",
        "method": "match",
        "time_range": "unknown"
      },
      "evidence": [
        {"field": "abstract", "quote": "从实际摘要逐字摘录的支持句", "locator": "实际来源定位"}
      ]
    }
  ]
}
```

### 标签与判定约定

- `relevance`：`direct` 表示对象、方法和问题直接匹配；`indirect` 表示仅方法、背景或部分条件相关；`not_relevant` 表示有实际证据表明不匹配；`uncertain` 表示信息不足或条件冲突。不能把“没读到”写成“不相关”。
- `decision`：`keep`、`review`、`exclude`。排除必须引用命中的排除条件；缺失摘要/年份、相互冲突的意见、无法核实版本或关键条件未知时进入 `review`。
- `role` 可使用 `core_evidence`、`method_reference`、`background` 等任务适用标签；角色不能替代相关性。
- `criteria` 每项只能是 `match`、`partial`、`mismatch` 或 `unknown`，也可写成含 `match` 字段的对象。未知不是符合，也不是不符合。
- `evidence` 保存实际字段、逐字短引文和来源定位；缺失证据就留空并降低置信度。不得补造摘要、年份、DOI、引文、标注或人工意见。
- 多条评估或 `reviewer_opinions` 决策冲突时，脚本保留全部意见、升级为复核并记录冲突，不静默多数投票。

### 透明计分与稳定顺序

脚本公开每个分数组件：相关性基分（直接 100、间接 60、待定 35、不相关 0）+ 条件匹配/不匹配分 + 证据覆盖分（最多 6）+ 词面辅助分（最多 10）。排序先按决策层级 `keep → review → exclude`，再按分数降序；其后依次按相关性层级、证据条数、规范标题、`record_key` 稳定排序。词面重叠只能影响同一决策层级内的顺序，不能把排除项推到保留或复核项之前。

`screening_results` 始终保留所有记录，`ranking` 覆盖每个 `record_key` 恰好一次。`--top-k N` 只限制 `primary_results` 的便捷前缀，不截断全记录；默认 `k=N（全部记录）`。在结果中保留实际 `top_k`、`k` 和平局规则，让他人能复算。

## 三、重复、版本与冲突不是静默删除

- 相同非空 DOI 或相同规范标题形成候选重复/版本簇；保留所有记录，并用 `cluster_id`、`duplicate_of` 和 `canonical_record_key` 交叉引用。
- 正式发表版优先于预印本，其后按元数据完整性和稳定键选代表；这只是透明规则，不宣称两篇一定是同一研究。
- 同一研究多篇报道但 DOI/标题不同，需要 Agent 根据实际证据在评估和限制中说明，不能仅凭相似标题自动合并。
- 簇内相关性或决策不一致会进入 `conflicts` 和 `review_queue`。重复导出与冲突意见只是待处理输入，不是预期标签。

## 四、生成并动态校验最终合同

```bash
python /skills/weekly-skill/scripts/screen_literature.py \
  --case /input/case.json \
  --assessments /app/work/assessments.json \
  --question "实际研究问题" \
  --criterion "实际条件" \
  --output /app/output/result.json

python /skills/weekly-skill/scripts/validate_result.py \
  --case /input/case.json \
  --result /app/output/result.json \
  --output /app/work/result_validation.json
```

- 原始 `output_contract` 优先。脚本支持紧凑字段映射、字段列表/`fields`、`required`/`optional`、JSON Schema `properties`、嵌套 `items` 和显式 nullable `type` 列表；保留全部声明字段及嵌套结构，通用字段只是补充，不能替换原合同。
- 对无法映射的额外字段写 `null`、登记 `contract_status.unmapped_fields` 并标为 `partial`，绝不编造值。Agent 必须根据真实任务补齐或保留诚实部分结果；严格校验会把未解决字段判为失败。
- `anyOf`/`allOf`/`oneOf`、`$ref`、`patternProperties`、依赖和其他不受支持的组合/引用 Schema 不作猜测性投影：登记 `contract_status.unsupported_features`、标为 `partial`，且独立校验失败关闭。JSON Schema 控制字段不会被误当成输出字段。
- 校验器按**原始字段名精确检查** `case_id` 和任意嵌套合同字段，生成阶段的别名不能替代最终原字段；同时检查非空值显式类型、全记录数量、唯一键、连续排名、覆盖完整的 `ranking`、证据与分数组件。额外字段允许，`null` 会保留警告而不是伪装成已知事实。
- 退出码：`0` 结构通过；`1` 合同或全记录校验失败；`2` 读取/解析失败。通过只证明结构与本地不变量，不证明科学标签、官方白板、服务端 admission 或分数。
- 保存实际命令、stdout/stderr、退出码、输入/输出哈希和变更记录。若修改结果，重新运行两条命令；不得修改输入 case 或放宽校验器来消除错误。

## 异常与部分交付

- **空候选**：合法完成空筛选，`summary` 和 `ranking` 为空，限制中写 `candidate_set_empty`；不能补造文献。
- **材料/权限/接口异常**：记录真实路径、错误和未完成范围；输入无法解析时仍尽量写 `status=failed` 的 JSON，退出码为 2。
- **缺失元数据**：保留原字段为空并列入 `missing_metadata`；标题缺失或保留/待定项缺摘要时进入人工复核。
- **合同缺失**：保存通用结果并标 `partial`；合同存在但为空时只校验通用不变量并给出警告，两者不能混同。
- **大量同分**：使用公开稳定平局链，不随机打散；重复运行的相同输入和评估应得到字节一致的 JSON。
- **时间不足**：保留早期部分结果和评估，说明已完成/未完成项，不为追求 `completed` 隐藏错误。

## 最小调用示例（合成示意，非官方案例、非正式测试输出）

以下只演示接口，不是正式答案，也不得复制到正式结果。合成 case：

```json
{
  "case_id": "synthetic-demo",
  "research_question": "Which studies measure X in population Y?",
  "output_contract": {"status": "string", "ranking": "array"},
  "candidates": [
    {"paper_id": "p1", "title": "X in Y", "abstract": "Synthetic abstract", "year": 2024}
  ]
}
```

将合成评估中的 `record_key` 设为 `p1`，依据合成摘要标记 `direct/keep` 后执行上述两条命令并替换路径。示意结果为：

```json
{"case_id":"synthetic-demo","status":"completed","ranking":["p1"]}
```

该示意只说明调用和字段保留，不证明任何真实论文的相关性、召回、排序质量或官方测试结果。


## 交付保证与评分对齐

1. 在 Skill 安装目录执行：`cd /skills/weekly-skill && python scripts/screen_literature.py --case /input/case.json --assessments /app/work/assessments.json --question "<实际研究问题>" --criterion "<实际条件>" --output /app/output/result.json`，随后 `python scripts/validate_result.py --case /input/case.json --result /app/output/result.json --output /app/work/result_validation.json`。
2. 必须产出**完整成品**：`screening_results` 覆盖每条真实候选，`ranking` 每个 `record_key` 恰好一次；禁止 skeleton、`pending`、空占位或用流程说明代替评估。
3. 脚本只做词面辅助；逐条相关性、决策与证据必须由调用 Agent 依据实际标题/摘要/原文写入 `assessments.json` 并生成最终结果，不得编造。
4. 自检：`case_id` 与原始字段名精确一致；`output_contract` 全部字段落位；`status` 按实际取 `completed` / `partial` / `failed`；校验器退出码 0；不得修改或放宽 `validate_result.py` 来消除错误。
5. 输入缺失、JSON 损坏或字段异常时仍写出结构化结果并说明缺口，退出码按脚本约定。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。
