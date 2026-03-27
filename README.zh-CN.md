# claude-skill-harness

[English](README.md) | [中文](README.zh-CN.md)

Claude Code 技能，用于管理跨会话的大型开发任务。

参考 Anthropic 工程博客：
- [Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## 解决什么问题

| 问题 | 应对机制 |
|------|---------|
| 跨会话状态丢失 | 文件持久化（`.harness/`）+ 会话启动协议 |
| 自评偏差（倾向于高估自身产出质量） | 独立 reviewer agent，prompt 中显式抑制宽容倾向 |
| 未经验证即标记完成 | `features.json` 中的验收条件不可变，agent 无法绕过 |
| context 接近上限时匆忙收尾 | 单 feature 推进 + 强制 checkpoint |
| 新会话缺少上下文 | `campaign.json` + `progress.md` + git log 三重恢复 |
| 会话中途中断 | `checkpoint_notes` 记录断点，下次会话精确续接 |
| 开发环境未启动 | `setup_command` 在每次会话启动时自动执行 |
| 长会话后期输出质量下降 | 会话边界建议 + checkpoint 交接 |
| feature 反复审查不通过 | 3 次失败后标记 blocked，跳过继续推进 |
| 流程开销与任务规模不匹配 | 按 feature 数量自��选择 lite / standard / heavy 模式 |

## 安装

```bash
npx skills add suntao2yl/claude-skill-harness
```

## 使用

```bash
/harness "实现多人对战系统"     # 新建 campaign
/harness                       # 恢复进行中的 campaign（自动检测阶段）
/harness review                # 手动触发审查
/harness status                # 查看进度
/harness focus F007            # 指定下一个要实现的 feature
/harness add "观战模式"         # 追加 feature
/harness skip F003             # 跳过 feature
/harness reset                 # 归档并重置
```

## 工作原理

```
抽象层次：

  CLAUDE.md → /harness → plan mode → task list
  (约束)      (campaign)  (单任务)     (执行步骤)
```

### 生命周期

```
INIT → 选取 feature → 规划 → 实现 → 自测 → 审查 → checkpoint → 选取下一个
                                │                   ↑
                        定期写入 checkpoint_notes   独立 agent context
                                                   显式抑制宽容倾向
```

### 目录结构

```
.harness/
├── campaign.json          # campaign 元数据与当前状态
├── features.json          # feature 列表，含不可变验收条件
├── features-schema.json   # JSON Schema
├── progress.md            # 会话日志（供人阅读）
└── archive/               # 历史 campaign 归档
```

## 核心特性

### 断点恢复
进行中的 feature 持续记录 `checkpoint_notes`（已完成项、下一步、待解决问题）。新会话通过 CONTINUE 阶段读取断点信息恢复，不依赖 git diff 推断。

### 环境自动启动
`campaign.json` 中的 `setup_command`（如 `npm run dev`、`docker compose up -d`）在每次会话启动时自动执行，确保运行测试前环境就绪。

### 浏览器 / E2E 测试
当 Playwright MCP 或 Puppeteer MCP 可用时，自测和审查阶段通过浏览器交互验证前端行为，而非仅依赖命令行测试。

### 验收清单
选取 feature 后，将不可变的 `verification` 展开为 `acceptance_checklist`——基于实现方案的逐项检查清单。reviewer 同时核验两者。

### 阻塞处理
feature 连续 3 次审查未通过或遇到外部依赖阻塞时，标记为 `blocked` 并记录原因，campaign 继续推进后续 feature。

### 模式自适应
根据 feature 总数自动设定 campaign 模式：`lite`（< 10）省略 schema 生成和验收清单；`heavy`（30+）每 10 个 feature 追加一次集成验证。

### 会话边界
checkpoint 是自然的会话切分点。harness 在适当时机建议开启新会话，并确保所有状态已持久化。

## 自动恢复（推荐）

配置 `SessionStart` hook 后，新会话自动检测活跃 campaign 并注入上下文：

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

配置后无需手动输入 `/harness` 恢复——会话启动时自动注入 campaign 状态。

## 设计原则

1. **文件持久化** — 跨会话状态全部存储在 `.harness/`，不依赖对话上下文
2. **角色隔离** — 实现者与 reviewer 运行在独立的 agent context 中
3. **单 feature 推进** — 完成、测试、checkpoint，再进入下一个
4. **JSON 存储机器状态** — 相比 Markdown，JSON 更不易被 agent 误改
5. **验收条件不可变** — 创建时锁定，agent 无法事后降低标准
6. **reviewer 偏差抑制** — prompt 中显式对抗已知的自评宽容倾向
7. **容错推进** — blocked feature 不阻塞整体进度；中断不丢失状态

## 许可证

MIT
