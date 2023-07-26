import click

def get_scholar_citations(
    record_id: str
):
    import re
    import requests
    
    url = f"https://scholar.google.com/scholar?cites={record_id}&as_sdt=2005&sciodt=0,5&hl=en"
    response = requests.get(url)
    message = response.text.split("Cited by")[1].strip()
    return int(re.match("\d+", message).group(0))

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
    record_ids = df["ID"].tolist()
    counts = []
    for record_id in tqdm.tqdm(record_ids):
        count = get_scholar_citations(record_id)
        counts.append(count)
    df["counts"] = counts
    df.to_csv(output_file)
    print(f"Saved citation counts to {output_file}")

    total = df.counts.sum()
    print(f"Total citations: {total}")


if __name__ == "__main__":
    get_citations()