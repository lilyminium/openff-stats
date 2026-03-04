import typing

import click


def get_anaconda_downloads(package: str) -> int:
    import requests
    
    url = f"https://anaconda.org/conda-forge/{package}"
    content = requests.get(url).content.decode("utf-8")
    n_downloads = content.split("total downloads")[0]
    n_downloads = n_downloads.split("<span>")[-1].split("</span>")[0]
    return int(n_downloads)


@click.command()
@click.option(
    "--package",
    "packages",
    type=str,
    multiple=True,
    help="Packages to download stats for",
    required=True,
)
@click.option(
    "--output",
    "output_file",
    type=click.Path(exists=False, file_okay=True, dir_okay=False),
    help="The path to the output file.",
    required=True,
)
def download_all(
    packages: typing.List[str],
    output_file: str,
):
    import tqdm
    import pandas as pd

    data = {
        "package": [],
        "total_downloads": [],
    }
    for package in tqdm.tqdm(packages):
        n_downloads = get_anaconda_downloads(package)
        data["package"].append(package)
        data["total_downloads"].append(n_downloads)
    
    df = pd.DataFrame(data)
    df.to_csv(output_file)
    print(f"Saved stats to {output_file}")

    total = df.total_downloads.sum()
    print(f"Total downloads: {total}")


if __name__ == "__main__":
    download_all()