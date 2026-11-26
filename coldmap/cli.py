"""Command line: coldmap scan | validate | issues | explorer."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pandas as pd

from .detect import flags_to_frame, map_algorithm, sliding_window
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
@click.option("--method", default="window", type=click.Choice(["window", "map"]))
@click.option("--window", default=4, show_default=True)
@click.option("--threshold", default=0.40, show_default=True, help="Flag at or below this solve rate")
@click.option("--min-cases", default=8, show_default=True)
@click.option("--max-p", type=float, default=None, help="Keep flags with binomial p at or below this")
@click.option("--no-fixes", is_flag=True, help="Use raw data without known-issue fixes")
@click.option("--top", default=25, show_default=True)
@click.option("--out", type=click.Path(), help="Write all flags to CSV")
def scan(shr_file, state, victim_sex, method, window, threshold, min_cases, max_p, no_fixes, top, out):
    """Scan for clusters."""
    df = load_shr(shr_file)
    if method == "map":
        flags = map_algorithm(df, victim_sex=victim_sex, state=state, use_fixes=not no_fixes)
    else:
        flags = sliding_window(df, victim_sex=victim_sex, window=window, threshold=threshold,
                               min_cases=min_cases, max_p=max_p, use_fixes=not no_fixes, state=state)
    fr = flags_to_frame(flags)
    if fr.empty:
        click.echo("No flags at these settings.")
        return
    click.echo(fr.drop(columns=["fixes", "method"]).head(top).to_string(index=False))
    click.echo(f"\n{len(fr)} flags. Fixes applied: {', '.join(flags[0].fixes) or 'none'}.")
    click.echo("A flag is a pattern worth review, not evidence of a link. See ETHICS.md.")
    if out:
        fr.to_csv(out, index=False)


@main.command()
@click.argument("shr_file", type=click.Path(exists=True))
def validate(shr_file):
    """Check the detector against known, adjudicated serial cases."""
    from .validate import run_validation
    click.echo(run_validation(load_shr(shr_file)).to_string(index=False))


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
