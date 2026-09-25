"""PHI/PII discovery & classification.

Scans a source dataset's schema and (synthetic-only) sample data to
produce ColumnClassification records (see
libs/contracts/src/healthcare_tdm_contracts/classification.py) using
rule-based and pattern-based detectors — e.g., column-name heuristics
("mrn", "ssn", "dob"), value-pattern matchers (SSN-shaped strings,
email-shaped strings), and statistical uniqueness checks (a column where
nearly every value is unique is a candidate identifier even without a
name/pattern match).

Phase 0 scope: placeholder module. Implemented in Phase 7. Design intent
recorded here so later phases start from a clear target: detectors must be
independently unit-testable against fixture data, must report a
confidence score (never a bare boolean), and must default to the more
conservative classification tier below a configured confidence threshold
(see DATA_GOVERNANCE.md section B.1).
"""
