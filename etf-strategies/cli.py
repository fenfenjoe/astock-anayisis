#!/usr/bin/env python
"""AStock ETF 策略管理 CLI — 交互式终端界面。

运行后展示功能菜单，上下键选择，回车执行。
入参通过交互流程获取，无需记忆命令行参数。
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ═══════════════════════════════════════════════════════════════
# 跨平台键盘输入（零依赖）
# ═══════════════════════════════════════════════════════════════

if os.name == "nt":
    import msvcrt

    def _get_key():
        """Windows: 读取单次按键。方向键返回 ('up'|'down'|'enter'|'esc')。"""
        while True:
            ch = msvcrt.getwch()
            if ch == "\r" or ch == "\n":
                return "enter"
            if ch == "\x1b":
                return "esc"
            if ch == "\xe0" or ch == "\x00":
                ch2 = msvcrt.getwch()
                if ch2 == "H":
                    return "up"
                if ch2 == "P":
                    return "down"
            if ch == "\x03":
                raise KeyboardInterrupt
else:
    import tty
    import termios

    def _get_key():
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\r" or ch == "\n":
                return "enter"
            if ch == "\x1b":
                ch2 = sys.stdin.read(2)
                if ch2 == "[A":
                    return "up"
                if ch2 == "[B":
                    return "down"
                return "esc"
            if ch == "\x03":
                raise KeyboardInterrupt
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ═══════════════════════════════════════════════════════════════
# 交互菜单组件
# ═══════════════════════════════════════════════════════════════

def _clear():
    os.system("cls" if os.name == "nt" else "clear")


def menu(title, options):
    """交互式菜单。options: [(label, value), ...]。
    返回用户选择的 value。"""
    idx = 0
    n = len(options)
    while True:
        _clear()
        print(f"  {title}")
        print(f"  {'=' * 50}\n")
        for i, (label, _) in enumerate(options):
            if i == idx:
                print(f"  ▶  {label}")
            else:
                print(f"     {label}")
        print(f"\n  ↑↓ 选择  Enter 确认  Esc 返回")

        key = _get_key()
        if key == "up":
            idx = (idx - 1) % n
        elif key == "down":
            idx = (idx + 1) % n
        elif key == "enter":
            return options[idx][1]
        elif key == "esc":
            return None


def pause():
    """按任意键继续。"""
    print(f"\n  按任意键返回主菜单...")
    try:
        _get_key()
    except KeyboardInterrupt:
        pass


# ═══════════════════════════════════════════════════════════════
# 功能入口
# ═══════════════════════════════════════════════════════════════

def _fn_list():
    """列出所有策略。"""
    from list_strategies import list_strategies
    _clear()
    list_strategies()
    pause()


def _fn_signal():
    """查看策略每日信号。"""
    from daily_signal import STRAT_MAP, generate_signal

    # 选策略
    options = [("全部策略 (--all)", "--all")]
    for sid, (sname, _) in STRAT_MAP.items():
        options.append((f"{sid}  {sname}", sid))
    options.append(("← 返回主菜单", None))

    choice = menu("📊 查看每日信号 — 选择策略", options)
    if choice is None:
        return

    _clear()
    if choice == "--all":
        for sid, (sname, strat) in STRAT_MAP.items():
            try:
                generate_signal(sid, sname, strat)
            except Exception as e:
                print(f"\n  ❌ {sid} 信号生成失败: {e}")
    else:
        sname, strat = STRAT_MAP[choice]
        try:
            generate_signal(choice, sname, strat)
        except Exception as e:
            print(f"\n  ❌ 信号生成失败: {e}")
            print("  请检查网络连接（需访问东财 push2his API）")
    pause()


def _fn_backtest():
    """运行全量回测。"""
    _clear()
    print("  ⏳ 正在运行全量回测（11个策略），请稍候...\n")
    from run_backtest import main as run_backtest
    run_backtest()
    print("\n  ✅ 回测完成！报告已生成。")
    pause()


# ═══════════════════════════════════════════════════════════════
# 主菜单
# ═══════════════════════════════════════════════════════════════

MAIN_MENU = [
    ("📋 列出所有策略       — 查看已维护的 11 个策略", _fn_list),
    ("📊 查看每日信号       — 查看策略今日买卖操作",  _fn_signal),
    ("🚀 运行全量回测       — 生成回测报告+图表",   _fn_backtest),
    ("🚪 退出",              None),
]


def _cmd_dispatch():
    """命令行参数模式：python cli.py <command> [args]"""
    import argparse
    from daily_signal import STRAT_MAP, generate_signal

    parser = argparse.ArgumentParser(description="AStock ETF 策略管理 CLI")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="列出所有策略")
    p_list.add_argument("--plain", action="store_true")

    p_sig = sub.add_parser("signal", help="查看策略每日信号")
    p_sig.add_argument("strategy", nargs="?", default=None)
    p_sig.add_argument("--all", action="store_true")

    p_bt = sub.add_parser("backtest", help="运行全量回测")

    args = parser.parse_args()

    if args.command == "list":
        _fn_list()
    elif args.command == "signal":
        if args.all:
            for sid, (sname, strat) in STRAT_MAP.items():
                try:
                    generate_signal(sid, sname, strat)
                except Exception as e:
                    print(f"\n  ❌ {sid} 信号生成失败: {e}")
        elif args.strategy:
            sid = args.strategy.upper()
            if sid not in STRAT_MAP:
                print(f"❌ 未知策略: {args.strategy}, 可用: {', '.join(STRAT_MAP)}")
                return
            sname, strat = STRAT_MAP[sid]
            try:
                generate_signal(sid, sname, strat)
            except Exception as e:
                print(f"\n❌ 信号生成失败: {e}")
        else:
            print("可用策略: " + ", ".join(STRAT_MAP.keys()))
    elif args.command == "backtest":
        _fn_backtest()
    else:
        parser.print_help()


def main():
    # 如果带了命令行参数 → 直接执行；否则进入交互模式
    if len(sys.argv) > 1:
        _cmd_dispatch()
        return

    while True:
        choice = menu("🏦 AStock ETF 策略管理", MAIN_MENU)
        if choice is None:
            break
        try:
            choice()
        except KeyboardInterrupt:
            break
        except Exception as e:
            _clear()
            print(f"\n  ❌ 执行出错: {e}")
            pause()

    _clear()
    print("  👋 再见！\n")


if __name__ == "__main__":
    main()
