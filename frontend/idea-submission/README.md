# Task 1 — Startup idea submission interface

Responsive, accessible browser form for collecting a startup idea, industry, target customers, and optional supporting details. The form validates required fields and sends JSON to the backend.

## Run the interface

Serve this folder with any static file server and open `index.html` through that server. For example, from this folder run `python -m http.server 5500`, then visit `http://localhost:5500`. The default API endpoint is `/api/ideas` on the same host.

If the backend runs on a different host or port, set `window.IDEA_API_URL` before the form script runs. For example, add `<script>window.IDEA_API_URL = "http://localhost:8000/api/ideas";</script>` in the page `<head>`. The backend must allow the page's origin if the hosts differ (CORS).

## Backend contract

**Request:** `POST /api/ideas`, `Content-Type: application/json`

```json
{
  "description": "A plain-language description of the idea (20–3000 characters)",
  "industry": "Healthcare",
  "target_customers": "Independent clinics",
  "relevant_details": "Optional context or feature ideas"
}
```

The first three fields are required. `relevant_details` may be an empty string. Return a 2xx JSON response, for example `{ "message": "Idea received" }`. For errors, return a non-2xx status with JSON such as `{ "detail": "A useful error message" }`. The form displays success and server/network errors to the user.

## Handoff to the next teammate

Integrate this folder into the team's existing frontend, point `IDEA_API_URL` at the backend route, and verify the request and response against the contract above. The workspace provided for this task did not contain a project checkout or Git remote, so this deliverable is standalone and has not been pushed to the team's repository.
