from collections import defaultdict
import click

def get_chemrxiv_metrics(
    record_id: str
):
    import requests
    
    url = f"https://chemrxiv.org/engage/chemrxiv/public-api/v1/items/{record_id}"
    response = requests.get(url)
    message = response.json()["metrics"]
    metrics = {}
    for item in message:
        metrics[item["description"]] = item["value"]
    return metrics

@click.command()
@click.option(
    "--input",
    "input_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="The path to the input file. Must contain a column named 'ID'.",
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
    all_metrics = defaultdict(list)
    for record_id in tqdm.tqdm(record_ids):
        metrics = get_chemrxiv_metrics(record_id)
        for k, v in metrics.items():
            all_metrics[k].append(v)

    for k, v in all_metrics.items():
        df[k] = v
    df.to_csv(output_file)
    print(f"Saved citation counts to {output_file}")

    for k, v in all_metrics.items():
        print(f"Total {k}: {sum(v)}")


if __name__ == "__main__":
    get_citations()