"""Shared helpers for the manually curated inputs/ CSVs.

Every ``add-*`` command follows the same recipe: load the curated CSV (or
start an empty one), skip if the row is already present, append the new row,
sort, and save.  These helpers cover the load/append/save boilerplate; each
caller keeps its own duplicate check (the key and its normalisation differ)
and its own sort order.
"""

import pathlib

import pandas as pd


def load(path: str, columns: list[str], **read_kwargs) -> pd.DataFrame:
    """Read *path*, or return an empty frame, guaranteeing *columns* exist."""
    file_path = pathlib.Path(path)
    if file_path.exists():
        df = pd.read_csv(file_path, **read_kwargs)
    else:
        df = pd.DataFrame(columns=columns)
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df


def append_row(df: pd.DataFrame, row: dict) -> pd.DataFrame:
    """Return *df* with *row* appended, blank-filling any columns it omits."""
    filled = {column: "" for column in df.columns}
    filled.update(row)
    return pd.concat([df, pd.DataFrame([filled])], ignore_index=True)


def save(df: pd.DataFrame, path: str) -> None:
    """Write *df* to *path*, creating the parent directory if needed."""
    file_path = pathlib.Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(file_path, index=False)
