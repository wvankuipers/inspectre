---
name: inspectre-verify-spa-in-browser
description: Use after any frontend change, before marking a frontend task complete.
---

# Verify the SPA in browser

1. Rebuild and restart the `spa` container:
   ```
   docker compose build spa && docker compose up -d spa
   ```
2. Using the Chrome DevTools MCP, navigate to `http://localhost:4200`.
3. Exercise the golden path for the change (the primary route/component touched) and at
   least one relevant edge case (empty state, error state, or filter/sort interaction as
   applicable).
4. Take a screenshot and check the console for errors (`list_console_messages`).
5. Only report the frontend task complete once the screenshot confirms the UI looks
   correct and the console is free of new errors. Type checking and Vitest verify code
   correctness, not visual/feature correctness — this step is not optional.
