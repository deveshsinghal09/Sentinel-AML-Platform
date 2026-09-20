"""Generate explicitly synthetic AWS demo inputs using the existing importers.

Run from the repository root: python -m scripts.create_aws_demo
Never overwrites an existing database. This is a demo baseline, not a calibrated
production model or a replacement for the project's real SAML-D baseline.
"""
import argparse
from pathlib import Path

import duckdb
import pandas as pd


def create_demo(directory: Path):
    from tools.data_loader import ingest_csv, ingest_saml_knowledge
    from tools.dataset_store import initialize_dataset_registry

    directory.mkdir(parents=True, exist_ok=True)
    database = directory / "seed.duckdb"
    if database.exists():
        raise FileExistsError("Demo database already exists; choose another --output directory")
    times = pd.date_range("2026-01-01", periods=200, freq="h")
    normal = pd.DataFrame({
        "Timestamp": times, "From Bank": "001", "Account": [f"NORMAL-{i % 20}" for i in range(200)],
        "To Bank": "002", "Account.1": [f"RECIPIENT-{i % 13}" for i in range(200)],
        "Amount Received": [50 + i % 100 for i in range(200)], "Receiving Currency": "USD",
        "Amount Paid": [50 + i % 100 for i in range(200)], "Payment Currency": "USD",
        "Payment Format": "ACH", "Is Laundering": 0,
    })
    normal_path = directory / "synthetic-normal.csv"
    normal.to_csv(normal_path, index=False)
    knowledge = pd.DataFrame({
        "Time": times.strftime("%H:%M:%S"), "Date": times.strftime("%Y-%m-%d"),
        "Sender_account": normal["Account"], "Receiver_account": normal["Account.1"],
        "Amount": normal["Amount Paid"], "Payment_currency": "USD", "Received_currency": "USD",
        "Sender_bank_location": "USA", "Receiver_bank_location": "USA", "Payment_type": "ACH",
        "Is_laundering": 0, "Laundering_type": "Normal",
    })
    knowledge_path = directory / "synthetic-knowledge.csv"
    knowledge.to_csv(knowledge_path, index=False)
    db = duckdb.connect(str(database))
    try:
        ingest_csv(normal_path, conn=db)
        ingest_saml_knowledge(knowledge_path, conn=db)
        initialize_dataset_registry(db)
        db.execute("UPDATE dataset_registry SET display_name = 'SYNTHETIC demo baseline', notes = 'Synthetic testing data only'")
    finally:
        db.close()
    suspicious = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-10", periods=120, freq="5min"),
        "sender_id": "SYNTHETIC-HIGH-RISK", "receiver_id": [f"SYNTHETIC-TARGET-{i % 10}" for i in range(120)],
        "amount": [9000 + i % 10 * 90 for i in range(120)], "currency": "USD",
        "payment_type": "ACH", "is_laundering": 0,
    })
    path = directory / "synthetic-transactions.csv"
    suspicious.to_csv(path, index=False)
    return database, path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dataset/aws-demo"))
    args = parser.parse_args()
    database, transactions = create_demo(args.output)
    print(f"Synthetic seed database: {database.resolve()}")
    print(f"Synthetic transaction upload: {transactions.resolve()}")
