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
- scope drift 检测：checkpoint 时检查 `files_touched` 是否越过 `scope_out` 边界
- quick-verify：`harness_checkpoint.py --quick-verify` 在实现阶段提前跑 `test_command`，尽早发现回归
- 结构化失败记录：checkpoint 中新增 `last_failure` 对象（command, error_summary, affected_files, timestamp）
- 会话交接上下文：session-summary 新增 `session_id`、`session_step_count`、`handoff_reason`，支持跨会话连续性
- 手动检查追踪：`--manual-check-done` 记录已完成的手动检查项
- 契约命令历史：`command_history` 记录验证命令的变更轨迹（含时间戳）
- 状态机新增 `backlog` 状态，支持转换到 `pending`、`in_progress`、`skipped`
- 运行时平台检测：`detect_platform()` / `skill_home()` 支持 Codex 环境兼容

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
- `command_history` — 验证命令变更的时间戳记录

### `session-summary.json`

新会话和 hook 默认读取的恢复摘要：

- campaign goal 与 mode
- 当前 feature
- 进度计数
- 下一步动作
- 已知失败项
- 环境状态
- `session_id` 和 `session_step_count` 用于会话边界检测
- `handoff_reason` — 上一会话结束原因（freshness, blocked, completed, interrupted）

## 内置脚本

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_validate.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_summary.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_pick_next.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_transition.py --feature-id F007 --to in_progress
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_contract.py --feature-id F007
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py --feature-id F007 --next-step "..."
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py --feature-id F007 --quick-verify
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py --feature-id F007 --manual-check-done "检查描述"
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_contract.py --feature-id F007 --update-command "旧命令" "新命令"
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_reset.py --label "phase-1"
```

这些脚本只读写 `.harness/`，用于替代手工修改 JSON。
其中 `harness_contract.py` 和 `harness_checkpoint.py` 只允许作用于当前激活且处于 `in_progress` 的 feature，`harness_transition.py` 会拒绝创建第二个活跃 feature。

脚本关键行为：
- `harness_validate.py` 检测 git drift（HEAD 与上次验证提交的差异）以及循环依赖和悬空依赖。
- `harness_checkpoint.py` 在未显式提供时自动从 `git diff` 提取 `files_touched`。`--quick-verify` 在写入前跑测试。`--selftest-retry` / `--failure-command` / `--failure-summary` 记录结构化失败信息。`--manual-check-done` 标记手动检查完成。
- `harness_contract.py` 支持 `--update-command` 更新验证命令并记录变更历史。
- `harness_transition.py` 在 feature 完成时将契约归档到 feature 记录中（而非删除），阻塞时追加带时间戳的条目到 `blocked_history`。支持 `backlog` 状态。
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
- 上一会话的 `handoff_reason`（freshness, blocked, completed, interrupted）
- 上次自测失败详情（如有）

## 安装

### Claude Code

```bash
# 先添加 marketplace，再安装 plugin
/plugin marketplace add suntao2yl/claude-skill-harness
/plugin install harness-plan@suntao-skills
```

安装完成后，直接通过 `/harness-plan` 调用这个 skill。

### Codex

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo suntao2yl/claude-skill-harness \
  --path plugins/harness-plan/skills/harness-plan
```

安装完成后请重启 Codex，新 skill 才会出现在技能列表中。

## License

MIT
