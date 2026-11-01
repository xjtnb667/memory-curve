# 机制细节与调参

这份文件是给「想改它」的人看的。README 讲怎么用，这里讲为什么这么算。

## 1. 可提取度 R

```
R(t) = exp(-dt / S)
dt   = (现在 - 上次触及) 的天数
S    = 稳定度（天）
```

`S` 大 = 忘得慢。`R ∈ (0,1]`，`R` 就是「这一刻还想得起来的概率」。
同一个公式用来做三件事：排序（谁先被想起来）、归档（沉不沉下去）、复习增益（该涨多少）。

## 2. 复习增益

```
S' = S * (1 + 0.9 * (1 - R))
```

`R≈1`（刚想起过）→ 几乎不涨；`R≈0.2`（快忘了）→ 涨接近 80%。
这就是 spacing effect 的算文化表达：**在最该忘的时候复习最值钱**。
`S_CAP = 365` 封顶，避免一条被复习十几次就变成永久记忆。

## 3. 初始稳定度 S0

```
S0 = base(kind) * (1 + 1.2|v|) * (0.6 + 0.8*imp) * (0.8 + 0.5*a)
```

| 因子 | 作用 | 取值范围 |
|---|---|---|
| `base(kind)` | 记忆类型的基本寿命 | episode 2 / fact 7 / preference 21 / relation 30 / rule 90 |
| `1 + 1.2|v|` | 情绪强度：难受和好受一样加深记忆 | 1.0 – 2.2 |
| `0.6 + 0.8*imp` | 重要性 | 0.6 – 1.4 |
| `0.8 + 0.5*a` | 唤醒度 | 0.8 – 1.3 |

一条 `importance=0.95, valence=-0.6, arousal=0.7` 的 rule：
`90 * 1.72 * 1.36 * 1.15 ≈ 242 天` —— 这就是「踩过的坑记得最牢」的算术版本。

## 4. 情绪两层

- 快变量：`feel` 一次 → `valence += 0.35 * intensity * sign`，`arousal += 0.45 * intensity`
- 慢变量：心境按时间常数回落

```
v(t) = BASE_V + (v0 - BASE_V) * exp(-dt_h / 8.0)
a(t) = BASE_A + (a0 - BASE_A) * exp(-dt_h / 2.5)
```

基线 `BASE_V = 0.25, BASE_A = 0.40`：略偏正面、中等唤醒。
唤醒比情绪**回落快三倍**——一阵火气过去了就是过去了。

## 5. 提取打分

```
score = sqrt(lexical) * (0.40 + salience) * mood_boost
salience = importance * R * (1 + 0.6|v|) * (1 + 0.3a)
```

- `sqrt(lexical)`：线索命中比例，开平方是为了「命中一半」不会输得太惨
- `0.40 + salience`：即使线索很弱，重要的事也能冒头
- `mood_boost`：`|mood_v| > 0.40` 时才生效，同号 1.30、异号 0.85（mood-congruent recall）

`lexical` 用字符 bigram：把查询和 `text + tags + entities` 都切成两字组求交集比例。
好处是中文不用分词；坏处是同义改写捞不到（见 README「已知边界」）。

## 6. 巩固（每天一次）

1. **重放**：显著度前 15% 的条目 `S *= 1.15`
2. **合并**：同标签 + `lexical >= 0.60` 的 episode 合成一条（重要度取大、S 取大、valence 取平均）
3. **抽象**：同一主标签下 ≥3 条 episode → 往 `rules.md` 追加一条 `[ ] pending` 候选
4. **归档**：`R < 0.05`，或 `R < 0.15 且 importance < 0.5` → 挪进 `archive/all.jsonl`

归档条目仍在检索池里，只是加权乘 0.55；`recall --touch` 会把它们挪回主库。

## 7. 实测曲线（一个 ~35 条的库）

```
after    0 day(s): still recall 21/21, mean R 0.909
after    1 day(s): still recall 21/21, mean R 0.775
after    3 day(s): still recall 20/21, mean R 0.587
after    7 day(s): still recall 14/21, mean R 0.388
after   30 day(s): still recall  6/21, mean R 0.189
after   90 day(s): still recall  4/21, mean R 0.096
after  365 day(s): still recall  0/21, mean R 0.001
```

注意 90 天还剩 4 条、365 天剩 0 条 —— 这是**没复习**的曲线。真实的库里规矩会被反复用到，
`S` 会一路涨到接近 `S_CAP`，所以长期看「规矩类」几乎不会掉出去，掉出去的都是情节。

## 8. 想调的时候动哪里

| 想要的效果 | 动什么 |
|---|---|
| 整体忘得更慢 | `BASE_S` 各项 ×2，或调高 `S_CAP` |
| 情节类型不要那么快消失 | `BASE_S["episode"]` 从 2.0 提到 4.0 |
| 规矩更容易被抽出来 | `consolidate` 里 `len(v) >= 3` 改成 2 |
| 归档更保守 | `ARCHIVE_R` 从 0.15 降到 0.10 |
| 心境回落更快/更慢 | `TAU_V`（8h）、`TAU_A`（2.5h） |
| 情绪对记忆的权重更强 | `s0()` 里 `1.2 * abs(valence)` 提到 1.6 |
| 检索更依赖字面、不靠重要度 | 打分里 `(0.40 + salience)` 的 0.40 调小 |
