import click

def get_crossref_referenced_by_count(
    doi: str
):
    import requests
    
    base_url = "https://api.crossref.org/works/"
    key = "is-referenced-by-count"
    full_url = f"{base_url}{doi}"
    response = requests.get(full_url)
    return response.json()["message"][key]


@click.command()
@click.option(
    "--input",
    "input_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="The path to the input file. Must contain a column named 'DOI'.",
    required=True,
)
@click.option(
    "--output",
    "output_file",
    type=click.Path(exists=False, file_okay=True, dir_okay=False),
    help="The path to the output file.",
    required=True,
)
def get_citations(
    input_file: str,
    output_file: str,
):
    import pandas as pd
    import tqdm

    df = pd.read_csv(input_file)
    dois = df["DOI"].tolist()
    counts = []
    for doi in tqdm.tqdm(dois):
        count = get_crossref_referenced_by_count(doi)
        counts.append(count)
    df["counts"] = counts
    df.to_csv(output_file)
    print(f"Saved citation counts to {output_file}")

    total = df.counts.sum()
    print(f"Total citations: {total}")


if __name__ == "__main__":
    get_citations()