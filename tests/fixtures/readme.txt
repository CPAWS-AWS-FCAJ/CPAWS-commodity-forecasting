Test fixtures for the CPAWS project.

accuracy/ contains three synthetic GET /accuracy/{asset} response examples:
- not_ready.json: No completed evaluation run for the current champion.
- collecting.json: Valid observations exist, but fewer than 20 eligible base dates.
- ready.json: At least 20 eligible base dates; summary metrics can be displayed.

Based on Rolling Accuracy RFC #45 v4.5. These are proposed examples for API/Web review, not production data or a finalized API contract.
