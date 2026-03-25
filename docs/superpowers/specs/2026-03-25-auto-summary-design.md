# Auto-Summary After Transcription

## Problem

The CLI auto-generates a meeting summary (Key Points + Action Items) after transcription completes, but the web app and Zoom bot flows do not. Users must manually use the chat interface to request a summary.

## Goal

Automatically generate a meeting summary after transcription completes in the web app and Zoom bot flows, matching the CLI behavior. Display the summary in a dedicated UI section and seed the chat with it for follow-up questions.

## Design

### Backend

After transcription completes (both local recording and Zoom bot), a background async task generates a summary via AWS Bedrock.

**Shared summarization module:**
Extract `summarize_transcript()` from `transcribe_live.py` into a new `bedrock_utils.py` module so both `transcribe_live.py` and `web_app.py` can import it. This avoids duplication and keeps Bedrock logic in one place.

**Async execution:**
`summarize_transcript()` is synchronous (blocking boto3 `invoke_model` call). The summary task is launched via `asyncio.create_task()` from the trigger point (not awaited inline), so the HTTP response or parent task is not delayed. Within the task, the blocking Bedrock call is wrapped in `loop.run_in_executor()` to avoid blocking the FastAPI event loop, consistent with how Whisper transcription is already handled.

**Transcript preprocessing:**
Before passing text to `summarize_transcript()`, timestamps must be stripped using the same logic as the CLI (`transcribe_live.py` lines 461-465): split each line on the first `]`, take the remainder, join with spaces. This applies to both local and Zoom bot paths — both produce `[MM:SS] text` formatted segments.

**Trigger points:**
- End of `stop_transcription()` endpoint handler (local recording flow in `web_app.py`): after transcript file is written, launch summary task via `asyncio.create_task(_generate_summary(transcript_text, transcript_path))`
- End of `_transcribe_zoom_audio()` (Zoom bot flow in `web_app.py`): after transcript file is written, launch summary task via `asyncio.create_task(_generate_summary(transcript_text, transcript_path))`

Both paths pass the transcript text and file path directly to the summary task as parameters. The Zoom bot transcript text is built locally in `_transcribe_zoom_audio()` and is not in `TranscriptionState`, so the function receives it as an argument. For the local recording path, transcript text is read from `state.get_transcript_text()` and also passed directly. Additionally, the Zoom bot path must store the transcript text in state (e.g., `state.summary_transcript_text`) so that `POST /api/summary/generate` can access it for manual re-generation.

**Summary task (`_generate_summary`):**
1. Set `state.summary_status = "generating"` and broadcast `summary_started` over WebSocket
2. Strip timestamps from transcript text
3. Call `summarize_transcript()` via `run_in_executor` (non-streaming)
4. Before storing results, check if the task has been cancelled (i.e., `state.summary_status` has been reset to `"idle"` by `start()`). If so, discard the result and return early. This handles the race condition where a new recording starts while the executor thread is still running — `asyncio.Task.cancel()` cannot interrupt executor threads, so we check state instead.
5. On success:
   a. Store summary in `state.summary_text`
   b. Set `state.summary_status = "complete"`
   c. Append summary to transcript `.txt` file with `## Meeting Summary` header
   d. Seed `state.chat_history` with the summary (see Chat Seeding below)
   e. Broadcast `summary_complete` with full summary text
6. On failure:
   a. Set `state.summary_status = "error"` and `state.summary_error = <message>`
   b. Broadcast `summary_error` with error message

**New state fields on `TranscriptionState`:**
- `summary_text: str | None` — the generated summary, or None
- `summary_status: str` — one of `"idle"`, `"generating"`, `"complete"`, `"error"`
- `summary_error: str | None` — error message if generation failed
- `summary_transcript_text: str | None` — the transcript text used for summary (needed for manual re-generation via Zoom bot path)
- `_summary_task: asyncio.Task | None` — reference to the running summary task (for cancellation)

These fields must be reset in `TranscriptionState.start()` when a new recording begins. If `_summary_task` is not None and not done, it is cancelled via `task.cancel()` and `_summary_task` is set to None. The staleness check in step 4 of the summary task provides a safety net against the executor-thread race condition.

**New endpoints:**

`GET /api/summary` — returns current summary state:
```json
{
  "summary": "..." | null,
  "status": "idle" | "generating" | "complete" | "error",
  "error": "..." | null
}
```

