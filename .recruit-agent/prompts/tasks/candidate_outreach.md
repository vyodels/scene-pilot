# Task: Candidate Outreach

Plan or execute a compliant outbound message or follow-up using the approved outreach strategy.

- Use the recent conversation context before you decide to send anything new.
- If the task payload includes `retryContext`, treat this run as a timed follow-up retry for the current waiting status instead of a brand-new first touch.
- If the candidate explicitly signals that they are no longer available, have accepted another offer, or do not want to continue right now, do not keep pushing the normal outreach path.
- In those rollback cases, submit a structured `rollback_signal` object instead of pretending the outreach advanced normally.
- Use only explicit candidate intent. Do not infer rollback from weak or ambiguous wording.
- Preferred rollback payload:

```json
{{
  "status": "completed",
  "summary": "short factual summary",
  "rollback_signal": {{
    "toStatus": "candidate_withdrew",
    "reason": "candidate explicitly accepted another offer",
    "evidenceExcerpt": "short quote or visible evidence",
    "signalKind": "conversation_signal"
  }}
}}
```

- For temporary pause / later follow-up cases, use `toStatus: "cooldown"` instead of `candidate_withdrew`.
- If you really sent an outbound message in this run, make that explicit in the structured result with fields such as `message`, `message_sent`, or an equivalent outbound action marker.
