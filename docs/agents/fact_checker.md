# FactChecker

**Type:** LlmAgent + MCP  
**Model:** `gemini/gemini-2.5-flash` via LiteLLM  
**MCP tools:** `verify_recording`, `search_wikipedia`, `search_wikidata`

## Role

Verifies the factual claims in a song's blurb and metadata. Two categories of checks:

1. **Structured fields** — `month_year` and `place` (where recorded). These have a
   definitive right answer; the agent corrects them if the researcher was wrong.

2. **Blurb claims** — specific factual assertions in the blurb text (anecdotes, historical
   facts, biographical details, numbers, dates). These are checked for corroboration:
   can a source be found that supports the claim? If not, the claim is flagged for the
   human reviewer. The agent does **not** rewrite the blurb — it flags; the human decides.

Runs concurrently per song alongside SongFetcher.

## Input

```python
class CheckerInput(BaseModel):
    title: str
    artist: str
    month_year: str     # researcher's best-effort
    place: str          # researcher's best-effort
    blurb: str          # full blurb text to check for factual claims
```

## Output schema

```python
class ClaimCheck(BaseModel):
    claim: str              # the specific assertion extracted from the blurb
    corroborated: bool      # True if a source was found supporting it
    confidence: str         # "high" | "medium" | "low" — see confidence rules below
    source_note: str        # what was found, or why it couldn't be verified

class CheckerOutput(BaseModel):
    month_year: str                 # corrected if sourced, else researcher's original
    place: str                      # corrected if sourced, else researcher's original
    metadata_verified: bool         # True if month_year + place both sourced
    metadata_source_note: str       # source used for metadata
    claim_checks: list[ClaimCheck]  # one entry per distinct factual claim in the blurb
    any_unverified_claims: bool     # True if any claim_check has confidence="low"
```

## MCP tools used

| Tool | Source | Purpose |
|------|--------|---------|
| `verify_recording(title, artist)` | MusicBrainz | Recording date, recording location |
| `search_wikipedia(query)` | Wikipedia | Metadata + blurb claim corroboration |
| `search_wikidata(entity)` | Wikidata | Structured property lookup |

MusicBrainz is the primary authority for `place`. Wikipedia/Wikidata handle both
metadata fallback and blurb claim corroboration.

## Confidence levels

| Confidence | Meaning |
|------------|---------|
| `high` | Wikipedia article directly states the claim (Wikipedia is community-edited and peer-reviewed — citations required for factual claims) |
| `medium` | MusicBrainz or Wikidata record matches the claim, but without a prose source; or Wikipedia mentions it in passing without a dedicated citation |
| `low` | No corroborating source found; claim may be true but couldn't be verified online |

A `corroborated=true` claim should have `confidence` of `"high"` or `"medium"`.
A `corroborated=false` claim must have `confidence: "low"`.

## What counts as a claim worth checking

Check anything specific and verifiable: dates, numbers, named people, named places,
historical events, cause-and-effect assertions. Do not check subjective editorial
statements ("the most politically honest thing Motown ever produced") — those are
opinion, not fact.

Examples of claims to check:
- "Robert Johnson died at 27" → verifiable
- "Berry Gordy modelled Motown on the Ford assembly line" → verifiable
- "Run-DMC signed a million-dollar Adidas deal" → verifiable
- "this record crossed the Atlantic within months of its release" → verifiable
- "the blues with no guitar" → editorial opinion, skip

## Field provenance rule

`place` in the final Journey record MUST be sourced from a tool result. If no tool
returns a recording location, `place` stays as the researcher's value and
`metadata_verified = false`. The human reviewer sees this when approving.

## Instruction (system prompt)

```
You are fact-checking a song entry for a music history app. You have two jobs.

JOB 1 — Metadata verification:
Use verify_recording to look up the recording date and location in MusicBrainz.
If MusicBrainz has no entry, try search_wikipedia or search_wikidata.
Correct month_year and place if the sourced value differs from what was provided.
"place" means where the song was physically recorded — not where the artist is from,
not where the lyrics are set.

JOB 2 — Blurb claim corroboration:
Read the blurb and identify every specific, verifiable factual claim.
For each claim, search Wikipedia or Wikidata to find a corroborating source.
Record whether you found corroboration, your confidence level, and what source you used.
Do NOT rewrite the blurb. Flag unverified claims; do not fix them.

Confidence rules:
- "high": Wikipedia article directly states the claim
- "medium": MusicBrainz or Wikidata record matches, or Wikipedia mentions it without
  a dedicated citation
- "low": no corroborating source found

Set corroborated=true for high or medium confidence.
Set corroborated=false and confidence="low" when nothing was found.

A claim that cannot be verified is not necessarily wrong — it may just be
obscure or not well-documented online. The human reviewer will judge whether
to keep it, cut it, or ask for a rewrite.
```

## Trajectory eval

`tests/evals/fact_checker.evalset` asserts:
- Agent calls at least one verification tool
- If MusicBrainz returns a recording location, `place` in output matches it
- `metadata_verified` is `false` when no tool returned location data
- `claim_checks` is non-empty when the blurb contains verifiable claims
- No claim about a named person or specific number appears without a tool call
  attempting to verify it
