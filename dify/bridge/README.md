# Dify Memory Bridge

This service is the only supporting backend for the Dify Chatflow. It exposes small HTTP endpoints while PowerContext owns the persistent story memory.

## Run

```powershell
cd dify/bridge
uv sync --extra dev
uv run dify-memory-bridge
```

The bridge listens on `0.0.0.0:8766`. Data is written to `dify/bridge/.data/` by default.

Check it:

```powershell
Invoke-RestMethod http://127.0.0.1:8766/health
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/recall` | Recall scoped story context for a Dify user |
| `POST` | `/v1/remember` | Save the player move and generated scene |
| `POST` | `/v1/reset` | Start a new chapter while preserving audit history |
| `GET` | `/v1/memories?user_id=...` | Inspect current memory entries and citations |

## Scope isolation

The Dify `sys.user_id` is hashed and used to create a stable PowerContext Scope. Two Dify users therefore cannot recall each other's story.
