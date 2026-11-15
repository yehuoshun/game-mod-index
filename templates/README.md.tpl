# 游戏 Mod 索引

> 把散落的游戏 mod 链接集中登记，并**每天自动核查最后更新时间**。
> 超过阈值没动的会浮到最上面单独列出——项目越加越多，旧 mod 也不会被新东西淹掉。

| 数据基准 | 收录 | 状态分布 |
| --- | --- | --- |
| {{DATA_STAMP}} | {{MOD_COUNT}} 个 mod · {{GAME_COUNT}} 个游戏 | {{STATS_LINE}} |

表格按「多久没更新」从久到近排序，最久没动的永远排在最前面。

## 🔔 需要关注

{{ATTENTION_BLOCK}}

## 📚 全部 Mod

{{MOD_TABLES}}

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

{{THRESHOLDS}}

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
