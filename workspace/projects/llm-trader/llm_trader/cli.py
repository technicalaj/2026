from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from llm_trader import __version__, bridge, pipeline
from llm_trader.config import CONFIRM_WORD, Paths, SettingsError, default_paths, load_dotenv, load_settings, section
from llm_trader.data.symbols import MissingCostsError
from llm_trader.eval.plans import lock_plan, make_plan, save_plan
from llm_trader.models import iso
from llm_trader.risk.approvals import ApprovalError, Approvals, UnknownChange
from llm_trader.risk.killswitch import KillSwitch, KillSwitchError
from llm_trader.signals.registry import all_rules, get_rule

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m llm_trader", description=f"Superagentic {__version__}: research and supervision desk. It never places trades.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run every agent once and write out/state.json, out/report.md and the bridge file")
    source = run.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="use the synthetic demo data")
    source.add_argument("--data", metavar="DIR", help="folder with your MT5 export, or 'mt5' for data.mt5_dir in settings")
    run.add_argument("--llm", action="store_true", help="let Claude write the review text (needs ANTHROPIC_API_KEY)")
    demo = sub.add_parser("demo", help="run on the demo data and write out/dashboard.html (open it in any browser)")
    demo.add_argument("--llm", action="store_true", help="let Claude write the review text (needs ANTHROPIC_API_KEY)")
    serve = sub.add_parser("serve", help="show the dashboard in your browser (this computer only)")
    serve.add_argument("--host", help="address to listen on (default 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port (default 8765)")
    snapshot = sub.add_parser("snapshot", help="write the dashboard as one self-contained HTML file")
    snapshot.add_argument("--out", help="where to write it (default out/dashboard.html)")
    lock = sub.add_parser("lock", help="lock (hash) a rule's test plan; needs --yes")
    lock.add_argument("rule", nargs="?", help="rule id, for example sweep_fade")
    lock.add_argument("--all", action="store_true", help="lock every rule's plan")
    lock.add_argument("--yes", action="store_true", help="confirm this is your decision")
    killswitch = sub.add_parser("killswitch", help="turn the kill switch on, or off with --yes")
    killswitch.add_argument("state", choices=["on", "off"])
    killswitch.add_argument("--yes", action="store_true", help="needed to turn it off")
    killswitch.add_argument("--reason", help="why you are turning it on")
    approve = sub.add_parser("approve", help="approve a pending change; needs --yes")
    approve.add_argument("id")
    approve.add_argument("--yes", action="store_true", help="confirm this is your decision")
    reject = sub.add_parser("reject", help="reject a pending change")
    reject.add_argument("id")
    return parser


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def summary_text(state: dict) -> str:
    meta = state["meta"]
    lines = [
        f"Superagentic {meta['version']} | {meta['data_mode']} data | AI {meta['llm_mode']} | kill switch "
        f"{'ON' if meta['kill_switch']['on'] else 'off'} | safe mode {'ON' if meta['safe_mode']['on'] else 'off'}",
        "",
        f"{'Agent':<30} {'Gate':<13} {'Never-seen wins':<16} {'95% CI':<10} {'Full stop':<10} Stage",
    ]
    for r in state["research"]:
        h = r["windows"]["holdout"]
        lo, hi = h["win_rate_ci"]
        ci = f"{lo:.0%}-{hi:.0%}" if h["trades"] else "-"
        lines.append(f"{r['name'][:30]:<30} {r['gate']['status']:<13} {_pct(h['win_rate']) + ' of ' + str(h['trades']):<16} "
                     f"{ci:<10} {_pct(h['full_stop_rate']):<10} {r['stage']}")
    lines += [
        "",
        f"Accuracy bar: {meta['accuracy_bar']:.0%} on never-seen months, after costs, and better than random entries.",
        meta["eligible_note"],
        f"Bridge: {state['bridge']['written']} signal(s). {state['bridge']['note']}",
    ]
    if meta["safe_mode"]["on"]:
        lines.append(f"Safe mode: {meta['safe_mode']['reason']}")
        lines += [f"  {p['id']}: {p['summary']}" for p in state["approvals"]["pending"]]
    lines += ["", "Wrote out/state.json, out/report.md and out/bridge/signals.json.",
              "Dashboard: python -m llm_trader serve   (one-file copy: python -m llm_trader snapshot)"]
    return "\n".join(lines)


def _refresh(paths: Paths) -> None:
    last = pipeline.last_run(paths)
    try:
        state = pipeline.run(last.get("data"), bool(last.get("use_llm")), paths)
    except (SettingsError, OSError, ValueError, KeyError) as exc:
        print(f"Note: the dashboard data was not refreshed ({exc}). Run: python -m llm_trader run")
        return
    print(f"Dashboard data refreshed at {state['meta']['generated_at']}.")


