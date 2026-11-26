# coldmap-streak

An example coldmap plugin. It adds one detector, `streak`, that flags runs of consecutive years in which a place had killings by one method and solved none.

```bash
pip install -e examples/coldmap-streak
coldmap plugins                     # streak now appears
coldmap scan SHR76_25a.csv --state California -d scan -d window -d streak
```

Everything a plugin needs is in two files: the detector class in `coldmap_streak/__init__.py` and one entry point in `pyproject.toml`.
