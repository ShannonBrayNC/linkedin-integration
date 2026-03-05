def build_adaptive_card(title: str, body_lines: list[str]) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium"},
            *[{"type": "TextBlock", "text": line, "wrap": True} for line in body_lines]
        ]
    }