def cmd_run(args, paths: Paths) -> int:
    state = pipeline.run("demo" if args.demo else args.data, args.llm, paths)
    print(summary_text(state))
    return 0


def cmd_demo(args, paths: Paths) -> int:
    from llm_trader.snapshot import write_snapshot

    state = pipeline.run("demo", args.llm, paths)
    target = write_snapshot(paths, state=state)
    print(summary_text(state))
    print(f"Open {paths.rel(target)} in any browser (nothing to install).")
    return 0


def cmd_serve(args, paths: Paths) -> int:
    import uvicorn

    from llm_trader.server import create_app

    cfg = section(load_settings(paths), "server")
    host, port = args.host or cfg.host, args.port or cfg.port
    if host not in LOOPBACK:
        print("Warning: the dashboard has no login. Never expose it to the internet; keep it on 127.0.0.1.", file=sys.stderr)
    print(f"Dashboard: http://{'127.0.0.1' if host in LOOPBACK else host}:{port}  (press Ctrl+C to stop)")
    uvicorn.run(create_app(paths, extra_hosts=[host]), host=host, port=port, log_level="warning")
    return 0


def cmd_snapshot(args, paths: Paths) -> int:
    from llm_trader.snapshot import write_snapshot

    target = write_snapshot(paths, args.out)
    print(f"Wrote {paths.rel(target)}. Open it in any browser; actions are turned off in a snapshot.")
    return 0


def cmd_lock(args, paths: Paths) -> int:
    if bool(args.rule) == bool(args.all):
        print("Name one rule (for example: lock sweep_fade --yes) or use --all.", file=sys.stderr)
        return 2
    if not args.yes:
        print("Locking a test plan changes what the gate tests. Add --yes to confirm it is your decision.", file=sys.stderr)
        return 1
    settings = load_settings(paths)
    approvals = Approvals(paths)
    if approvals.settings_pending():
        print("Settings have a change waiting for your YES. Approve or reject it first, then lock.", file=sys.stderr)
        return 1
    try:
        rules = all_rules() if args.all else [get_rule(args.rule)]
    except KeyError as exc:
        print(f"{exc.args[0]}. Known rules: {', '.join(r.rule_id for r in all_rules())}.", file=sys.stderr)
        return 2
    for rule in rules:
        plan = lock_plan(make_plan(rule, settings))
        save_plan(paths.plans_dir, plan)
        approvals.record_lock(rule.rule_id, plan)
        print(f"Locked {rule.rule_id}: {plan['sha256'][:12]} at {plan['locked_at']}")
    _refresh(paths)
    return 0


def cmd_killswitch(args, paths: Paths) -> int:
    switch = KillSwitch(paths.killswitch_file)
    if args.state == "on":
        switch.turn_on(args.reason or "Turned on from the command line.")
        mode = "demo" if pipeline.last_run(paths).get("data") in (None, "demo") else "mt5"
        bridge.clear(paths.bridge_file, iso(datetime.now(timezone.utc)), mode, bridge.KILL_NOTE)
        print("Kill switch is ON. The bridge file now holds no signals.")
    else:
        if not args.yes:
            print("Turning the kill switch off needs your confirmation: add --yes.", file=sys.stderr)
            return 1
        switch.turn_off(CONFIRM_WORD)
        print("Kill switch is off.")
    _refresh(paths)
    return 0


def cmd_approve(args, paths: Paths) -> int:
    if not args.yes:
        print("Approving a change needs your confirmation: add --yes.", file=sys.stderr)
        return 1
    entry = Approvals(paths).approve(args.id, CONFIRM_WORD)
    print(f"Approved {entry['id']}: {entry['summary']}")
    _refresh(paths)
    return 0


def cmd_reject(args, paths: Paths) -> int:
    entry = Approvals(paths).reject(args.id)
    print(f"Rejected {entry['id']}: {entry['summary']}")
    _refresh(paths)
    return 0


COMMANDS = {
    "run": cmd_run, "demo": cmd_demo, "serve": cmd_serve, "snapshot": cmd_snapshot, "lock": cmd_lock,
    "killswitch": cmd_killswitch, "approve": cmd_approve, "reject": cmd_reject,
}


def main(argv=None, paths: Paths | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    paths = paths or default_paths()
    load_dotenv(paths.env_file)
    try:
        return COMMANDS[args.command](args, paths)
    except UnknownChange as exc:
        print(f"{exc} Run `python -m llm_trader run` to list pending changes.", file=sys.stderr)
        return 1
    except (ApprovalError, KillSwitchError, SettingsError, MissingCostsError, FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
