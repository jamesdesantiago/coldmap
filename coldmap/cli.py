"""Command line: coldmap scan | validate | issues | explorer."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pandas as pd

from .detect import flags_to_frame
from .issues import ISSUES
from .load import load_shr

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)


@click.group()
def main():
    """coldmap: find clusters of unsolved homicides. Flags are leads for review, not links."""


@main.command()
@click.argument("shr_file", type=click.Path(exists=True))
@click.option("--state", help="Full state name, e.g. California")
@click.option("--sex", "victim_sex", default="Female", type=click.Choice(["Female", "Male"]))
@click.option("--method", default="both", show_default=True,
              type=click.Choice(["both", "scan", "window", "map"]),
              help="both: strict + sensitive, merged and labeled. scan: strict (false-alarm "
                   "controlled). window: sensitive. map: MAP's original")
@click.option("--level", default="county,agency", show_default=True,
              help="scan levels, comma-separated: county, agency, msa")
@click.option("--kind", type=click.Choice(["serial-pattern", "accountability"]),
              help="Keep only one kind of flag")
@click.option("--max-q", type=float, default=0.10, show_default=True, help="scan: false discovery rate cutoff")
@click.option("--reps", default=999, show_default=True, help="scan: Monte Carlo simulations")
@click.option("--clearance", type=click.Path(exists=True), help="UCR65_25.csv, to add reporting coverage")
@click.option("--window", default=4, show_default=True)
@click.option("--threshold", default=0.40, show_default=True, help="Flag at or below this solve rate")
@click.option("--min-cases", default=8, show_default=True)
@click.option("--max-p", type=float, default=None, help="Keep flags with binomial p at or below this")
@click.option("--no-fixes", is_flag=True, help="Use raw data without known-issue fixes")
@click.option("--top", default=25, show_default=True)
@click.option("--out", type=click.Path(), help="Write all flags to CSV")
def scan(shr_file, state, victim_sex, method, level, kind, max_q, reps, clearance, window, threshold,
         min_cases, max_p, no_fixes, top, out):
    """Scan for clusters. Confidence: high = both detectors agree, strong = strict scan only,
    possible = sensitive window only."""
    from .combined import detect_all
    df = load_shr(shr_file)
    flags = detect_all(
        df, method, state=state, victim_sex=victim_sex, kind=kind,
        levels=tuple(l.strip() for l in level.split(",")),
        scan_kw={"reps": reps, "max_q": max_q, "min_cases": min_cases, "use_fixes": not no_fixes},
        window_kw={"window": window, "threshold": threshold, "min_cases": min_cases,
                   "max_p": max_p, "use_fixes": not no_fixes})
    if clearance and state:
        from .coverage import add_coverage
        from .load import load_clearance
        flags = add_coverage(flags, df, load_clearance(clearance), state)
    fr = flags_to_frame(flags).dropna(axis=1, how="all")
    if fr.empty:
        click.echo("No flags at these settings.")
        return
    click.echo(fr.drop(columns=["fixes", "method"], errors="ignore").head(top).to_string(index=False))
    click.echo(f"\n{len(fr)} flags. Fixes applied: {', '.join(flags[0].fixes) or 'none'}.")
    click.echo("A flag is a pattern worth review, not evidence of a link. See ETHICS.md.")
    if out:
        fr.to_csv(out, index=False)


@main.command()
@click.argument("shr_file", type=click.Path(exists=True))
def validate(shr_file):
    """Check the detector against known, adjudicated serial cases."""
    from .validate import run_validation
    kw = {"max_len": 25}
    click.echo(run_validation(load_shr(shr_file), scan=kw, both=kw).to_string(index=False))


@main.command()
@click.argument("shr_file", type=click.Path(exists=True))
@click.option("--reps", default=999, show_default=True)
def backtest(shr_file, reps):
    """In what year would each detector first have flagged each known series?"""
    from .validate import run_backtests
    kw = {"reps": reps, "max_len": 25}
    click.echo(run_backtests(load_shr(shr_file), scan=kw, both=kw).to_string(index=False))
    click.echo("\nLead times are optimistic: any flag overlapping the series years counts.")


@main.command()
@click.argument("shr_file", type=click.Path(exists=True))
@click.argument("clearance_file", type=click.Path(exists=True))
@click.option("--state", required=True)
@click.option("--below", default=0.8, show_default=True)
def coverage(shr_file, clearance_file, state, below):
    """Counties where the case file is missing many reported murders (blind spots)."""
    from .coverage import low_coverage_places
    from .load import load_clearance
    t = low_coverage_places(load_shr(shr_file), load_clearance(clearance_file), state, below=below)
    click.echo(t.to_string(index=False) if len(t) else "No large gaps.")


@main.command()
def issues():
    """List known data issues and fixes."""
    for i in ISSUES:
        click.echo(f"[{i.id}] {i.title}\n  {i.summary}\n  fix applied: {'yes' if i.fix else 'no (caveat)'}\n")


@main.command()
@click.argument("shr_file", type=click.Path(exists=True))
@click.option("--state", required=True)
@click.option("--out-dir", default="explorer_site", show_default=True)
def explorer(shr_file, state, out_dir):
    """Build the interactive explorer for one state."""
    from .explorer.build import build_site
    path = build_site(load_shr(shr_file), state, Path(out_dir))
    click.echo(f"Explorer written to {path}. Serve the folder (python -m http.server) and open index.html.")


if __name__ == "__main__":
    main()
