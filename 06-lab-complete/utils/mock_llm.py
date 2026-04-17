def ask(question: str) -> str:
    """Simple mock LLM response for local testing."""
    q = (question or "").strip()
    if not q:
        return "Please provide a question."
    return f"Mock answer: {q}"