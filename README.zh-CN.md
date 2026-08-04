# Harness

Harness 3.2 只暴露一个同名 Codex plugin 与 skill：`$harness`。它把原 harness 的持久化
合同、制品、风险门和跨 task 交接，与 Codex 原生 PDCA 执行环合并为一条工作流。

不再区分被动账本模式和 PDCA companion。Ultra 负责 Plan，High 负责 Do，全新的 Max
负责 Check，确定性代码负责 Act；项目内 `.harness/` 账本保存批准范围与精确交接状态。

## 它保存什么

- 已确认的交付目标和验收标准；
- 不允许静默漂移的验收标准；
- 已完成工作、遗留问题和一个明确的下一步；
- 验收证据和可审计的交接摘要。

适合需要明确验收合同、独立复核或跨 task 连续性的交付。普通的一次性工作仍可直接使用
Codex，不必引入 harness。

## 在 Codex 中安装

```bash
codex plugin marketplace add /absolute/path/to/harness
codex plugin add harness@harness-marketplace
```

安装后新建 Codex task。这个 skill 只能显式调用：

```text
$harness 启动已经确认的交付
$harness status
$harness validate
$harness resume
```

插件不注册 hook，也不启动后台进程。安装包由 canonical skill 生成，并通过以下命令检查
两者是否漂移：

```bash
python3 scripts/sync_codex_plugin.py --check
```

## 合并后的 Codex 原生工作流

`$harness` 只能显式调用，并运行唯一的 contract-to-Act 工作流：

- Plan 使用 Ultra、只读的原生 agent，并完成当前交付所需的需求澄清、设计、架构、范围和风险分析；
- Do 使用 High、workspace-write 的唯一写 agent；
- Check 使用全新的 Max、只读 agent，完成合同要求的测试、评审、发布就绪和精确 revision 验收；
- Act 不调用模型，由确定性代码决定完成、回 Do、重做 Plan 或阻塞。

批准合同初始化后立即进入 fail-closed schema v2；schema v1 只作为初始化或旧状态迁移的
中间态。每个阶段记录结构化项目内 artifact，并通过 checkpoint sequence 做 CAS 防并发
覆盖。完整约定见 [Harness skill](skills/harness/SKILL.md)。

## 状态与安全边界

所有活动状态都位于 `<project>/.harness/`；显式旧版迁移还会在旁边创建审计备份。
`status`、`validate` 和 `resume` 只读；只有覆盖全部验收项的独立 Check 加确定性 Act，才能
完成验收。

初始化后，验收标准即被冻结，3.0 命令不提供改写入口。修改验收标准意味着创建新的、
经用户确认的验收约定；替换前必须把原账本保留为审计记录。

具体用法见 [USAGE.md](USAGE.md)，操作约定见 [operations.md](docs/operations.md)，
结构见 [architecture.md](docs/architecture.md)，设计约束见
[principles.md](docs/principles.md)。

## 从 2.x 迁移

3.0 有意移除了 `full` 生命周期模式以及全部 `.engineering/` 生命周期行为。

| 2.x 状态或调用 | 3.0 处理方式 |
| --- | --- |
| 已有 2.x `.harness/` | 执行 `resume --migrate`。迁移会完整归档旧目录并创建干净的活动账本，可安全重复执行；普通 `status` 和 `resume` 不会暗中迁移。 |
| 同时存在 `.engineering/` 和 `.harness/` | 迁移 `.harness/`；3.0 忽略旧关联。另一个目录仅在项目确认不再需要时归档。 |
| 只有带旧 campaign 文件的 `.engineering/implementation/.harness/` | 执行 `resume --migrate`；这是唯一支持自动识别的嵌套旧状态位置。 |
| 其他 `.engineering/` 生命周期状态，且没有可识别的旧 `.harness/` | 重新审查仍然有效的验收标准，再初始化新账本；不做自动转换。 |
| `$harness-engineering full ...` | 改用 `$harness`；按交付规模把必要的生命周期分析折叠到 Plan。 |
| `$harness-engineering campaign ...` | 改用 `$harness`；批准合同与 PDCA 事件历史替代独立 campaign 状态。 |

plugin 与 skill 统一使用 `harness` 名称，`$harness` 是唯一调用入口。3.2 不恢复第二套
固定七阶段引擎，而是把这些职责合并进 contract-to-Act 主循环。原 `harness-plan` 源码
仍可从仓库历史中恢复，不再由任何 marketplace 发布。

迁移不会把旧 `done` 标签直接升级为已验收，只会把它保留为结果未知的历史声明；必须补充
当前且绑定源码版本的成功证据后，才能确认完成。

## Claude 兼容

`.claude-plugin/` 与 `./install.sh --claude` 向 Claude 兼容宿主提供持久合同与交接表面；
Ultra/High/Max agent 执行环仍只在 Codex 中运行。

## 校验本仓库

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py skills/harness
python3 scripts/sync_codex_plugin.py --check
python3 /path/to/plugin-creator/scripts/validate_plugin.py plugins/harness
python3 -m unittest discover -s tests -v
```
