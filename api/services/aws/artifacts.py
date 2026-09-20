"""Persist existing report formats without modifying their generators."""
import hashlib
from uuid import uuid4

from api.services.aws.s3_service import S3Service


def archive_export(content, filename, media_type, key=None):
    """Also retain user-requested CSV/XLSX/JSON/Markdown/text evidence exports."""
    return S3Service().put_bytes(content, key or f"reports/exports/{uuid4().hex}/{filename}", media_type)


def store_reports(response):
    from tools.exporter import export_investigation_pdf, export_sar_pdf

    s3 = S3Service()
    key = f"reports/{response.investigation_id}/investigation.pdf"
    s3.put_bytes(export_investigation_pdf(response), key, "application/pdf")
    for entity in response.top_entities:
        if entity.sar_draft:
            account_key = hashlib.sha256(entity.entity_id.encode()).hexdigest()[:20]
            s3.put_bytes(export_sar_pdf(entity),
                         f"sar-drafts/{response.investigation_id}/{account_key}/sar-draft.pdf",
                         "application/pdf")
    return key
