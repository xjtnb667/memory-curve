# memory-curve

给 AI agent 用的记忆库：**会忘、会复习、会被情绪加权、夜里自己整理，而且不删东西。**

单文件、零依赖、纯 JSONL。`python mem.py --help` 就能看到全部命令。

> 大多数 agent 的记忆只有两种：向量库（什么都记得住，越堆越多，每条的权重还都一样），
> 或者整段聊天记录（贵、慢、必被压缩）。这个库把「会忘」当成特性来做：
> 一条记忆有多牢，是算出来的，不是它被写过几次。

---

## 它凭什么算得出来

五个机制，每个都能手算验证：

| 机制 | 公式 | 一句话 |
|---|---|---|
| 遗忘曲线 | `R = exp(-dt / S)` | `S` 是稳定度（天），`dt` 是距上次触及的天数 |
| 间隔重复 | `S' = S * (1 + 0.9 * (1 - R))` | 越接近遗忘时复习，涨得越多（spacing effect） |
| 情绪加权 | `S0 = base(kind) * (1 + 1.2|v|) * (0.6 + 0.8*imp) * (0.8 + 0.5*a)` | 有情绪、够重要、唤醒高的事，天生记得更牢 |
| 夜间巩固 | `consolidate` | 重放最显著的 15% / 合并重复 / 抽象规矩候选 / 归档 |
| 线索提取 | `score = sqrt(lexical) * (0.40 + salience) * mood_boost` | 字面线索 + 显著度 + 心境一致偏向 |

情绪是两级：`feel` 是快变量（一次事件的冲量），`state.json` 里的心境是慢变量
（按 8h / 2.5h 的时间常数自己回落），它会反过来改变「什么更容易被想起来」。

`kind` 决定初始稳定度的基数：

```python
BASE_S = {"episode": 2.0, "fact": 7.0, "preference": 21.0, "relation": 30.0, "rule": 90.0}
S_CAP  = 365.0   # 上限，防止复习几次就变永久
```

---

## 快速开始

```bash
python mem.py init
python mem.py add "今天把一个 40 分钟都没解决的按钮点开了，原因是坐标原点算错了" \
  --kind episode --tags 调试,坐标 --importance 0.8 --valence -0.3 --arousal 0.6
python mem.py recall 坐标
python mem.py stats
```

Windows 上用 `py mem.py ...` 或 `python mem.py ...` 都行；路径可以用环境变量 `MEMORY_HOME`
指到别处，也可以每个命令加 `--home D:\my-memory`。

---

## 命令

| 命令 | 干什么 |
|---|---|
| `init` | 建文件、初始化心境 |
| `add <text>` | 写一条：`--kind episode|fact|preference|relation|rule`、`--tags`、`--entities`、`--importance 0..1`、`--valence -1..1`、`--arousal 0..1`、`--at` |
| `recall [cue]` | 顺着线索想：`-k`、`--tag`、`--touch`（想过一遍就算复习） |
| `touch <id>` | 单独复习某一条 |
| `feel <why>` | 记一次情绪：`--valence -1..1`（必须给）、`--intensity 0..1`、`--target` |
| `mood` | 现在什么心情 + 最近三条情绪 |
| `stats [--proj N]` | 库里什么情况；`--proj` 只算不写，看 N 天后会沉下去几条 |
| `consolidate` | 收工跑一次：重放 / 合并 / 抽象规矩候选 / 归档 |
| `forget` | 打印遗忘曲线（0/1/3/7/30/90/365 天还剩几条） |

---

## 数据长什么样

一条记忆（`memories.jsonl`，一行一条）：

```json
{"id":"m2610301812_007","t":"2026-10-30T18:12+08:00","kind":"rule",
 "text":"发消息前先确认收件人，不指定就会发给默认对象。",
 "tags":["私信","发送"],"entities":["收件人"],
 "importance":0.95,"valence":-0.6,"arousal":0.7,
 "S":231.58,"last":"2026-10-30T18:12+08:00","n":3,"src":"user"}
```

一次情绪（`emotions.jsonl`）：`{"t":..., "why":..., "target":..., "valence":..., "intensity":..., "label":"anger"}`

心境（`state.json`）：`{"valence":0.25,"arousal":0.40,"last_feel":"...","label":"calm"}`

规矩（`rules.md`）：`consolidate` 只写**候选**，格式 `- [ ] pending \`标签\` —— 3 similar: ...`。
把 `[ ]` 改成 `[x]` 才算数 —— 这一步是刻意留给人/agent 自己的，机器不该替它定规矩。

---

## 接进一个 agent 的最小用法

1. **收工时**跑一次 `consolidate`（每天一次就够，它就是"睡觉"）。
2. **答话前**跑 `recall <关键词> --touch`：顺手把复习也做了，不用另开一步。
3. **有人给它东西/教它规矩**时，写 `--kind fact` 或 `--kind rule`，`--importance` 给高一点。
4. **它自己有情绪**时跑 `feel`（正=好受，负=难受）。攒着不记，心境就会回落到基线 ——
   这不是 bug：两天不记，它会当什么都没发生过。

---

## 三个刻意的设计取舍

**归档 ≠ 删除。** 沉进 `archive/all.jsonl` 的条目，线索对得上会被 `recall` 捞回来（打印时带 `⟲`），
`--touch` 还能把它挪回主库。所以「忘了」在这是「暂时想不起来」，不是销毁。

**规矩候选要点头。** `consolidate` 发现同一标签下 ≥3 条同类情节，只写一条候选进 `rules.md`。
不自动生效，是因为「从重复里抽出来的规律」经常是错的，让 agent 自己确认，它才会真信。

**情绪改变选择，不优化输出。** 心境只影响 `S0` 和提取偏向，不参与"写得好不好"。
状态差就是状态差，不该被拿来当生产力指标。

---

## 已知边界

- 这是**机制**，不是生理。它给出「算得出来的遗忘」，不声称任何主观体验。
- 不存凭据、不存别人的隐私、不存平台禁止记录的东西 —— 记忆库只装「它自己经历过的事」。
- 线索匹配是字符 bigram，没有语义向量。同义改写（"收件人" vs "发给谁"）可能捞不到；
  要语义检索，自己接 embedding，把 `lexical()` 换掉即可。
- 一个库几万条以内够用；再大该换存储，别指望单文件 JSONL 扛。

## License

MIT
