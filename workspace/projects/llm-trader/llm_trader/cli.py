from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from llm_trader import __version__, bridge, pipeline
from llm_trader.config import CONFIRM_WORD, Paths, SettingsError, default_paths, load_dotenv, load_settings, section
from llm_trader.data.symbols import MissingCostsError
from llm_trader.eval.plans import lock_rule, previous_plan, trial_hash
from llm_trader.models import utc
from llm_trader.llm import llm_wanted
from llm_trader.risk.approvals import ApprovalError, Approvals, UnknownChange
from llm_trader.risk.killswitch import KillSwitch, KillSwitchError
from llm_trader.signals.registry import all_rules, get_rule

LOOPBACK = ("127.0.0.1", "localhost", "::1")
LLM_HELP = "let Claude write the review text: on or off (default off, or LLM_MODE in .env); needs ANTHROPIC_API_KEY"


def _llm_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--llm", nargs="?", const="on", choices=["on", "off"], help=LLM_HELP)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m llm_trader", description=f"Superagentic {__version__}: research and supervision desk. It never places trades.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run every agent once and write out/state.json, out/report.md and the bridge file")
    source = run.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="use the synthetic demo data")
    source.add_argument("--data", metavar="DIR", help="folder with your MT5 export, or 'mt5' for data.mt5_dir in settings")
    _llm_option(run)
    demo = sub.add_parser("demo", help="run on the demo data and write out/state.json and out/dashboard.html (open it in any browser)")
    _llm_option(demo)
    serve = sub.add_parser("serve", help="show the dashboard in your browser (this computer only)")
    serve.add_argument("--host", help="address to listen on (default 127.0.0.1)")
    serve.add_argument("--i-know-there-is-no-login", dest="no_login_ok", action="store_true",
                       help="needed with a --host other than this computer: anyone who can reach it can press the buttons")
    serve.add_argument("--port", type=int, help="port (default 8765)")
    snapshot = sub.add_parser("snapshot", help="write the dashboard as one self-contained HTML file")
    snapshot.add_argument("--out", help="where to write it (default out/dashboard.html)")
    lock = sub.add_parser("lock", help="lock (hash) a rule's test plan; needs --yes")
    lock.add_argument("rule", nargs="?", help="rule id, for example trend_pullback")
    lock.add_argument("--all", action="store_true", help="lock every rule's plan")
    lock.add_argument("--yes", action="store_true", help="confirm this is your decision")
    lock.add_argument("--unstudied-since", metavar="YYYY-MM-DD",
                      help="declare that you have not studied your broker's data from this date on (only if true)")
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


def _self_test_line(state: dict) -> str:
    tests = state["self_tests"]
    failed = [t["name"] for t in tests if t["ok"] is False]
    passed = sum(1 for t in tests if t["ok"])
    return f"Self-tests: {passed} of {len(tests)} OK" + (f" (FAILED: {'; '.join(failed)})" if failed else "")


