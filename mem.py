#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mem.py —— 一个给 AI agent 用的记忆库（遗忘曲线 + 间隔重复 + 情绪权重 + 夜间巩固 + 线索提取）

五个机制，都可验算，不是比喻：

  1. 遗忘曲线   R = exp(-dt / S)          S = 稳定度(天)，dt = 距上次触及(天)
  2. 间隔重复   S' = S * (1 + 0.9(1-R))   越接近遗忘时复习，涨得越多（spacing effect）
  3. 情绪加权   S0 = base(kind) * (1 + 1.2|v|) * (0.6 + 0.8*imp) * (0.8 + 0.5*a)
  4. 夜间巩固   consolidate：重放增强 / 去重合并 / 抽象成规矩候选 / 归档
  5. 线索提取   recall：字面线索(bigram) + 显著度 + 心境一致偏向(mood-congruent)

情绪是两级：快变量（一次 feel）→ 慢变量（心境，按时间常数自己回落）→ 反过来影响
「什么更容易被想起」和「写进来时记得多牢」。

设计上刻意保留的三条：
  · 归档不是删除：沉进 archive/all.jsonl，线索对得上还能捞回来。
  · 规矩不是自动生成的：consolidate 只写「候选」，要 agent 自己点头才变成 [x]。
  · 记忆库不写规则之外的东西：不存凭据、不存别人的隐私。

零第三方依赖，单文件，Python 3.8+。
用法见 README.md：`python mem.py --help`
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 数据放在哪：环境变量 MEMORY_HOME，否则 ~/.memory-curve
ROOT = os.environ.get("MEMORY_HOME") or os.path.join(os.path.expanduser("~"), ".memory-curve")
MEM = os.path.join(ROOT, "memories.jsonl")
EMO = os.path.join(ROOT, "emotions.jsonl")
STATE = os.path.join(ROOT, "state.json")
RULES = os.path.join(ROOT, "rules.md")
ARCHIVE = os.path.join(ROOT, "archive")
ARCH_PATH = os.path.join(ARCHIVE, "all.jsonl")

# 写入时的初始稳定度（天）。情节最快忘，规矩最慢忘 —— 这几个数是可调的旋钮。
BASE_S = {
    "episode": 2.0,     # 今天发生的一件事
    "fact": 7.0,        # 一条事实（谁、在哪、版本号）
    "preference": 21.0, # 一个偏好（喜欢什么、讨厌什么）
    "relation": 30.0,   # 和某个人的关系里的一条
    "rule": 90.0,       # 一条规矩（踩过坑换来的）
}
S_CAP = 365.0          # 稳定度上限，防止复习几次就变永久记忆
ARCHIVE_R = 0.15       # 可提取度低于它 + 不重要 -> 归档
ARCHIVE_R_HARD = 0.05  # 低于它 -> 一律归档
BASE_V, BASE_A = 0.25, 0.40   # 基线心境：略偏正面、中等唤醒
TAU_V, TAU_A = 8.0, 2.5       # 心境回落时间常数（小时）


# ---------- 时间 ----------
def now():
    return datetime.now().astimezone()


def parse(s):
    return datetime.fromisoformat(s)


def iso(t):
    return t.isoformat(timespec="minutes")


def days(a, b):
    return max(0.0, (b - a).total_seconds() / 86400.0)


# ---------- 读写（写都用临时文件 + replace，断电不会写坏） ----------
def ensure():
    for d in (ROOT, ARCHIVE):
        os.makedirs(d, exist_ok=True)
    for p in (MEM, EMO):
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8"):
                pass


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def write_jsonl(path, items):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def append_jsonl(path, item):
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------- 情绪（快变量 -> 心境） ----------
def load_state(t=None):
    st = {"valence": BASE_V, "arousal": BASE_A, "last_feel": None,
          "label": "calm", "upd": iso(now())}
    if os.path.exists(STATE):
        try:
            with open(STATE, "r", encoding="utf-8") as f:
                st.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return decay_state(st, t or now())


