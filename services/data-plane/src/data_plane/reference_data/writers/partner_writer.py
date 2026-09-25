"""External partner files/API writer: the supplemental reference-lab feed.

The messiest of the five simulated source systems on purpose: an
external reference-lab partner that supplements the primary EHR lab
feed (``s3_writer.py``) with its own results, delivered two different
ways depending on when the partner's own systems were last upgraded:

- **v1 (legacy)** — a pipe-delimited flat file with old, abbreviated
  field names (``pat_id``, ``test_cd``, ...), the kind of format a
  partner integration built a decade ago still uses.
- **v2 (current)** — a JSON payload shaped like what the partner's
  modern API returns today, with renamed/expanded fields.

Both are written from the same underlying ``LabResult`` records
(``source == "partner_reference_lab"``), split by
``LabResult.schema_version``, so consumers must handle both shapes to
read "the partner lab feed" completely — this is the schema-drift edge
case made concrete, alongside the late-arriving-data edge case: every
record's ``delivered_at`` is the batch's fixed load date, so any record
whose ``collected_date`` is far earlier than ``delivered_at`` is
identifiably late-arriving data (flagged via ``late_arrival``).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from data_plane.reference_data.domain import LabResult

LATE_ARRIVAL_THRESHOLD_DAYS = 90


def _is_late(lab: LabResult, delivered_at: date) -> bool:
    try:
        collected = date.fromisoformat(lab.collected_date)
    except ValueError:
        return False
    return (delivered_at - collected) > timedelta(days=LATE_ARRIVAL_THRESHOLD_DAYS)


def write_partner_lab_feed(output_root: Path, lab_results: list[LabResult]) -> list[Path]:
    """Write the partner reference-lab feed as v1 flat file + v2 JSON payloads."""

    partner_dir = output_root / "partner_lab_feed"
    written: list[Path] = []
    delivered_at = date.today()

    partner_labs = [lr for lr in lab_results if lr.source == "partner_reference_lab"]
    v1_labs = [lr for lr in partner_labs if lr.schema_version == "v1"]
    v2_labs = [lr for lr in partner_labs if lr.schema_version == "v2"]

    v1_dir = partner_dir / "inbound" / "v1_legacy_flat_file"
    v1_dir.mkdir(parents=True, exist_ok=True)
    v1_path = v1_dir / f"labs_{delivered_at.isoformat()}.txt"
    with v1_path.open("w", encoding="utf-8") as f:
        f.write("pat_id|test_cd|test_nm|result|collected_dt|delivered_dt|late_arrival\n")
        for lab in v1_labs:
            f.write(
                "|".join(
                    [
                        lab.member_id,
                        lab.test_code,
                        lab.test_name,
                        lab.result_value or "",
                        lab.collected_date,
                        delivered_at.isoformat(),
                        "Y" if _is_late(lab, delivered_at) else "N",
                    ]
                )
                + "\n"
            )
    written.append(v1_path)

    v2_dir = partner_dir / "inbound" / "v2_api_json"
    v2_dir.mkdir(parents=True, exist_ok=True)
    v2_path = v2_dir / f"labs_{delivered_at.isoformat()}.json"
    payload = [
        {
            "member_id": lab.member_id,
            "test_code": lab.test_code,
            "test_name": lab.test_name,
            "result_value": lab.result_value,
            "result_unit": lab.result_unit,
            "reference_range": lab.reference_range,
            "abnormal_flag": lab.abnormal_flag,
            "collected_date": lab.collected_date,
            "resulted_date": lab.resulted_date,
            "delivered_at": delivered_at.isoformat(),
            "late_arrival": _is_late(lab, delivered_at),
            "schema_version": "v2",
        }
        for lab in v2_labs
    ]
    v2_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    written.append(v2_path)

    return written


__all__ = ["LATE_ARRIVAL_THRESHOLD_DAYS", "write_partner_lab_feed"]