def summary_text(state: dict) -> str:
    meta, bridge_state = state["meta"], state["bridge"]
    lines = [
        f"Superagentic {meta['version']} | {' | '.join(meta['banners'])}",
        f"kill switch {'ON' if meta['kill_switch']['on'] else 'off'} | safe mode {'ON' if meta['safe_mode']['on'] else 'off'} | "
        f"tries counted on these months: {meta['trial_count']}",
        "",
        f"{'Agent':<30} {'Gate':<13} {'Never-seen wins':<16} {'95% CI':<10} {'Full stop':<10} Stage",
    ]
    for r in state["research"]:
        h = r["windows"]["holdout"]
        lo, hi = h["win_rate_ci"]
        ci = f"{lo:.0%}-{hi:.0%}" if h["trades"] else "-"
        name = (r["name"] + (" *" if r["self_test"] else ""))[:30]
        lines.append(f"{name:<30} {r['gate']['status']:<13} {_pct(h['win_rate']) + ' of ' + str(h['trades']):<16} "
                     f"{ci:<10} {_pct(h['full_stop_rate']):<10} {r['stage']}")
    lines += [
        "* self-test: proves the harness works; never traded.",
        "",
        f"Accuracy bar: {meta['accuracy_bar']:.0%} on never-seen months, after costs, and better than random entries.",
        _self_test_line(state),
        f"Picks today: {len(state['picks_today']['picks'])}. {state['picks_today']['reason']}",
        meta["eligible_note"],
        f"Bridge: {len(bridge_state['advisories'])} advisories, kill.flag {'set' if bridge_state['kill_flag'] else 'not set'}. {bridge_state['note']}",
    ]
    if meta["safe_mode"]["on"]:
        lines.append(f"Safe mode: {meta['safe_mode']['reason']}")
        lines += [f"  {p['id']}: {p['summary']}" for p in state["approvals"]["pending"]]
    lines += ["", "Wrote out/state.json, out/report.md and out/bridge/advisories.json.",
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
    state = pipeline.run("demo" if args.demo else args.data, llm_wanted(args.llm), paths)
    print(summary_text(state))
    return 0


def cmd_demo(args, paths: Paths) -> int:
    from llm_trader.snapshot import balance_warning, write_snapshot

    state = pipeline.run("demo", llm_wanted(args.llm), paths)
    target = write_snapshot(paths, state=state)
    print(summary_text(state))
    print(f"Open {paths.rel(target)} in any browser (nothing to install).")
    if balance_warning(state):
        print(balance_warning(state), file=sys.stderr)
    return 0


def cmd_serve(args, paths: Paths) -> int:
    import uvicorn

    from llm_trader.server import create_app

    cfg = section(load_settings(paths), "server")
    if args.host and args.host not in LOOPBACK and not args.no_login_ok:
        print(f"Refusing to listen on {args.host}: the dashboard has no login, so anyone who can reach it could turn the kill "
              "switch off or approve changes. Keep it on 127.0.0.1, or add --i-know-there-is-no-login.", file=sys.stderr)
        return 2
    if not args.host and cfg.host not in LOOPBACK:
        print(f"Ignoring server.host {cfg.host!r} from settings.json: only --host on the command line can open the dashboard "
              "to other computers.", file=sys.stderr)
    host = args.host or (cfg.host if cfg.host in LOOPBACK else "127.0.0.1")
    port = args.port or cfg.port
    if host not in LOOPBACK:
        print("Warning: the dashboard has no login. Never expose it to the internet.", file=sys.stderr)
    print(f"Dashboard: http://{'127.0.0.1' if host in LOOPBACK else host}:{port}  (keep this window open; Ctrl+C stops it)")
    uvicorn.run(create_app(paths, extra_hosts=[host]), host=host, port=port, log_level="warning")
    return 0


def cmd_snapshot(args, paths: Paths) -> int:
    from llm_trader.snapshot import balance_warning, saved_state, write_snapshot

    state = saved_state(paths)
    target = write_snapshot(paths, args.out, state)
    print(f"Wrote {paths.rel(target)}. Open it in any browser; actions are turned off in a snapshot.")
    if balance_warning(state):
        print(balance_warning(state), file=sys.stderr)
    return 0


def cmd_lock(args, paths: Paths) -> int:
    if bool(args.rule) == bool(args.all):
        print("Name one rule (for example: lock trend_pullback --yes) or use --all.", file=sys.stderr)
        return 2
    if not args.yes:
        print("Locking a test plan changes what the gate tests. Add --yes to confirm it is your decision.", file=sys.stderr)
        return 1
    settings = load_settings(paths)
    approvals = Approvals(paths)
    if approvals.record() is None:
        print("Nothing is approved yet. Approve the starting point first (python -m llm_trader run lists it), then lock.", file=sys.stderr)
        return 1
    if approvals.settings_pending():
        print("Settings have a change waiting for your YES. Approve or reject it first, then lock.", file=sys.stderr)
        return 1
    try:
        rules = all_rules() if args.all else [get_rule(args.rule)]
    except KeyError as exc:
        print(f"{exc.args[0]}. Known rules: {', '.join(r.rule_id for r in all_rules())}.", file=sys.stderr)
        return 2
    try:
        declared = utc(args.unstudied_since) if args.unstudied_since else None
    except ValueError:
        print(f"--unstudied-since needs a date like 2026-01-30, not {args.unstudied_since!r}.", file=sys.stderr)
        return 2
    for rule in rules:
        before = previous_plan(paths.plans_dir, rule.rule_id)
        plan = lock_rule(rule, settings, paths.plans_dir, unstudied_since=declared)
        approvals.record_lock(rule.rule_id, plan)
        kept = before is not None and before.get("locked_at") == plan["locked_at"] and trial_hash(before) == trial_hash(plan)
        note = " (same test as before, so its original lock time is kept)" if kept else ""
        print(f"Locked {rule.rule_id}: {plan['sha256'][:12]} at {plan['locked_at']}{note}")
    _refresh(paths)
    return 0


def stop_bridge(paths: Paths) -> None:
    bridge.write(paths.bridge_dir, bridge.payload(datetime.now(timezone.utc), kill=True))


def cmd_killswitch(args, paths: Paths) -> int:
    switch = KillSwitch.at(paths)
    if args.state == "on":
        switch.turn_on(args.reason or "Turned on from the command line.")
        stop_bridge(paths)
        print("Kill switch is ON. kill.flag is set and the advisories file is empty.")
    else:
        if not args.yes:
            print("Turning the kill switch off needs your confirmation: add --yes.", file=sys.stderr)
            return 1
        switch.turn_off(CONFIRM_WORD)
        print("Kill switch is off. kill.flag removed.")
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
