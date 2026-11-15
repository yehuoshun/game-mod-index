# AGENTS.md — game-mod-index 项目约定

## 这个仓库是什么

游戏 mod 的集中索引。**唯一手写的数据源是 `mods/*.yaml`**；`README.md` 和 `data/latest.json` 都由 `scripts/modindex.py` 生成，不要手动编辑（CI 会因不一致报错）。

## 改东西的正确姿势

| 想做什么 | 改哪里 |
| --- | --- |
| 登记 / 删除一个 mod | `mods/<游戏>.yaml`，然后 `python scripts/modindex.py all` |
| 改阈值（多久算停滞） | `config.yaml` 的 `freshness` |
| 改 README 文案、加说明段 | `templates/README.md.tpl`，然后 `python scripts/modindex.py render` |
| 加新游戏 | `config.yaml` 的 `games` 加一项 + 新建 `mods/<key>.yaml` |
| 改核查逻辑 | `scripts/modindex.py`，同时补 `tests/test_status.py` |

改完必须本地跑一遍：

```bash
python scripts/modindex.py check     # YAML 语法与字段
python -m unittest discover -s tests -v
python scripts/modindex.py render --check
```

三条全绿再提交。

## 数据字段

必填 `id`（唯一、稳定，改名也别动，跨次核查靠它对齐）、`name`、`repo`（或 `url`）、`kind`。

- `kind`：`mod` | `lib` | `template` | `example` | `tool`
- `lifecycle`：`active` | `paused` | `archived`，手填优先于自动判定；`archived` 不进「需要关注」
- 非 GitHub 链接用 `url` 替代 `repo`，并手填 `last_checked: YYYY-MM-DD`
- 内部字段 `_game` 由加载器注入，别写进 YAML

## 状态口径

判定基准是仓库 `pushed_at`（任意分支最后一次推送），不是 release 日期。分档由 `config.yaml` 的阈值决定，默认 ≤30 活跃 / 31–90 低频 / 91–180 停滞 / >180 疑似废弃。

## 提交与推送

- 提交信息：中文，`范围: 改了什么(为什么)`，范围用 `mods` / `scripts` / `docs` / `chore`。
- 一修改一 push，立刻推 `origin main`，不留本地。
- PowerShell 5.1 下 `git push` 即使成功也可能返回 exit 1，以 `git status -sb` 显示 `## main...origin/main`（无 ahead）为准。
- 禁止 `git reset --hard` / `git checkout -- .` / `git clean -fd` / `git push --force`。
- 每日核查 workflow 会自己提交 `chore: 每日核查更新 mod 元数据（日期）`，本地 pull 时注意别和它抢同一处改动。

## 凭据

GitHub token 只从环境变量 `GITHUB_TOKEN` 读（Actions 里用内置 secrets）。**不要把 token 写进这个仓库的任何文件**——仓库是公开的。
