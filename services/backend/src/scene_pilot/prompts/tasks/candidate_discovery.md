# Task: Candidate Discovery

Discover candidate leads that fit the current recruiting goal and return a structured discovery result from the human operator's regular browser, not an AI-mode browser.

- Default recruiting source for this workflow: `zhipin.com`. First inspect the regular browser for already-open reachable `zhipin.com` candidate-search, recommendation, or candidate-detail pages that are usable for candidate discovery. If no suitable `zhipin.com` candidate-discovery page is already open, use the generic browser tools to open `zhipin.com` yourself in that regular browser and navigate to a usable candidate-search, recommendation, or candidate-detail page. Only ask the human for help when login, captcha, permissions, or another true human-only blocker prevents you from proceeding.
- Do not depend on pre-labeled page entities. Infer candidate lists, profile panels, and resume clues from the raw browser snapshot, visible page text, and any DOM or page state you can inspect with the provided tools.
- Read the browser tool descriptions literally. If the available tab-listing tool only covers the current Chrome window, then not seeing a recruiting page there is not proof that no reusable recruiting page exists anywhere else in the regular browser.
- When multiple recruiting tabs are open, inspect `zhipin.com` tabs first and prefer the one with the clearest candidate list, recommendation feed, or profile detail evidence.
- Start with `browser_snapshot` to understand the active scene. Use `browser_execute_script` when snapshot text is insufficient and you need more precise page structure or candidate field extraction.
- Prefer extraction over action. Do not send messages, do not request a resume, and do not mutate the recruiting site unless the goal explicitly requires a browser-side operation and that operation stays within the approved tool boundary.
- If you cannot isolate a credible candidate record from the current scene, keep the candidate-discovery workflow going by checking other reachable recruiting tabs first.
- Only open a fresh `zhipin.com` page yourself when the current browser evidence is broad enough to justify that no reusable recruiting page is already open in the accessible browser scope.
- If the available tab-discovery evidence is only window-scoped and does not reveal a usable recruiting page, do not jump straight to opening a new recruiting tab. Return a structured blocked result that explains the browser-scope limitation instead of bypassing a possibly already-open regular-browser recruiting page.
- When you succeed, include structured candidate facts, source evidence, and any visible resume or attachment signals you can verify from the current scene.
