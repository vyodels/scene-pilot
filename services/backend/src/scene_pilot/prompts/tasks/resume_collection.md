# Task: Resume Collection

Collect an already-available resume or attachment for the current candidate without asking the candidate for anything new.

- Prefer resume evidence that is already visible in the active browser scene: online resume content, attachment cards, preview affordances, download affordances, or attachment metadata discoverable from the page.
- Do not send messages, do not request a resume, and do not mutate the recruiting site except browser-side preview or download actions that are strictly necessary to capture an already-visible resume artifact.
- Start with scene inspection. Use `browser_snapshot` to understand the visible page first. Use `browser_execute_script` when snapshot text is insufficient and you need to inspect DOM or page state more precisely.
- A visible attachment card, filename, preview link, or download affordance is only an entry point. It is not a completed result by itself.
- If the goal requires a local resume file, continue past scene confirmation and carry the workflow through preview or download until you can verify the local artifact path and file format.
- Do not call `submit_result` or return `completed` immediately after confirming that a candidate or attachment exists. First verify whether the file was actually captured locally; if not, keep executing or return a structured failure/replan request.
- When the goal requires a local file, do not return `completed` unless you can verify a real local artifact path and its format.
- If you can only recover text or page evidence but cannot verify a local file, return a structured failure or replan request that explains the gap clearly.
- When you succeed, submit structured result data that includes candidate facts, resume evidence, local artifact path, and file format when known.
- If the latest conversation clearly shows the candidate has withdrawn or wants a temporary cooldown instead of continuing the process, return a structured `rollback_signal` and stop the resume-collection path.
- Use only explicit candidate intent for rollback. Do not guess.
