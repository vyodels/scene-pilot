# Task: Candidate Discovery

Discover candidate leads that fit the current recruiting goal and return a structured discovery result.

- Do not depend on pre-labeled page entities. Infer candidate lists, profile panels, and resume clues from the raw browser snapshot, visible page text, and any DOM or page state you can inspect with the provided tools.
- Start with `browser_snapshot` to understand the active scene. Use `browser_execute_script` when snapshot text is insufficient and you need more precise page structure or candidate field extraction.
- Prefer extraction over action. Do not send messages, do not request a resume, and do not mutate the recruiting site unless the goal explicitly requires a browser-side operation and that operation stays within the approved tool boundary.
- If you cannot isolate a credible candidate record from the current scene, return a structured failure or replan request instead of guessing.
- When you succeed, include structured candidate facts, source evidence, and any visible resume or attachment signals you can verify from the current scene.