`POST /api/summary/generate` — manually trigger summary generation:
- Returns 409 if summary is already being generated
- Returns 400 if no transcript exists (checks `state.transcript_segments` for local path, `state.summary_transcript_text` for Zoom bot path)
- Works regardless of `AUTO_SUMMARIZE` setting (this is the manual trigger)
- Uses `state.get_transcript_text()` or `state.summary_transcript_text` as the transcript source

**Configuration:**
- `AUTO_SUMMARIZE` env var (default: `true`) — when `false`, no automatic summary is generated after transcription

**Skip conditions (for auto-trigger only):**
- `AUTO_SUMMARIZE=false`
- Transcript duration < 30 seconds
- AWS credentials not configured (log warning, skip silently)

### Frontend

**Summary tab in transcript panel:**
The right-side transcript panel header (currently showing "Transcript") gains two tab buttons: "Transcript" and "Summary". The Transcript tab is selected by default. Clicking a tab shows its content and hides the other. When a `summary_started` or `summary_complete` message arrives, the Summary tab auto-selects to draw attention.

Tab content by summary state:
- **Idle:** "No summary yet" placeholder text
- **Generating:** spinner with "Generating summary..."
- **Complete:** rendered summary text (Key Points + Action Items)
- **Error:** "Summary generation failed" message with a "Retry" button that calls `POST /api/summary/generate`

On page load and WebSocket reconnect: fetches `GET /api/summary` to sync state.

**Chat seeding:**
When the summary is generated, it is inserted into the chat as a two-message exchange:
- A synthetic user message: `"Summarize this meeting"` (role: `user`)
- The summary text (role: `assistant`)

This satisfies the Anthropic API requirement that conversations start with a user message. The backend updates `state.chat_history` with both messages so follow-up questions have full context.

If the user already has chat history when the summary arrives, the summary pair is prepended. Clearing chat via any existing clear mechanism also clears the seeded summary — the summary remains available in the Summary tab regardless.

**WebSocket message types:**

| Type | Payload | Purpose |
|------|---------|---------|
| `summary_started` | `{}` | Frontend shows spinner in Summary tab |
| `summary_complete` | `{ "summary": "..." }` | Frontend renders summary in tab + chat |
| `summary_error` | `{ "error": "..." }` | Frontend shows error + retry button |

### Error Handling

- **Bedrock call fails:** `summary_error` broadcast. Summary tab shows "Summary generation failed" with a "Retry" button that hits `POST /api/summary/generate`.
- **No AWS credentials:** Summary silently skipped. Server-side log warning emitted. `summary_status` remains `"idle"`.
- **Very short transcripts (<30s):** Auto-summary skipped — not enough content.
- **Multiple clients connected:** All receive the same broadcast. Summary is stored in state for consistency.
- **New recording started before summary finishes:** `_summary_task` is cancelled in `TranscriptionState.start()`, all summary fields reset to idle. The summary task checks for staleness before storing results (see step 4 in summary task lifecycle).
- **`POST /api/summary/generate` called during generation:** Returns 409 Conflict.
- **`POST /api/summary/generate` called with no transcript:** Returns 400 Bad Request.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| AUTO_SUMMARIZE | true | Auto-generate summary after transcription (true/false) |

Uses existing `BEDROCK_MODEL_ID` and `AWS_REGION` for the Bedrock call.

### Persistence

Summary is appended to the transcript `.txt` file with a `## Meeting Summary` header, matching existing CLI behavior. No separate summary file.

### Files to Modify

- `bedrock_utils.py` (new) — extract `summarize_transcript()` from `transcribe_live.py`
- `transcribe_live.py` — import `summarize_transcript` from `bedrock_utils` instead of defining inline
- `web_app.py` — add `_generate_summary()` task, new state fields, new endpoints, WebSocket messages
- `static/index.html` — add Summary/Transcript tabs in transcript panel, handle new WebSocket message types, chat seeding
- `.env.example` — add `AUTO_SUMMARIZE=true`
- `CLAUDE.md` — add `AUTO_SUMMARIZE` to configuration table
- `README.md` — add `AUTO_SUMMARIZE` to configuration table
- `tests/` — add tests for new endpoints, summary generation, and WebSocket messages
