# Runbook template: incident response

Use this as the starting shape for any new incident-response runbook added
to `docs/runbooks/`. Copy it, rename it to describe the specific incident
class, and fill in each section with real, specific detail — a runbook that
just restates the template's headings without concrete steps is not done.

## Symptom

How does someone first notice this incident? Be specific: an alert name, a
dashboard panel, a user report, a failed CI job. Vague symptoms
("something is wrong") make a runbook useless under pressure.

## Impact

- Who is affected (which environments, which teams, which downstream
  consumers)?
- How bad is it (data unavailable vs. data wrong vs. potential compliance
  exposure)?
- Is there a PHI/PII exposure risk? If there is *any* chance real sensitive
  data was involved, this stops being a normal operational incident and
  becomes a security/compliance incident — escalate per `SECURITY.md`
  immediately rather than continuing down this runbook.

## Diagnosis

Concrete steps to confirm the root cause, in order of speed/cheapness (check
the cheap, fast things first). Reference specific log fields, metric names,
or metadata-plane queries once those exist. Every diagnosis step should
have a clear "this confirms X" or "this rules out X" outcome.

## Resolution

Concrete, numbered steps. Prefer the least-destructive fix that resolves
the immediate impact; note explicitly where a step is destructive/
irreversible and requires a second person's confirmation.

## Prevention / follow-up

- What should change (a test, a check, an alert, an architectural fix) so
  this class of incident is less likely or easier to catch next time?
- Where is that follow-up tracked? (Usually a new entry in
  `docs/problems/problems_master.md`, or a new ADR if it changes an architectural
  decision.)
- If this incident revealed a gap in this runbook itself, update the
  runbook in the same change that resolves the incident — a runbook that
  doesn't reflect the last real incident isn't trustworthy for the next
  one.
