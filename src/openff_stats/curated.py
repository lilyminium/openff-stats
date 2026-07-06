"""Shared helpers for the manually curated inputs/ CSVs.

Every input kind lives in a directory of CSVs where the *filename* is the
group classification: e.g. inputs/publications/force-field.csv holds the
force-field papers, inputs/zenodo/qcsubmit.csv the qcsubmit Zenodo records.
``load_groups`` reads a whole directory and tags rows with their group.

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


def load_groups(directory: str, columns: list[str], **read_kwargs) -> pd.DataFrame:
    """Read every ``*.csv`` in *directory*, tagging rows with ``group``.

    The group is the filename stem (``force-field.csv`` → ``force-field``).
    Accepts a single CSV path too (its stem becomes the group), so ``--input``
    overrides keep working.  Returns an empty frame with *columns* + ``group``
    if nothing is found.
    """
    path = pathlib.Path(directory)
    files = [path] if path.is_file() else sorted(path.glob("*.csv")) if path.is_dir() else []
    frames = []
    for file_path in files:
        df = load(str(file_path), columns, **read_kwargs)
        df["group"] = file_path.stem
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=[*columns, "group"])
    return pd.concat(frames, ignore_index=True)


def group_path(directory: str, group: str) -> str:
    """Return the CSV path for *group* within *directory*."""
    return str(pathlib.Path(directory) / f"{group}.csv")


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
