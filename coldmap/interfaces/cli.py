"""coldmap command line. Every command works with whatever plugins are installed."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pandas as pd

from .. import DETECTORS, ENRICHERS, FIXES, SOURCES, Query, findings_frame, load
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
    }
    if as_json:
        click.echo(json.dumps(info, indent=2, default=str))
        return
    for kind in ("sources", "fixes", "enrichers", "checks"):
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
@click.option("--kind", type=click.Choice(["serial-pattern", "accountability"]))
@click.option("--min-age", default=12, show_default=True)
@click.option("--top", default=25, show_default=True)
@click.option("--out", type=click.Path(), help="Write all findings to CSV or JSON")
def scan(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, state, victim_sex, detectors, params, kind, min_age, top, out):
    """Run one or more detectors as an ensemble."""
    data = _load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified)
    ens = Ensemble.from_names(detectors or DEFAULT_DETECTORS, parse_overrides(params))
    findings = ens.run(data, Query(state=state, victim_sex=victim_sex, min_age=min_age), kind=kind)
    if not findings:
        click.echo("No findings at these settings.")
        return
    fr = findings_frame(findings).dropna(axis=1, how="all")
    click.echo(fr.head(top).to_string(index=False))
    click.echo(f"\n{len(fr)} findings from {', '.join(d.name for d in ens.detectors)}. "
               f"Data fixes: {', '.join(data.fixes) or 'none'}.\n{NOTICE}")
    if out:
        (fr.to_json(out, orient="records", indent=1) if out.endswith(".json") else fr.to_csv(out, index=False))


@main.command()
@with_data
@click.option("-d", "--detector", "detectors", multiple=True,
              help="Detectors to score (repeatable); 'ensemble' scores the default ensemble")
@click.option("-p", "--param", "params", multiple=True, help="detector.param=value")
@click.option("--series-file", type=click.Path(exists=True), help="Custom known-series JSON")
@click.option("--backtest", is_flag=True, help="Also compute first year flagged (slower)")
def benchmark(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, detectors, params, series_file, backtest):
    """Score detectors against known, adjudicated serial cases."""
    from ..benchmarks import backtest_all, evaluate, load_series
    data = _load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified)
    dets = detectors or (*DEFAULT_DETECTORS, "ensemble")
    p = parse_overrides(params)
    p["ensemble"] = {"params": dict(p)}
    series = load_series(series_file)
    click.echo(evaluate(data, dets, p, series).to_string(index=False))
    if backtest:
        click.echo("")
        click.echo(backtest_all(data, dets, p, series).to_string(index=False))
        click.echo("\nLead times are optimistic: any finding overlapping the series' years counts.")


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
def controls(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, state, victim_sex,
             detectors, params, runs, all_kinds):
    """Estimate false alarms: run detectors on data with unsolved cases shuffled across places."""
    from ..benchmarks.controls import false_alarms
    data = _load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified)
    p = parse_overrides(params)
    p["ensemble"] = {"params": dict(p)}
    t = false_alarms(data, Query(state=state, victim_sex=victim_sex),
                     detectors or (*DEFAULT_DETECTORS, "ensemble"), p, runs,
                     kind=None if all_kinds else "serial-pattern")
    click.echo(t.to_string(index=False))
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
@click.option("--out-dir", default="explorer_site", show_default=True)
def explorer(cases, source, clearance, skip_fix, namus_missing, namus_unidentified, state, detectors, params, out_dir):
    """Build the interactive explorer for one state."""
    from .explorer.build import build_site
    path = build_site(_load(cases, source, clearance, skip_fix, namus_missing, namus_unidentified), state, Path(out_dir),
                      detectors or DEFAULT_DETECTORS, parse_overrides(params))
    click.echo(f"Explorer written to {path}. Serve the folder (python -m http.server) and open index.html.")


if __name__ == "__main__":
    main()
