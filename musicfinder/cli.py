"""Command-line interface: ``musicfinder serve`` starts the web app; the other commands work in the terminal."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from musicfinder import __version__


def _progress():
    last = {"t": 0.0, "step": ""}

    def report(step: str, done: int, total: int) -> None:
        now = time.time()
        if step != last["step"] or now - last["t"] > 0.25 or done == total:
            if step != last["step"] and last["step"]:
                sys.stderr.write("\n")
            sys.stderr.write(f"\r  {step}: {done}/{total}   ")
            sys.stderr.flush()
            last.update(t=now, step=step)

    return report


def _app(args):
    from musicfinder.app import MusicFinder
    from musicfinder.store import Store

    if args.demo:
        print("Demo mode: a simulated listener and catalogue (no Spotify data or network needed).", file=sys.stderr)
        return MusicFinder.demo_instance()
    if args.home:
        os.environ["MUSICFINDER_HOME"] = str(Path(args.home).expanduser())
    return MusicFinder(Store())


def _ensure_graph(app) -> None:
    if not app.graph_ready():
        print("Building your music map (the first run looks up similar artists online; "
              "later runs are cached)…", file=sys.stderr)
        app.build_graph(_progress())
        print(file=sys.stderr)


def cmd_import(args) -> int:
    app = _app(args)
    summary = app.import_paths(args.paths)
    print(json.dumps(summary, indent=2))
    if not summary["plays"] and not summary["library"]:
        print("No music preferences or Spotify listening data found in those files.", file=sys.stderr)
        return 1
    return 0


def cmd_pick(args) -> int:
    app = _app(args)
    verdict = "dislike" if args.dislike else "remove" if args.remove else "love"
    for name in args.artists:
        if verdict != "remove" and not args.exact:
            from musicfinder.app import Unavailable

            try:
                found = app.search_artists(name, 1)["items"]
            except Unavailable:
                found = []
                print(f"Couldn't check {name!r} online; saved as typed.", file=sys.stderr)
            if found and found[0]["name"].casefold() != name.casefold():
                print(f"{name!r} → {found[0]['name']!r} (use --exact to keep your spelling)")
            name = found[0]["name"] if found else name
        picks = app.set_pick(name, verdict)
    print(f"Loved: {', '.join(picks['loved']) or '—'}")
    if picks["disliked"]:
        print(f"Not for you: {', '.join(picks['disliked'])}")
    print("Next: musicfinder recommend (the music map is rebuilt automatically).")
    return 0


def cmd_config(args) -> int:
    app = _app(args)
    print(json.dumps(app.update_settings(
        lastfm_api_key=args.lastfm_key, use_listenbrainz=None if args.listenbrainz is None else args.listenbrainz,
    ), indent=2))
    return 0


def cmd_profile(args) -> int:
    app = _app(args)
    p = app.profile_summary()
    print(f"{p['plays']:,} plays · {p['hours']:,} hours · {p['artists_heard']:,} artists "
          f"({p['effective_artists']} 'effective') · skip rate {p['skip_rate']:.0%} · {p['first']} → {p['last']}")
    if not p["has_skip_data"]:
        print("Note: no skip data (Account-data export). The Extended Streaming History export is more accurate.")
    print("\nTop artists by modelled affinity:")
    for i, a in enumerate(p["top_artists"][:25], 1):
        print(f"{i:3}. {a['name']:<32} {a['streams']:>5} streams  skip {a['skip_rate']:>4.0%}  {a['trend'] or ''}")
    return 0


def cmd_recommend(args) -> int:
    app = _app(args)
    _ensure_graph(app)
    for i, r in enumerate(app.recommendations(args.n, args.explore), 1):
        why = ", ".join(r["because"][:2])
        tags = ", ".join(r["tags"][:3])
        print(f"{i:3}. {r['name']:<32} match {r['match']:5.1f}  [{tags}]  ← {why}")
    return 0


def cmd_songs(args) -> int:
    app = _app(args)
    _ensure_graph(app)
    out = app.songs(args.explore)
    titles = {"new_artist": "Songs from new artists", "similar_song": "Songs like your favourites",
              "deep_cut": "Unheard songs by artists you love"}
    for kind, items in out.items():
        print(f"\n{titles[kind]}:")
        for r in items[: args.n]:
            print(f"  • {r['artist']} — {r['title']}   ({r['because']})")
    return 0


def cmd_explore(args) -> int:
    app = _app(args)
    _ensure_graph(app)
    if args.tag:
        res = app.explore_tag(args.tag)
        print(f"Best ways into “{res['tag']}” for you:")
        for r in res["gateways"]:
            print(f"  • {r['name']:<32} match {r['match']:5.1f}  ← {', '.join(r['because'][:2])}")
        if res["you_already_know"]:
            print("You already know: " + ", ".join(res["you_already_know"]))
        return 0
    res = app.explore()
    print("Your genres: " + ", ".join(f"{g['tag']} {g['share']:.0%}" for g in res["your_genres"][:8]))
    for t in res["territories"]:
        print(f"\n{t['tag']}  (predicted like-rate {t['predicted_like_rate']:.0%}, "
              f"next to {', '.join(t['related_genres_you_know']) or 'your taste'})")
        for g in t["gateways"]:
            print(f"  • {g['name']}  ← {', '.join(g['because'][:2])}")
    if res.get("far_genres"):
        print("\nFurther afield (try `musicfinder explore --tag <genre>`): " + ", ".join(res["far_genres"]))
    return 0


def cmd_evaluate(args) -> int:
    app = _app(args)
    print("Backtesting on your own history (this crawls two past versions of your taste)…", file=sys.stderr)
    rep = app.evaluate(_progress())
    print(file=sys.stderr)
    if not rep.get("ok"):
        print(rep.get("reason"))
        return 1
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
        return 0
    print("\n".join(rep["summary"]))
    m, b = rep["model"], rep["baselines"]
    print("\n                         recall@10  recall@50  recall@100  pref-AUC  pct-rank")
    rows = [("musicfinder", m), ("default weights", rep["default_model"]),
            ("popularity", b["popularity"]), ("similar-artists only", b["similar_artists_only"]), ("random", b["random"])]
    for name, r in rows:
        auc = r.get("auc")
        pr = r.get("mean_percentile_rank")
        print(f"  {name:<22} {r.get('recall@10', 0):9.0%} {r.get('recall@50', 0):10.0%} {r.get('recall@100', 0):11.0%}"
              f"  {('%.2f' % auc) if auc is not None else '  n/a':>8} {('%.0f%%' % pr) if pr is not None else 'n/a':>9}")
    print("\nSettings chosen on the validation window: " + json.dumps(rep["chosen"]))
    return 0


def cmd_serve(args) -> int:
    from musicfinder.server import serve

    app = _app(args)
    host = "0.0.0.0" if args.phone and args.host == "127.0.0.1" else args.host
    serve(app, host, args.port, open_browser=not args.no_browser)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sideband", description="Find the music you'll love: from a few artists you name, and from your Spotify history.")
    parser.add_argument("--version", action="version", version=f"Sideband {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", help="data directory (default: ~/.musicfinder or $MUSICFINDER_HOME)")
    common.add_argument("--demo", action="store_true", help="use a simulated listener instead of your data")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("serve", parents=[common], help="start the web app (default)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--phone", action="store_true",
                   help="also allow phones/tablets on your Wi-Fi (prints a private link to open)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("import", parents=[common], help="import music preferences (CSV/TSV/TXT) or Spotify history (ZIP/JSON)")
    p.add_argument("paths", nargs="+")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("pick", parents=[common], help="name artists you love (no Spotify export needed)")
    p.add_argument("artists", nargs="+")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--dislike", action="store_true", help="artists you don't want anything like")
    group.add_argument("--remove", action="store_true", help="forget these picks")
    p.add_argument("--exact", action="store_true", help="don't look the names up (works offline)")
    p.set_defaults(fn=cmd_pick)

    p = sub.add_parser("config", parents=[common],
                       help="optional: use a Last.fm API key (or set LASTFM_API_KEY) / toggle sources")
    p.add_argument("--lastfm-key")
    p.add_argument("--listenbrainz", dest="listenbrainz", action="store_true", default=None)
    p.add_argument("--no-listenbrainz", dest="listenbrainz", action="store_false")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("profile", parents=[common], help="show your taste profile")
    p.set_defaults(fn=cmd_profile)

    for name, fn, help_ in (("recommend", cmd_recommend, "recommend new artists"),
                            ("songs", cmd_songs, "recommend songs")):
        p = sub.add_parser(name, parents=[common], help=help_)
        p.add_argument("-n", type=int, default=30)
        p.add_argument("--explore", type=float, default=0.0, help="0 = safest bets … 1 = most adventurous")
        p.set_defaults(fn=fn)

    p = sub.add_parser("explore", parents=[common], help="discover genres outside your comfort zone")
    p.add_argument("--tag", help="find your best way into a specific genre")
    p.set_defaults(fn=cmd_explore)

    p = sub.add_parser("evaluate", parents=[common], help="measure accuracy on your own history (backtest)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_evaluate)

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv = ["serve", *argv]  # `musicfinder` alone (or with only options) starts the web app
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except Exception as e:
        from musicfinder.app import NotReady

        from musicfinder.app import Unavailable

        if isinstance(e, (NotReady, Unavailable, FileNotFoundError)):
            print(str(e), file=sys.stderr)
            return 1
        raise
