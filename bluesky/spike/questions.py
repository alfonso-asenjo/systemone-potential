"""Las preguntas de la fase 1. Toxicidad y adultos van como Choice de dos opciones, no como
Noul: la ficha de Laya avisa de que su Noul puede seguir a las etiquetas false/true en vez de
al texto (issue #156) y recomienda justo esto."""
Q = {
    "emotion": {"type": "choice", "instructions": "What emotion does the author of this social media post mostly express?",
                "criteria": {"joy": "happy, excited, grateful, proud", "love": "affection, tenderness, admiration",
                             "sadness": "sad, grief, loneliness, disappointment", "anger": "angry, outraged, frustrated, hostile",
                             "fear": "afraid, anxious, worried", "surprise": "surprised, amazed, shocked",
                             "neutral": "factual, informative, no clear emotion"}},
    "topic": {"type": "choice", "instructions": "What is this social media post mainly about?",
              "criteria": {"politics": "politics, government, elections, activism", "news": "news, world events, disasters",
                           "tech": "technology, science, AI, software", "culture": "art, music, books, films, games",
                           "sports": "sports", "daily_life": "personal life, feelings, family, food, pets",
                           "humor": "jokes, memes, irony", "other": "anything else"}},
    "toxic": {"type": "choice", "instructions": "Is this social media post insulting, hateful or harassing?",
              "criteria": {"ok": "respectful or neutral, no insults", "toxic": "insults, hate or harassment"}},
    "adult": {"type": "choice", "instructions": "Does this social media post contain sexual or adult content?",
              "criteria": {"safe": "no sexual content", "adult": "sexual, explicit or pornographic content"}},
}
