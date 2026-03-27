# claude-skill-harness

[English](README.md) | [中文](README.zh-CN.md)

一个用于编排长时间、多会话开发任务的 Claude Code 技能。

基于 Anthropic 工程团队的研究成果：
- [长时间运行应用的 Harness 设计](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [长时间运行 Agent 的有效 Harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## 解决的问题

| 问题 | 机制 |
|------|------|
| 跨会话遗忘 | 基于文件的状态管理（`.harness/`）+ 会话启动协议 |
| 自我评估宽容偏差 | 物理隔离的审查 agent + 校准过的怀疑态度 |
| 过早宣告"完成" | `features.json` 中不可变的验收合约 |
| 上下文焦虑导致草草收工 | 一次只做一个 feature + 强制检查点 |
| 新会话不知道之前发生了什么 | `campaign.json` + `progress.md` + git log 三重恢复 |
| 会话中途中断 | 结构化的 `checkpoint_notes` 实现可靠恢复 |
| 开发环境未就绪 | 自动检测并在会话启动时运行 `setup_command` |
| 长会话中上下文质量退化 | 会话边界指引 + 基于检查点的交接 |
| Feature 卡在审查循环中 | 阻塞流程——3 次失败后标记阻塞，继续下一个 |
| 流程开销一刀切 | 复杂度自适应——轻量/标准/重型模式 |

## 安装

```bash
npx skills add suntao2yl/claude-skill-harness
```

## 使用方法

```bash
# 开始新的开发战役
/harness "实现多人对战系统"

# 新会话中恢复（自动检测阶段）
/harness

# 手动触发 QA 审查
/harness review

# 查看进度
/harness status

# 指定下一个要做的 feature
/harness focus F007

# 战役中途添加 feature
/harness add "比赛观战模式"

# 跳过某个 feature
/harness skip F003

# 重置战役
/harness reset
```

## 工作原理

```
/harness 位于 plan mode 之上的抽象层次中：

  CLAUDE.md → /harness → plan mode → task list
  (规则)      (战役)      (单个任务)    (步骤)
```

### 战役生命周期

```
INIT → 选择 feature → 规划 → 实现 → 自测 → 审查 → 检查点 → 选择下一个
                                │                    ↑
                         定期更新 checkpoint_notes   独立 agent 上下文
                                                    配备校准过的怀疑态度
```

### 创建的关键文件

```
.harness/
├── campaign.json          # 战役元数据、会话追踪和当前状态
├── features.json          # Feature 列表及不可变的验收合约
├── features-schema.json   # JSON Schema 校验
├── progress.md            # 人类可读的会话日志
└── archive/               # 归档的历史战役
```

## 核心特性

### 结构化会话恢复
每个进行中的 feature 都跟踪 `checkpoint_notes`——已完成步骤、下一步操作、待解决问题。新会话恢复时，CONTINUE 阶段读取这些笔记进行可靠交接，而非仅靠 git diff 猜测。

### 环境启动自动化
`campaign.json` 存储 `setup_command`（如 `npm run dev`、`docker compose up -d`）。每次会话启动时自动执行，确保开发环境就绪后再跑测试。

### 浏览器/E2E 测试集成
当浏览器测试工具（Playwright MCP、Puppeteer MCP）可用时，自测和审查阶段会使用它们从视觉上验证用户可见的行为——像人类用户一样测试。

### 验收清单
在 PICK 阶段，不可变的 `verification` 被展开为详细的 `acceptance_checklist`——基于实现方案的具体可检查项。审查者同时检查两者。

### 阻塞流程
当一个 feature 连续 3 次审查失败或遇到外部阻塞时，标记为 `blocked` 并记录原因。战役继续推进下一个未阻塞的 feature，而非卡住不动。

### 复杂度自适应
战役的 `mode`（轻量/标准/重型）根据 feature 数量设定，调整流程的仪式感。小型战役跳过 schema 生成；大型战役增加里程碑集成检查。

### 会话边界指引
检查点是天然的会话边界。Harness 在合适的时机建议中断，并确保所有状态已保存到文件，供下一次会话使用。

## 自动恢复（推荐配置）

配置 `SessionStart` hook，让每个新 Claude 会话自动检测活跃的 campaign：

```json
// .claude/settings.json 或 ~/.claude/settings.json
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

配置后无需每次手动输入 `/harness`——campaign 上下文会在会话启动时自动注入。

## 设计原则

1. **基于文件的状态管理** — 所有跨会话状态存储在 `.harness/` 中，绝不依赖对话记忆
2. **角色分离** — 实现者和审查者在物理上隔离的 agent 上下文中
3. **一次一个 feature** — 完成、测试、检查点，然后继续下一个
4. **JSON 存储机器状态** — 比 Markdown 更能抵抗意外修改
5. **不可变验收条件** — Feature 的验收标准在创建时锁定；agent 无法弱化它们
6. **校准过的怀疑态度** — 审查者提示词明确对抗已记录的宽容偏差
7. **优雅降级** — 阻塞的 feature 不会拖停整个战役；上下文中断不会丢失进度

## 许可证

MIT
