from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture()
def sample_transactions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2022-09-01 09:00",
                    "2022-09-01 09:20",
                    "2022-09-01 09:40",
                    "2022-09-01 10:00",
                    "2022-09-01 10:20",
                    "2022-09-01 11:00",
                ]
            ),
            "from_account": ["A", "A", "A", "B", "C", "D"],
            "to_account": ["X", "Y", "Z", "H", "H", "H"],
            "amount_paid": [8_500.0, 9_000.0, 9_500.0, 4_000.0, 4_000.0, 4_000.0],
            "payment_format": ["Wire", "Wire", "Wire", "ACH", "ACH", "ACH"],
            "from_country": ["USA", "USA", "USA", "UK", "UK", "NIGERIA"],
            "to_country": ["USA", "USA", "USA", "UK", "UK", "UK"],
        }
    )
