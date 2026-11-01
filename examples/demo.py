#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo —— 一分钟看完五个机制：写 / 想 / 复习 / 情绪 / 巩固 / 遗忘曲线

用法:
    python examples/demo.py            # 在临时目录里跑，跑完不删，路径会打印出来
    python examples/demo.py --keep     # 同上（默认就保留）
    python examples/demo.py --clean    # 跑完删掉临时目录

只调用 CLI，不 import mem.py —— 这样 demo 同时验证了命令行本身能用。
"""
import os
import shutil
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
MEM = os.path.join(os.path.dirname(HERE), "mem.py")


def run(home, *args):
    cmd = [sys.executable, MEM, "--home", home] + list(args)
    print("\n$ mem.py " + " ".join(args))
    r = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip())
    if r.returncode != 0:
        raise SystemExit("command failed: " + " ".join(args))


def main():
    home = tempfile.mkdtemp(prefix="memory-curve-demo-")
    print("demo home:", home)

    run(home, "init")

    # 1) 三种记忆，稳定度基数不同
    run(home, "add", "把一个卡了四十分钟的按钮点开了，原因是坐标原点取错。",
        "--kind", "episode", "--tags", "调试,坐标", "--entities", "按钮",
        "--importance", "0.8", "--valence", "-0.5", "--arousal", "0.7")
    run(home, "add", "发消息前必须先确认收件人，不指定会发给默认对象。",
        "--kind", "rule", "--tags", "发送", "--entities", "收件人",
        "--importance", "0.95", "--valence", "-0.6", "--arousal", "0.7")
    run(home, "add", "机器上装着一个我没在用的消息客户端，版本 4.2。",
        "--kind", "fact", "--tags", "环境", "--importance", "0.7")

    # 2) 顺着线索想
    run(home, "recall", "收件人", "--touch")

    # 3) 一次情绪 -> 心境
    run(home, "feel", "有人把一件小事托付给我，我接住了", "--valence", "0.6", "--intensity", "0.7")
    run(home, "mood")

    # 4) 巩固（相当于睡一觉）
    run(home, "consolidate")
    run(home, "stats", "--proj", "30")

    # 5) 遗忘曲线
    run(home, "forget")

    print("\n留在:", home)
    print("想自己接着玩: python mem.py --home", home, "stats")
    if "--clean" in sys.argv:
        shutil.rmtree(home, ignore_errors=True)
        print("(已删除临时目录)")


if __name__ == "__main__":
    main()
