import pathlib
import typing

import click

if typing.TYPE_CHECKING:
    import pandas as pd


def download_stats(package_name: str) -> "pd.DataFrame":
    from condastats.cli import overall
    
    data = overall(package_name, monthly=True)
    df = data.to_frame().reset_index()
    df["year"] = df.time.str.split("-", expand=True)[0]
    return df


@click.command()
@click.option(
    "--output-directory",
    type=click.Path(exists=False, file_okay=False, dir_okay=True),
    default="stats.csv",
    help="The path to save the stats to.",
)
@click.option(
    "--package",
    "packages",
    type=str,
    multiple=True,
    help="Packages to download stats for",
)
def download_all(
    output_directory: str,
    packages: typing.List[str],
):
    import tqdm
    import pandas as pd

    output_directory = pathlib.Path(output_directory)
    output_directory.mkdir(exist_ok=True, parents=True)
    
    all_dfs = []
    for package in tqdm.tqdm(packages):
        stats = download_stats(package)
        all_dfs.append(stats)
    df = pd.concat(all_dfs)

    all_output = output_directory / "monthly_stats_all.csv"
    df.to_csv(all_output)
    print(f"Saved all monthly stats to {all_output}")

    if len(packages) == 1:
        df = df[["time", "counts", "year"]]

    combined = df.groupby("time").sum().reset_index()
    combined = combined[["time", "counts"]]
    combined["cumulative"] = combined.counts.cumsum()
    combined_output = output_directory / "monthly_stats_combined.csv"
    combined.to_csv(combined_output)
    print(f"Saved combined monthly stats to {combined_output}")

    yearly = df.groupby("year").sum().reset_index()
    yearly = yearly[["year", "counts"]]
    yearly_output = output_directory / "yearly_stats.csv"
    yearly.to_csv(yearly_output)
    print(f"Saved yearly stats to {yearly_output}")

    total = df.counts.sum()
    print(f"Total downloads: {total}")


if __name__ == "__main__":
    download_all()