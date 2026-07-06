from .agents import make_song_fetcher

# ADK CLI entry point: adk eval / adk web / adk run
root_agent = make_song_fetcher()
