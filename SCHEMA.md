# TESS Engine - Data Schemas

The system relies on strictly typed data. We use Pydantic models in Python to enforce these structures.

## 1. Panel (JSON payload via WebSocket)

When a background process completes a segment of the solution, it streams to the frontend as a `Panel` object.

```json

{

  "panel_id": "uuid4",

  "folder_path": "Coding/Project_A",

  "status": "processing | review_passed | completed",

  "content_type": "markdown | code | image",

  "content": "The actual payload (e.g., code block or text)",

  "follow_up_options": ["Continue with this", "Change style", "Discard"]

}

