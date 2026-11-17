# 游戏 Mod 索引

> 把散落的游戏 mod 链接集中登记，并**每天自动核查最后更新时间**。
> 超过阈值没动的会浮到最上面单独列出——项目越加越多，旧 mod 也不会被新东西淹掉。

| 数据基准 | 收录 | 状态分布 |
| --- | --- | --- |
| 2026-11-17 11:49（北京时间） | 5 个 mod · 2 个游戏 | ✅ 活跃 3 · 🟡 低频 1 · ⏳ 停滞 1 |

主表格按「最后更新」从新到旧排列；久未更新的不在这张表里比早晚，看上面「需要关注」区块。

## 🔔 需要关注

> 共 **1** 条需要关注，按「多久没动」从久到近排列。

| 状态 | Mod | 最后更新 | 未更新 | 该做什么 |
| --- | --- | --- | --- | --- |
| ⏳ 停滞 | [STS2 AI Teammate](https://github.com/yehuoshun/STS2-AiTeammate) | 2026-07-18 | 122 天 | 看一眼上游 API/依赖有没有变；还能跑就先放着，或把 config 阈值调宽 |

## 📚 全部 Mod

### 杀戮尖塔 2 · Slay the Spire 2  `sts2`

| Mod | 类型 | 上游 | 最后更新 | 未更新 | 状态 | 最新版 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [sts2-mod-examples](https://github.com/yehuoshun/sts2-mod-examples) | 示例 | yehuoshun/sts2-mod-examples | 2026-11-17 | 今天 | ✅ 活跃 | — | 纯原生 mod 示例仓库：卡牌/能力/遗物/药水/附魔/事件的可编译样例 |
| [ShunMod](https://github.com/yehuoshun/STS2-ShunMod) | mod | yehuoshun/STS2-ShunMod | 2026-11-12 | 2 天 | ✅ 活跃 | 0.113 | 自研主线 mod：舜角色的卡牌/遗物/事件 + 共享核心框架 ShunMod_Core |
| [SpireTheRpg](https://github.com/yehuoshun/SpireTheRpg) | mod | yehuoshun/SpireTheRpg | 2026-10-02 | 46 天 | 🟡 低频 | — | 尖塔 RPG 化改造：装备/融合/强化/锻造/卷轴/掉落系统（反编译源码整理，暂无 README） |
| [STS2 AI Teammate](https://github.com/yehuoshun/STS2-AiTeammate) | mod | yehuoshun/STS2-AiTeammate | 2026-07-18 | 122 天 | ⏳ 停滞 | — | AI 队友 mod：本地伪联机里自动战斗/选牌/用药水/逛商店（fork 上游后适配当前版本） |

### 末世：我有一辆房车 · Rebirth Hoarder  `rebirth-hoarder`

| Mod | 类型 | 上游 | 最后更新 | 未更新 | 状态 | 最新版 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [末世房车 MOD 工具库](https://github.com/yehuoshun/rebirth-hoarder-mod) | mod | yehuoshun/rebirth-hoarder-mod | 2026-11-03 | 14 天 | ✅ 活跃 | v3.23 | F8 修改面板 + 独立存档修改器，中英双语、按语义锚点自动适配游戏小版本（fork 自 thus1235，另加 CI 打包发布） |

## ➕ 怎么登记新 mod

**方式一：直接改 YAML**（推荐给 AI 或批量操作）——在 `mods/<游戏>.yaml` 末尾追加一条，然后跑一次脚本：

```yaml
- id: shunmod                  # 唯一 id，跨次核查靠它对齐，改名也别动
  name: ShunMod                # 显示名
  repo: yehuoshun/STS2-ShunMod # GitHub 仓库 owner/name（自动核查用）
  kind: mod                    # mod | lib | template | example | tool
  lifecycle: active            # active | paused | archived，手填优先于自动判定
  summary: 一句话说明           # 出现在表格「说明」列
  tags: [自研, 角色]            # 仅作检索线索，不进表格
```

**方式二：命令行追加**：

```bash
python scripts/modindex.py add --game sts2 --name "X" --repo owner/repo --summary "一句话"
python scripts/modindex.py all
```

**非 GitHub 链接**（Nexus / 创意工坊 / 网盘）：把 `repo` 换成 `url`，并手填 `last_checked: 2026-11-15`——这类页面拿不到「最后更新时间」，新鲜度只能按你上次人工确认的日期算。

## 🚦 状态口径

| 状态 | 判据 |
| --- | --- |
| ✅ 活跃 | 最后更新在 30 天内 |
| 🟡 低频 | 31–90 天没更新 |
| ⏳ 停滞 | 91–180 天没更新 |
| 🪦 疑似废弃 | 超过 180 天没更新 |
| 📦 已归档 | 仓库被归档，或你手动标了 `lifecycle: archived` |

阈值写在 `config.yaml` 的 `freshness`，改一行就生效（当前 30/90/180 天）。

- `lifecycle: archived` = 你主动结项，不再进「需要关注」；`paused` = 暂时停手，仍然统计但不告警。
- 判定用的是仓库 `pushed_at`（任意分支的最后一次推送），比 release 日期更接近真实活跃度；没有发行版也照样能算。

## ⚙️ 自动化

- `每日核查`（`.github/workflows/sync.yml`）：每天 05:17（北京）拉一轮元数据。**只有元数据真的变了、或某条 mod 跨越了状态阈值才提交**，所以不会被每天 +1 天的天数刷屏。
- `校验`（`.github/workflows/ci.yml`）：每次 push 校验 YAML 合法、跑单元测试、确认 `README.md` 与 `data/latest.json` 一致。
- 本地手动：`pip install -r requirements.txt`，然后 `python scripts/modindex.py all`。

## 🗂 目录结构

```
mods/              登记表：一个游戏一个 yaml —— 唯一需要手写的数据源
data/latest.json   核查快照（脚本生成，别手改）
templates/         README 模板（文案改这里，别改生成出来的 README）
scripts/           modindex.py：sync / render / check / add
config.yaml        阈值、时区、游戏分组顺序
tests/             状态分档与渲染的单元测试
```
