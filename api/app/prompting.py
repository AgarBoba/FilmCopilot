def compose_prompt(note_texts: list[str], node_prompt: str) -> str:
    """Upstream note texts (in connection order), then the node's own prompt, blank-line separated."""
    parts = [text.strip() for text in note_texts] + [str(node_prompt or '').strip()]
    return '\n\n'.join(part for part in parts if part)
