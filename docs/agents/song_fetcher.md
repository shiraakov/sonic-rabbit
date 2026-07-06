# SongFetcher

**Type:** LlmAgent + MCP  
**Model:** `gemini/gemini-2.5-flash` via LiteLLM  
**MCP tools:** `search_track`, `get_track_metadata`

## Role

Given a song title and artist from the JourneyResearcher draft, fetch the real
`preview_url`, `image_url`, and `streaming_links` from iTunes/Deezer.
Runs concurrently per song alongside FactChecker.

## Input

```python
class FetcherInput(BaseModel):
    title: str
    artist: str
```

## Output schema

```python
class FetcherOutput(BaseModel):
    preview_url: Optional[str]          # 30s snippet from iTunes/Deezer
    image_url: Optional[str]            # album art URL
    streaming_links: StreamingLinks     # {spotify, apple_music, youtube}
```

All fields nullable. A miss on all three is valid — the song record is still published,
just without playback links.

## MCP tools used

| Tool | Source | Purpose |
|------|--------|---------|
| `search_track(title, artist)` | iTunes Search API | Primary lookup |
| `search_track(title, artist)` | Deezer API | Fallback if iTunes misses |

The agent calls iTunes first. If `preview_url` is null in the result, it tries Deezer.
If both miss, it returns all-null output and logs the miss.

## Field provenance rule (enforced in orchestrator)

`preview_url` MUST come from an MCP tool result. If the LLM output contains a
`preview_url` that was not returned by a tool call in this session, the orchestrator
rejects it and sets `preview_url = null`. This is checked in code — the LLM cannot
hallucinate a working preview URL.

## Instruction (system prompt)

```
You are fetching music metadata for a song. Use the search_track tool to find
the song, then extract preview_url, image_url, and streaming links from the result.

Call iTunes first. If preview_url is missing or null, call Deezer as a fallback.
If both sources return nothing useful, return null for all fields.

Do not invent or guess URLs. Only return URLs that appear in tool results.
```

## Trajectory eval

`tests/evals/song_fetcher.evalset` asserts:
- Agent calls `search_track` at least once
- `preview_url` in output matches a URL returned by the tool (or is null)
- No URLs in output that did not appear in any tool result
