"""Keep POST /ingest usable with a restored workspace or private S3 CSV sources."""
from api.services.aws.logging import event
from api.services.aws.s3_service import S3Service


def ingest_baselines(force=False):
    from tools.data_loader import get_db_connection, _table_exists, ingest_csv, ingest_saml_knowledge
    from tools.ml_engine import clear_model_cache
    from tools.statistical import get_saml_iqr_bounds

    s3 = S3Service()
    db = get_db_connection()
    result = {"status": "ok"}
    sources = (
        ("transactions", "state/bootstrap/transactions.csv", ingest_csv),
        ("saml_knowledge", "state/bootstrap/knowledge.csv", ingest_saml_knowledge),
    )
    try:
        for table, key, ingest in sources:
            if not force and _table_exists(db, table):
                result[table] = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                continue
            if not s3.file_exists(key):
                raise FileNotFoundError(f"Upload {key} to the configured S3 bucket or seed the workspace database")
            event("dataset_ingestion_started", dataset_id=table)
            with s3.temporary_file(key) as path:
                result[table] = ingest(path, force=force, conn=db)
            event("dataset_ingestion_completed", dataset_id=table)
        return result
    finally:
        db.close()
        clear_model_cache()
        get_saml_iqr_bounds.cache_clear()
