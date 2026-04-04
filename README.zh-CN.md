# claude-skill-harness

[English](README.md) | [中文](README.zh-CN.md)

用于管理长周期、多会话开发任务的 Claude Code skill。

思路来源仍然是 Anthropic Engineering 关于长任务 harness 的两篇文章：
- [Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## v2 的核心变化

`/harness` 的外部命令保持不变，但内部恢复与交接逻辑改成了：

- 用紧凑的机器状态替代自由文本断点
- 每个进行中 feature 只有一个 `current-contract.json`
- 用 `session-summary.json` 作为默认恢复入口
- 用确定性的 Python 脚本处理状态变更
- 按风险决定是否进入完整 QA
- 精简 `SKILL.md`，减少 skill 本身的 token 开销

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
python3 scripts/harness_validate.py
python3 scripts/harness_summary.py
python3 scripts/harness_pick_next.py
python3 scripts/harness_transition.py --feature-id F007 --to in_progress
python3 scripts/harness_contract.py --feature-id F007
python3 scripts/harness_checkpoint.py --feature-id F007 --next-step "..."
```

这些脚本只读写 `.harness/`，用于替代手工修改 JSON。
其中 `harness_contract.py` 和 `harness_checkpoint.py` 只允许作用于当前激活且处于 `in_progress` 的 feature，`harness_transition.py` 会拒绝创建第二个活跃 feature。

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

可在新会话启动时自动注入紧凑状态：

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "~/.claude/skills/harness/hooks/session-start.sh"
      }]
    }]
  }
}
```

hook 只注入：

- 目标
- 进度计数
- 当前 feature
- review policy
- 上次会话日期
- 一行 next step

## 安装

```bash
npx skills add suntao2yl/claude-skill-harness
```

## License

MIT
