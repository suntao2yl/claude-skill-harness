# claude-skill-harness

[English](README.md) | [中文](README.zh-CN.md)

用于管理长周期、多会话开发任务的 Claude Code skill。

思路来源仍然是 Anthropic Engineering 关于长任务 harness 的两篇文章：
- [Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## v2 的核心变化

`/harness-plan` 的外部命令保持不变，但内部恢复与交接逻辑改成了：

- 用紧凑的机器状态替代自由文本断点
- 每个进行中 feature 只有一个 `current-contract.json`
- 用 `session-summary.json` 作为默认恢复入口
- 用确定性的 Python 脚本处理状态变更
- 按风险决定是否进入完整 QA
- 通过 `${CLAUDE_SKILL_DIR}` 使脚本路径可移植——不依赖安装位置
- 新增 `harness_reset.py` 实现确定性的 campaign 归档
- 命令路由明确：`/harness-plan "goal"` → INIT，`/harness-plan` → RESUME
- `/harness-plan focus` 切换前检查是否有 in_progress 冲突
- 启动时只读取活跃 feature 条目，而非整个 `features.json`
- `session-protocol.md` 合并到 SKILL.md，减少每次会话的 token 开销
- 重试升级：`selftest_retries` 计数器连续失败 3 次后自动 block
- 会话新鲜度信号：`checkpoint_writes`、已完成步骤数、会话内完成 feature 数触发换会话建议
- 并行子任务指导：在单个 feature 内使用 Agent tool 并行处理独立子任务
- 默认自动推进：仅 INIT 计划审批、破坏性操作和 QA 审查需要人工确认

## 关键文件

```text
.harness/
├── campaign.json
├── features.json
├── current-contract.json
├── session-summary.json
├── features-schema.json
├── contract-schema.json
├── session-summary-schema.json
└── progress.md
```

## 状态文件说明

### `campaign.json`

保存 campaign 元数据与默认策略：

- `bootstrap_command`
- `setup_command`
- `default_review_policy`
- `baseline_status`
- `last_session_commit`

### `features.json`

保存 feature 列表、不可变的 `verification`，以及结构化 `checkpoint`。
每个 feature 还包含 `blocked_history`（带时间戳的阻塞/解除记录，上限 10 条）和 `archived_contract`（feature 完成时保存的契约快照）。

### `current-contract.json`

当前激活 feature 的执行契约：

- `feature_id`
- `goal`
- `scope_in`
- `scope_out`
- `verification_claims`
- `verification_commands`
- `manual_checks`
- `review_policy`
- `execution_context` — 验证命令的工作目录和超时设置

### `session-summary.json`

新会话和 hook 默认读取的恢复摘要：

- campaign goal 与 mode
- 当前 feature
- 进度计数
- 下一步动作
- 已知失败项
- 环境状态

## 内置脚本

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_validate.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_summary.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_pick_next.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_transition.py --feature-id F007 --to in_progress
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_contract.py --feature-id F007
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py --feature-id F007 --next-step "..."
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_reset.py --label "phase-1"
```

这些脚本只读写 `.harness/`，用于替代手工修改 JSON。
其中 `harness_contract.py` 和 `harness_checkpoint.py` 只允许作用于当前激活且处于 `in_progress` 的 feature，`harness_transition.py` 会拒绝创建第二个活跃 feature。

脚本关键行为：
- `harness_validate.py` 检测 git drift（HEAD 与上次验证提交的差异）以及循环依赖和悬空依赖。
- `harness_checkpoint.py` 在未显式提供时自动从 `git diff` 提取 `files_touched`。
- `harness_transition.py` 在 feature 完成时将契约归档到 feature 记录中（而非删除），阻塞时追加带时间戳的条目到 `blocked_history`。
- `harness_reset.py` 将整个 campaign 归档到 `.harness/archive/<timestamp>_<label>/`，清理 `.harness/` 以便重新 INIT。

## 工作流

```text
INIT -> PICK -> 生成 contract -> 实现 -> 自测 -> 按需 QA -> checkpoint -> 完成
```

恢复时优先级：

1. `session-summary.json`
2. `current-contract.json`
3. 当前 feature 的 `checkpoint`
4. 必要时再读 `progress.md` 最近几行

## 审查策略

- `selftest`: 只跑本地验证
- `qa`: 先跑本地验证，再启动独立 reviewer agent

默认对 UI、鉴权、支付、迁移、并发、外部集成类 feature 使用 `qa`；其他低风险 feature 默认 `selftest`。

## SessionStart hook

安装 plugin 后会自动注册 SessionStart hook,在新会话启动时注入紧凑状态:

- 目标
- 进度计数
- 当前 feature
- review policy
- 环境状态（baseline failing 时显示警告）
- 上次会话日期
- 一行 next step
- 已知失败项（最多 5 条）
- 当前 feature 上次 checkpoint 的 open issues（最多 5 条）

## 安装

```bash
# 作为 plugin 安装(推荐)
/plugin marketplace add suntao2yl/claude-skill-harness
/plugin install harness-plan@suntao-skills
```

## License

MIT
