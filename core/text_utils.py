import re 

def clean_text(text, skip_words: int = 0) -> str:
    text = re.sub(r"https?://\S+|\S+@\S+", " " , str(text))  # remove urls and emails
    text = re.sub(r"[^a-zA-Z0-9+#./]", " ", text).lower()  # keep c++, c#, node.js style tokens
    return " ".join(text.split()[skip_words: ])