def decay_state(st, t):
    if st.get("last_feel"):
        dt_h = max(0.0, (t - parse(st["last_feel"])).total_seconds() / 3600.0)
        st["valence"] = BASE_V + (st["valence"] - BASE_V) * math.exp(-dt_h / TAU_V)
        st["arousal"] = BASE_A + (st["arousal"] - BASE_A) * math.exp(-dt_h / TAU_A)
    st["valence"] = max(-1.0, min(1.0, st["valence"]))
    st["arousal"] = max(0.0, min(1.0, st["arousal"]))
    st["label"] = label_of(st["valence"], st["arousal"])
    st["last_feel"] = iso(t)
    st["upd"] = iso(t)
    return st


def save_state(st):
    with open(STATE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def label_of(v, a):
    """把 (valence, arousal) 翻成一个词。想用别的语言就改这里。"""
    if v > 0.40 and a >= 0.50:
        return "joy"        # 乐
    if v > 0.40:
        return "like"       # 喜
    if v < -0.30 and a >= 0.50:
        return "anger"      # 怒
    if v < -0.30:
        return "sad"        # 哀
    return "calm"           # 平静


# ---------- 记忆核心 ----------
def retrievability(m, t):
    """这一刻还想得起来的概率。"""
    dt = days(parse(m["last"]), t)
    return math.exp(-dt / max(0.05, m["S"]))


def salience(m, t):
    """重要性 × 可提取度 × 情绪强度：决定「同一批线索里谁先冒出来」。"""
    r = retrievability(m, t)
    return m["importance"] * r * (1 + 0.6 * abs(m["valence"])) * (1 + 0.3 * m["arousal"])


def s0(kind, importance, valence, arousal):
    """刚写进来时它有多牢。情绪越强、越重要、唤醒越高 -> S 越大。"""
    base = BASE_S.get(kind, 2.0)
    s = base * (1 + 1.2 * abs(valence)) * (0.6 + 0.8 * importance) * (0.8 + 0.5 * arousal)
    return min(S_CAP, round(s, 3))


def new_id(t):
    n = len(read_jsonl(MEM)) + 1
    return "m%s_%03d" % (t.strftime("%y%m%d%H%M"), n)


def bigrams(s):
    """字符串双字组：中英混排都能用，不依赖分词器。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s.lower())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def lexical(q, m):
    qb = bigrams(q)
    if not qb:
        return 0.0
    hay = m["text"] + " " + " ".join(m.get("tags", [])) + " " + " ".join(m.get("entities", []))
    tb = bigrams(hay)
    hit = len(qb & tb)
    if hit == 0:
        return 0.0
    return (hit / len(qb)) * (1.0 + 0.15 * len(qb & bigrams(" ".join(m.get("entities", [])))))


def cmd_add(a):
    ensure()
    t = parse(a.at) if a.at else now()
    kind = a.kind if a.kind in BASE_S else "episode"
    rec = {
        "id": new_id(t),
        "t": iso(t),
        "kind": kind,
        "text": a.text.strip(),
        "tags": [x for x in (a.tags or "").replace("，", ",").split(",") if x],
        "entities": [x for x in (a.entities or "").replace("，", ",").split(",") if x],
        "importance": max(0.0, min(1.0, a.importance)),
        "valence": max(-1.0, min(1.0, a.valence)),
        "arousal": max(0.0, min(1.0, a.arousal)),
        "S": s0(kind, a.importance, a.valence, a.arousal),
        "last": iso(t),
        "n": 0,
        "src": a.src,
    }
    append_jsonl(MEM, rec)
    if not a.quiet:
        print("remembered %s [%s] S=%.2fd  %s" % (rec["id"], kind, rec["S"], rec["text"][:40]))
    return rec


def cmd_recall(a):
    ensure()
    t = parse(a.at) if a.at else now()
    st = load_state()
    mood_v = st["valence"]
    q = a.query or ""
    rows = []
    arch = read_jsonl(ARCH_PATH)
    arch_ids = {x["id"] for x in arch}
    for m in read_jsonl(MEM) + arch:
        if a.tag and a.tag not in m.get("tags", []):
            continue
        lx = lexical(q, m) if q else 0.5
        if lx <= 0.0:
            continue
        s = salience(m, t)
        boost = 1.0
        if abs(mood_v) > 0.40:
            # 心境一致：心情好时更容易想起高兴的事，反之亦然
            boost = 1.30 if (mood_v > 0) == (m["valence"] > 0) else 0.85
        score = (lx ** 0.5) * (0.40 + s) * boost
        rows.append((score, s, retrievability(m, t), m))
    rows.sort(key=lambda r: -r[0])
    rows = rows[:max(1, a.k)]
    if not rows:
        print("(nothing found. try another cue, or it is really gone.)")
        return
    print("cue %r -> %d hit(s) (mood %s, v=%+.2f)" % (q or "*", len(rows), st["label"], mood_v))
    for score, s, r, m in rows:
        print("  %s %s %-3s  R=%.2f S=%6.1fd  %s" % (m["id"],
              "\u27f2" if m["id"] in arch_ids else " ", m["kind"][:3], r, m["S"], m["text"][:50]))
    if a.touch:
        act = read_jsonl(MEM)
        arch = read_jsonl(ARCH_PATH)
        moved = 0
        for _, _, _, m in rows:
            r = retrievability(m, t)
            m["S"] = min(S_CAP, round(m["S"] * (1 + 0.9 * (1 - r)), 3))
            m["last"] = iso(t)
            m["n"] = m["n"] + 1
            hit = [x for x in act if x["id"] == m["id"]]
            if hit:
                hit[0].update(m)
            else:
                m.pop("archived_at", None)
                arch = [x for x in arch if x["id"] != m["id"]]
                act.append(m)
                moved += 1
        write_jsonl(MEM, act)
        write_jsonl(ARCH_PATH, arch)
        print("  (rehearsed: S grew by spacing%s)"
              % (", %d archived item(s) pulled back" % moved if moved else ""))


def cmd_touch(a):
    ensure()
    t = now()
    ms = read_jsonl(MEM)
    hit = 0
    for m in ms:
        if m["id"] == a.id:
            r = retrievability(m, t)
            m["S"] = min(S_CAP, round(m["S"] * (1 + 0.9 * (1 - r)), 3))
            m["last"] = iso(t)
            m["n"] += 1
            hit += 1
            print("rehearsed %s  R=%.2f -> S=%.2fd  (#%d)" % (m["id"], r, m["S"], m["n"]))
    if not hit:
        print("no such id: %s" % a.id)
        return
    write_jsonl(MEM, ms)


def cmd_feel(a):
    ensure()
    t = parse(a.at) if a.at else now()
    st = load_state(t)
    sign = 1 if a.valence >= 0 else -1
    st["valence"] = max(-1.0, min(1.0, st["valence"] + 0.35 * a.intensity * sign))
    st["arousal"] = max(0.0, min(1.0, st["arousal"] + 0.45 * a.intensity))
    st["label"] = label_of(st["valence"], st["arousal"])
    st["last_feel"] = iso(t)
    st["upd"] = iso(t)
    save_state(st)
    append_jsonl(EMO, {"t": iso(t), "why": a.why, "target": a.target or "",
                       "valence": a.valence, "intensity": a.intensity,
                       "label": st["label"]})
    print("mood -> %s (v=%+.2f a=%.2f) | because: %s"
          % (st["label"], st["valence"], st["arousal"], a.why))
    return st


def cmd_mood(a):
    ensure()
    st = load_state(parse(a.at) if a.at else None)
    save_state(st)
    print("now: %s  valence=%+.2f  arousal=%.2f  (baseline %+.2f / %.2f)"
          % (st["label"], st["valence"], st["arousal"], BASE_V, BASE_A))
    for e in read_jsonl(EMO)[-3:]:
        print("   %s %s %+.1f  %s%s" % (e["t"][5:16], e["label"], e["valence"],
                                        e["why"][:30], (" ->" + e["target"]) if e.get("target") else ""))


def cmd_stats(a):
    ensure()
    t = parse(a.at) if a.at else now()
    ms = read_jsonl(MEM)
    if not ms:
        print("library is empty.")
        return
    by_kind = {}
    for m in ms:
        by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1
    print("%d item(s)  %s  archived %d"
          % (len(ms), " ".join("%s:%d" % kv for kv in sorted(by_kind.items())),
             len(read_jsonl(ARCH_PATH))))
    rows = sorted(((salience(m, t), retrievability(m, t), m) for m in ms), reverse=True)
    print("-- top 5 easiest to recall --")
    for s, r, m in rows[:5]:
        print("  %.3f R=%.2f S=%6.1fd %s" % (s, r, m["S"], m["text"][:46]))
    print("-- top 5 fading --")
    for s, r, m in rows[-5:]:
        print("  %.3f R=%.2f S=%6.1fd %s" % (s, r, m["S"], m["text"][:46]))
    if a.proj:
        d = float(a.proj)
        ft = datetime.fromtimestamp(t.timestamp() + d * 86400).astimezone()
        r_ft = [(retrievability(m, ft), m) for m in ms]
        will_arch = [m for r, m in r_ft
                     if r < ARCHIVE_R_HARD or (r < ARCHIVE_R and m["importance"] < 0.5)]
        hard = [m for r, m in r_ft if r < ARCHIVE_R_HARD]
        print("-- projected +%d day(s) (no write) --" % d)
        print("   %d will sink into archive; %d of them are not even 'important'"
              " (they sink, they are not deleted - a matching cue can pull them back)"
              % (len(will_arch), len(hard)))


def cmd_consolidate(a):
    ensure()
    t = parse(a.at) if a.at else now()
    ms = read_jsonl(MEM)
    if not ms:
        print("library is empty, nothing to consolidate.")
        return
    rep = []

    # 1) 重放：最显著的 15% 加固
    order = sorted(ms, key=lambda m: -salience(m, t))
    top = order[:max(1, int(len(ms) * 0.15))]
    for m in top:
        m["S"] = min(S_CAP, round(m["S"] * 1.15, 3))
    rep.append("replayed %d item(s), S x1.15" % len(top))

    # 2) 去重：同一批标签、措辞几乎一样的 episode 合成一条
    merged = 0
    kept, used = [], set()
    for i, m in enumerate(ms):
        if i in used:
            continue
        if m["kind"] == "episode":
            for j in range(i + 1, len(ms)):
                if j in used or ms[j]["kind"] != "episode":
                    continue
                o = ms[j]
                if set(m.get("tags", [])) == set(o.get("tags", [])) and lexical(m["text"], o) >= 0.60:
                    m["importance"] = max(m["importance"], o["importance"])
                    m["S"] = max(m["S"], o["S"])
                    m["valence"] = (m["valence"] + o["valence"]) / 2
                    m["n"] += o["n"] + 1
                    used.add(j)
                    merged += 1
        kept.append(m)
    rep.append("merged %d duplicate(s)" % merged)

    # 3) 抽象：同一个主标签下 >=3 条 episode -> 写一条「待确认」的规矩候选
    groups = {}
    for m in kept:
        if m["kind"] == "episode":
            for tg in m.get("tags", [])[:1]:
                groups.setdefault(tg, []).append(m)
    cands = [(k, v) for k, v in groups.items() if len(v) >= 3]
    have = set()
    if os.path.exists(RULES):
        with open(RULES, "r", encoding="utf-8") as f:
            txt = f.read()
        have = set(re.findall(r"^- \[.\] (?:pending )?`([^`]+)`", txt, re.M))
    new = [(k, v) for k, v in cands if k not in have]
    if new:
        with open(RULES, "a", encoding="utf-8", newline="\n") as f:
            for k, v in new:
                f.write("\n- [ ] pending `%s` —— %d similar: %s\n" % (
                    k, len(v), " | ".join(x["text"][:24] for x in v[:3])))
        rep.append("%d rule candidate(s) written to rules.md (must be accepted by the agent)" % len(new))

    # 4) 归档：不是删除
    os.makedirs(ARCHIVE, exist_ok=True)
    keep, arch = [], []
    for m in kept:
        r = retrievability(m, t)
        if r < ARCHIVE_R_HARD or (r < ARCHIVE_R and m["importance"] < 0.5):
            arch.append(m)
        else:
            keep.append(m)
    if arch:
        for m in arch:
            m["archived_at"] = iso(t)
            append_jsonl(ARCH_PATH, m)
        rep.append("archived %d item(s) (still in archive/all.jsonl; a cue can pull them back)" % len(arch))

    write_jsonl(MEM, keep)
    print("consolidated (%s)" % iso(t))
    for line in rep:
        print("  - " + line)


def cmd_forget(a):
    ensure()
    t = now()
    ms = read_jsonl(MEM)
    if not ms:
        print("library is empty.")
        return
    for d in (0, 1, 3, 7, 30, 90, 365):
        ft = datetime.fromtimestamp(t.timestamp() + d * 86400).astimezone()
        alive = sum(1 for m in ms if retrievability(m, ft) >= ARCHIVE_R)
        avg = sum(retrievability(m, ft) for m in ms) / len(ms)
        print("  after %4d day(s): still recall %2d/%d, mean R %.3f" % (d, alive, len(ms), avg))


def cmd_init(a):
    ensure()
    if not os.path.exists(RULES):
        with open(RULES, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Intuitions (grown out of repeated events)\n\n"
                    "`mem.py consolidate` appends candidates here. "
                    "A candidate does not count until the agent flips [ ] to [x].\n")
    st = load_state()
    save_state(st)
    print("ready: %s" % ROOT)
    print("memories %d, emotion records %d, mood %s"
          % (len(read_jsonl(MEM)), len(read_jsonl(EMO)), st["label"]))


def main():
    p = argparse.ArgumentParser(description="agent memory store with a forgetting curve")
    p.add_argument("--home", default="", help="data dir (default: $MEMORY_HOME or ~/.memory-curve)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create files").set_defaults(fn=cmd_init)

    a = sub.add_parser("add", help="write one memory")
    a.add_argument("text")
    a.add_argument("--kind", default="episode", choices=list(BASE_S.keys()))
    a.add_argument("--tags", default="")
    a.add_argument("--entities", default="")
    a.add_argument("--importance", type=float, default=0.6, help="0..1")
    a.add_argument("--valence", type=float, default=0.0, help="-1..1")
    a.add_argument("--arousal", type=float, default=0.3, help="0..1")
    a.add_argument("--src", default="self")
    a.add_argument("--at", default="", help="when it happened (backfill)")
    a.add_argument("--quiet", action="store_true")
    a.set_defaults(fn=cmd_add)

    r = sub.add_parser("recall", help="search by cue")
    r.add_argument("query", nargs="?", default="")
    r.add_argument("-k", type=int, default=5)
    r.add_argument("--tag", default="")
    r.add_argument("--touch", action="store_true", help="recalling counts as rehearsal")
    r.add_argument("--at", default="")
    r.set_defaults(fn=cmd_recall)

    t = sub.add_parser("touch", help="rehearse one item")
    t.add_argument("id")
    t.set_defaults(fn=cmd_touch)

    f = sub.add_parser("feel", help="record one emotion")
    f.add_argument("why")
    f.add_argument("--valence", type=float, required=True, help="-1..1 (positive = felt good)")
    f.add_argument("--intensity", type=float, default=0.5, help="0..1")
    f.add_argument("--target", default="")
    f.add_argument("--at", default="")
    f.set_defaults(fn=cmd_feel)

    m = sub.add_parser("mood", help="current mood")
    m.add_argument("--at", default="")
    m.set_defaults(fn=cmd_mood)

    s = sub.add_parser("stats", help="what is in the library")
    s.add_argument("--at", default="")
    s.add_argument("--proj", default="", help="project N days ahead (read-only)")
    s.set_defaults(fn=cmd_stats)

    c = sub.add_parser("consolidate", help="nightly: replay / merge / abstract / archive")
    c.add_argument("--at", default="")
    c.set_defaults(fn=cmd_consolidate)

    sub.add_parser("forget", help="print the forgetting curve").set_defaults(fn=cmd_forget)

    args = p.parse_args()
    if args.home:
        global ROOT, MEM, EMO, STATE, RULES, ARCHIVE, ARCH_PATH
        ROOT = os.path.abspath(args.home)
        MEM = os.path.join(ROOT, "memories.jsonl")
        EMO = os.path.join(ROOT, "emotions.jsonl")
        STATE = os.path.join(ROOT, "state.json")
        RULES = os.path.join(ROOT, "rules.md")
        ARCHIVE = os.path.join(ROOT, "archive")
        ARCH_PATH = os.path.join(ARCHIVE, "all.jsonl")
    args.fn(args)


if __name__ == "__main__":
    main()
