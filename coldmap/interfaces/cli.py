"""coldmap command line. Every command works with whatever plugins are installed."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pandas as pd

from .. import DETECTORS, ENRICHERS, FIXES, PRESETS, SOURCES, Query, findings_frame, load
from ..ensemble import DEFAULT_DETECTORS, Ensemble
from .params import parse_overrides

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
NOTICE = "A finding is a pattern worth review, not evidence that cases are linked. See ETHICS.md."

data_options = [
    click.argument("cases", type=click.Path(exists=True)),
    click.option("--source", default="map-shr", show_default=True, help="Source plugin for the cases file"),
    click.option("--clearance", type=click.Path(exists=True), help="Clearance file (adds coverage)"),
    click.option("--skip-fix", multiple=True, help="Data fix to skip (repeatable)"),
    click.option("--namus-missing", type=click.Path(exists=True), help="NamUs Missing Persons CSV export"),
    click.option("--namus-unidentified", type=click.Path(exists=True), help="NamUs Unidentified Persons CSV export"),
]


def with_data(f):
    for opt in reversed(data_options):
        f = opt(f)
    return f


def _load(cases, source, clearance, skip_fix, namus_missing=None, namus_unidentified=None):
    aux = {k: v for k, v in {"namus-missing": namus_missing, "namus-unidentified": namus_unidentified}.items() if v}
    return load(cases, source=source, clearance_path=clearance, skip_fixes=tuple(skip_fix), aux=aux)


@click.group()
def main():
    """coldmap: a framework for finding clusters of unsolved homicides."""


@main.command("plugins")
@click.option("--json", "as_json", is_flag=True)
def plugins(as_json):
    """List installed sources, fixes, detectors and enrichers, with detector parameters."""
    info = {
        "sources": {n: c.summary for n, c in SOURCES},
        "fixes": {n: f.title + ("" if f.apply else " (caveat)") for n, f in FIXES},
        "detectors": [c.describe() for _, c in DETECTORS],
        "enrichers": {n: c.summary for n, c in ENRICHERS},
        "checks": {n: c.summary for n, c in __import__("coldmap.quality", fromlist=["CHECKS"]).CHECKS},
        "presets": {n: f"{p.summary} [{', '.join(p.detectors)}]" for n, p in PRESETS},
    }
    if as_json:
        click.echo(json.dumps(info, indent=2, default=str))
        return
    for kind in ("presets", "sources", "fixes", "enrichers", "checks"):
        click.echo(f"{kind}:")
        for n, s in info[kind].items():
            click.echo(f"  {n:28} {s}")
    click.echo("detectors:")
    for d in info["detectors"]:
        click.echo(f"  {d['name']:28} [{d['tier']}] {d['summary']}")
        for p in d["params"]:
            click.echo(f"      {d['name']}.{p['name']}={p['default']!r:<22} {p['help']}")


@main.command()
@with_data
@click.option("--state", help="Full state name, e.g. California")
@click.option("--sex", "victim_sex", default="Female", type=click.Choice(["Female", "Male"]))
@click.option("-d", "--detector", "detectors", multiple=True,
              help=f"Detector to run (repeatable). Default: {', '.join(DEFAULT_DETECTORS)}")
@click.option("-p", "--param", "params", multiple=True, help="detector.param=value (repeatable)")
@click.option("--preset", help="strict, balanced, profiles, exploratory (see `coldmap plugins`)")
@click.option("--kind", type=click.Choice(["serial-pattern", "accountability"]))
@click.option("--min-age", default=12, show_default=True)
@click.option("--top", default=25, show_default=True)
@click.option("--explain", "n_explain", default=0, help="Explain the top N findings in plain language")
@click.option("--out", type=click.Path(), help="Write all findings to CSV or JSON")
def scan(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, state, victim_sex, detectors,
         params, preset, kind, min_age, top, n_explain, out):
    """Run one or more detectors as an ensemble."""
    from ..presets import resolve
    data = _load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified)
    dets, prm = resolve(preset, detectors, parse_overrides(params))
    ens = Ensemble.from_names(dets or DEFAULT_DETECTORS, prm)
    findings = ens.run(data, Query(state=state, victim_sex=victim_sex, min_age=min_age), kind=kind)
    if not findings:
        click.echo("No findings at these settings.")
        return
    fr = findings_frame(findings).dropna(axis=1, how="all")
    click.echo(fr.head(top).to_string(index=False))
    click.echo(f"\n{len(fr)} findings from {', '.join(d.name for d in ens.detectors)}. "
               f"Data fixes: {', '.join(data.fixes) or 'none'}.\n{NOTICE}")
    if n_explain:
        from ..explain import explain
        for f in findings[:n_explain]:
            click.echo("\n" + "-" * 70 + "\n" + explain(f, data)["text"])
    if out:
        (fr.to_json(out, orient="records", indent=1) if out.endswith(".json") else fr.to_csv(out, index=False))


@main.command()
@with_data
@click.option("-d", "--detector", "detectors", multiple=True,
              help="Detectors to score (repeatable); 'ensemble' scores the default ensemble")
@click.option("-p", "--param", "params", multiple=True, help="detector.param=value")
@click.option("--preset", help="Score a preset's ensemble as 'ensemble'")
@click.option("--series-file", type=click.Path(exists=True), help="Custom known-series JSON")
@click.option("--backtest", is_flag=True, help="Also compute first year flagged (slower)")
@click.option("--json", "json_out", type=click.Path(), help="Also write results as JSON (for the explorer)")
def benchmark(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, detectors, params, preset,
              series_file, backtest, json_out):
    """Score detectors against known, adjudicated serial cases."""
    from ..benchmarks import backtest_all, evaluate, load_series
    data = _load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified)
    dets = detectors or (*DEFAULT_DETECTORS, "ensemble")
    from ..presets import resolve
    pdets, p = resolve(preset, None, parse_overrides(params))
    p["ensemble"] = {"params": dict(p), **({"detectors": pdets} if pdets else {})}
    series = load_series(series_file)
    from ..benchmarks import evaluate_records
    ev = evaluate(data, dets, p, series)
    click.echo(ev.to_string(index=False))
    bt = None
    if backtest:
        bt = backtest_all(data, dets, p, series)
        click.echo("")
        click.echo(bt.to_string(index=False))
        click.echo("\nLead times are optimistic: any finding overlapping the series' years counts.")
    if json_out:
        out = {"detectors": list(dets), "series": evaluate_records(data, dets, p, series),
               "backtest": json.loads(bt.to_json(orient="records")) if bt is not None else []}
        Path(json_out).write_text(json.dumps(out, indent=1, default=str))


@main.command()
@with_data
@click.option("--state", required=True)
@click.option("--below", default=0.8, show_default=True)
def coverage(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, state, below):
    """Counties where the case file is missing many reported murders (blind spots)."""
    from ..enrichers.builtin import low_coverage_places
    if not clearance:
        raise click.UsageError("--clearance is required")
    t = low_coverage_places(_load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified), state, below=below)
    click.echo(t.to_string(index=False) if len(t) else "No large gaps.")


@main.command()
@with_data
@click.option("--state", required=True)
@click.option("--sex", "victim_sex", default="Female", type=click.Choice(["Female", "Male"]))
@click.option("-d", "--detector", "detectors", multiple=True, help="Detectors to test (repeatable)")
@click.option("-p", "--param", "params", multiple=True, help="detector.param=value")
@click.option("--runs", default=5, show_default=True, help="Shuffled datasets to run")
@click.option("--all-kinds", is_flag=True, help="Count accountability findings too")
@click.option("--json", "json_out", type=click.Path(), help="Write results as JSON (for the explorer); "
              "runs both victim sexes")
def controls(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, state, victim_sex,
             detectors, params, runs, all_kinds, json_out):
    """Estimate false alarms: run detectors on data with unsolved cases shuffled across places."""
    from ..benchmarks.controls import false_alarms
    data = _load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified)
    p = parse_overrides(params)
    p["ensemble"] = {"params": dict(p)}
    t = false_alarms(data, Query(state=state, victim_sex=victim_sex),
                     detectors or (*DEFAULT_DETECTORS, "ensemble"), p, runs,
                     kind=None if all_kinds else "serial-pattern")
    click.echo(t.to_string(index=False))
    if json_out:
        other = "Male" if victim_sex == "Female" else "Female"
        t2 = false_alarms(data, Query(state=state, victim_sex=other), detectors or (*DEFAULT_DETECTORS, "ensemble"),
                          p, runs, kind=None if all_kinds else "serial-pattern")
        recs = [{**r, "victim_sex": sx} for sx, tt in ((victim_sex, t), (other, t2))
                for r in json.loads(tt.to_json(orient="records"))]
        Path(json_out).write_text(json.dumps({"state": state, "runs": runs, "rows": recs}, indent=1))
    click.echo("\nnull_findings: average findings on shuffled data, where any finding is a false alarm.\n"
               "noise_share: rough share of real findings that would appear by chance.")


@main.command()
@with_data
@click.option("--state", help="Limit to one state")
@click.option("-c", "--check", "checks", multiple=True, help="Checks to run (default: all)")
@click.option("--top", default=10, show_default=True)
def quality(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, state, checks, top):
    """Data-quality report: reporting anomalies, gaps and suspicious years."""
    from ..quality import CHECKS, report
    data = _load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified)
    for name, t in report(data, state, list(checks) or None, top).items():
        click.echo(f"\n== {name}: {CHECKS.get(name).summary}")
        click.echo(t.to_string(index=False) if len(t) else "   nothing found")
    if data.clearance is None:
        click.echo("\n(Pass --clearance to also run coverage and missing-agency-year checks.)")


@main.command()
@with_data
@click.option("--state", required=True)
@click.option("-d", "--detector", "detectors", multiple=True, help="Detectors to include (repeatable)")
@click.option("-p", "--param", "params", multiple=True, help="detector.param=value")
@click.option("--preset", help="Build from a preset")
@click.option("--benchmark-json", type=click.Path(exists=True), help="From `coldmap benchmark --json`")
@click.option("--controls-json", type=click.Path(exists=True), help="From `coldmap controls --json`")
@click.option("--no-profiles", is_flag=True, help="Skip the age-band view (faster build)")
@click.option("--out-dir", default="explorer_site", show_default=True)
def explorer(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, state, detectors, params,
             preset, benchmark_json, controls_json, no_profiles, out_dir):
    """Build the interactive explorer for one state."""
    from ..presets import resolve
    from .explorer.build import build_site
    dets, prm = resolve(preset, detectors, parse_overrides(params))
    path = build_site(_load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified), state,
                      Path(out_dir), dets or DEFAULT_DETECTORS, prm, profiles=not no_profiles,
                      benchmark_file=benchmark_json, controls_file=controls_json)
    click.echo(f"Explorer written to {path}. Serve the folder (python -m http.server) and open index.html,\n"
               f"or use `coldmap open` to build, serve and open it in one step.")


@main.command("open")
@click.argument("state", required=False)
@click.option("--cases", type=click.Path(exists=True, dir_okay=False), help="Use this case file instead of downloading")
@click.option("--clearance", type=click.Path(exists=True, dir_okay=False), help="Use this clearance file")
@click.option("--sample", is_flag=True, help="Open the synthetic sample (fictional 'Samplestate'), no download")
@click.option("--refresh", is_flag=True, help="Download MAP's files again (after MAP publishes an update)")
@click.option("--rebuild", is_flag=True, help="Rebuild the explorer even if a current one exists")
@click.option("--port", default=8765, show_default=True)
@click.option("--no-browser", is_flag=True, help="Don't open a browser window")
def open_cmd(state, cases, clearance, sample, refresh, rebuild, port, no_browser):
    """The easy way in: get the data, build the explorer and open it in your browser.

    Opens STATE first; every other state in the file is a menu choice away in the page.

    
    coldmap open California
    coldmap open --sample
    """
    from . import launch
    click.echo(NOTICE)
    if sample:
        from ..sample import make_sample
        cases, clearance = make_sample(launch.home() / "sample")
        state = "Samplestate"
    elif cases:
        cases, clearance = Path(cases), Path(clearance) if clearance else None
    else:
        cases, clearance = launch.ensure_data(refresh)
    lib = launch.Library(Path(cases), Path(clearance) if clearance else None, rebuild=rebuild or refresh)
    if not state:
        state = click.prompt("Which state first? (switch to any other in the browser)", default="California")
    state = lib.resolve(state.strip())
    lib.build(state)
    launch.serve(lib, state, port, open_browser=not no_browser)


@main.command()
@click.option("--out-dir", default=".", show_default=True)
def sample(out_dir):
    """Write synthetic sample data (a fictional state with a planted series) to try coldmap."""
    from ..sample import make_sample
    cases, clearance = make_sample(out_dir)
    click.echo(f"Wrote {cases} and {clearance} (synthetic: fictional state 'Samplestate').\nTry:\n"
               f"  coldmap scan {cases} --state Samplestate --clearance {clearance} --explain 1\n"
               f"  coldmap quality {cases} --clearance {clearance}")


if __name__ == "__main__":
    main()
