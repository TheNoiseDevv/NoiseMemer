#!/usr/bin/env python3
"""
Meme Bot (classic-meme style)
-----------------------------
Makes ONE meme in the classic format: a photo-style image with big white
Impact-style text across the top and bottom, then posts it to X.
"""

import os
import re
import sys
import json
import base64
import random
import logging
import textwrap

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("meme")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
TEXT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
COIN_NAME = os.environ.get("COIN_NAME", "The Loudest Coin")
DRY_RUN = os.environ.get("MEME_DRY_RUN", "1") == "1"

X_API_KEY = os.environ.get("X_API_KEY", "")
X_API_SECRET = os.environ.get("X_API_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET", "")

FONT_PATH = os.environ.get("MEME_FONT", "Anton-Regular.ttf")
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
OUT_PATH = os.environ.get("MEME_OUT", "meme.png")

MEME_SITUATIONS = [
    "a very relaxed cat wearing tiny sunglasses, calm and unbothered",
    "an excited golden retriever that looks like it just heard great news",
    "a grumpy-looking pug that refuses to be impressed",
    "a dramatic squirrel frozen mid-action like it got caught",
    "a tiny hamster standing proudly like it owns the place",
    "a chaotic parrot mid-squawk looking absolutely feral",
    "a wise old tortoise looking unimpressed by everything",
    "a golden retriever puppy with pure unfiltered joy",
    "a cat knocking something off a table with zero remorse",
    "a raccoon that clearly has a plan and it's a bad one",
    "a duck marching with total confidence and no destination",
    "a sleepy corgi refusing to get out of bed",
]

BANNED = re.compile(
    r"\b(buy now|sell|ape in|aping|moon(shot)?|100x|1000x|to the moon|"
    r"get rich|guaranteed|financial advice|pump|don'?t miss|last chance|"
    r"you'?ll regret|dump|invest)\b",
    re.IGNORECASE,
)

CONCEPT_SYSTEM = f"""You write classic top/bottom-text memes for {COIN_NAME}, a
community crypto project with a loud/megaphone/high-energy vibe. You are an
openly-disclosed automated project account.

Return ONLY JSON: {{"image_prompt": "...", "top_text": "...", "bottom_text": "..."}}

Rules you never break:
- The joke is about the community's mood/energy/vibe. Wholesome, silly, relatable.
- NEVER mention price, gains, buying, selling, investing, "moon", "100x", getting
  rich, guarantees, or fear-of-missing-out. No financial advice at all.
- Never mock or shame anyone.
- top_text and bottom_text are SHORT (ideally under ~30 characters each), punchy,
  and read as one joke together. They will be shown in ALL CAPS.
- image_prompt: a realistic PHOTO-style image of ONE funny/expressive animal or
  scene (like the situation given). No text in the image, no real named people,
  no logos, no copyrighted characters.
"""


def ensure_font():
    if os.path.exists(FONT_PATH):
        return FONT_PATH
    try:
        import requests
        log.info("Font not found locally, downloading Anton...")
        data = requests.get(FONT_URL, timeout=60).content
        with open(FONT_PATH, "wb") as f:
            f.write(data)
        return FONT_PATH
    except Exception as e:
        log.warning("Could not fetch Anton (%s); using a default bold font.", e)
        return ""


def generate_concept():
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    situation = random.choice(MEME_SITUATIONS)
    log.info("Situation: %s", situation)
    for _ in range(3):
        resp = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": CONCEPT_SYSTEM},
                {"role": "user", "content": f"Make today's meme. Situation: {situation}."},
            ],
            temperature=0.95,
            max_tokens=250,
        )
        raw = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        top = data.get("top_text", "").strip()
        bottom = data.get("bottom_text", "").strip()
        prompt = data.get("image_prompt", "").strip()
        if not prompt or not (top or bottom):
            continue
        if BANNED.search(top) or BANNED.search(bottom):
            log.warning("Caption tripped the no-hype filter, retrying...")
            continue
        return {"image_prompt": prompt, "top_text": top, "bottom_text": bottom}
    raise RuntimeError("Could not produce a clean meme concept after 3 tries.")


def generate_image(image_prompt):
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    full = (image_prompt +
            " Realistic photograph, sharp focus, good lighting, centered subject, "
            "plain uncluttered background. No text, no watermarks, no logos.")
    result = client.images.generate(model=IMAGE_MODEL, prompt=full, size="1024x1024", n=1)
    item = result.data[0]
    b64 = getattr(item, "b64_json", None)
    if b64:
        return base64.b64decode(b64)
    import requests
    return requests.get(item.url, timeout=60).content


def _fit_font(draw, text, max_width, start_size, font_path):
    from PIL import ImageFont
    size = start_size
    while size > 14:
        font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
        wrapped = None
        for chars in range(40, 6, -1):
            lines = textwrap.wrap(text, width=chars) or [text]
            widest = max(draw.textlength(ln, font=font) for ln in lines)
            if widest <= max_width:
                wrapped = lines
                break
        if wrapped and len(wrapped) <= 3:
            return wrapped, font
        size -= 6
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
    return (textwrap.wrap(text, width=18) or [text]), font


def _draw_block(draw, lines, font, img_w, y, line_h, align_top=True):
    stroke = max(2, font.size // 12)
    if not align_top:
        y = y - line_h * len(lines)
    for ln in lines:
        w = draw.textlength(ln, font=font)
        x = (img_w - w) / 2
        draw.text((x, y), ln, font=font, fill="white", stroke_width=stroke, stroke_fill="black")
        y += line_h


def render_meme(image_bytes, top_text, bottom_text, out_path):
    from PIL import Image, ImageDraw
    import io
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    W, H = img.size
    draw = ImageDraw.Draw(img)
    margin = int(W * 0.05)
    start_size = int(W / 9)
    if top_text:
        lines, font = _fit_font(draw, top_text.upper(), W - 2 * margin, start_size, FONT_PATH)
        line_h = int(font.size * 1.05)
        _draw_block(draw, lines, font, W, margin, line_h, align_top=True)
    if bottom_text:
        lines, font = _fit_font(draw, bottom_text.upper(), W - 2 * margin, start_size, FONT_PATH)
        line_h = int(font.size * 1.05)
        _draw_block(draw, lines, font, W, H - margin, line_h, align_top=False)
    img.save(out_path, "PNG")
    log.info("Rendered meme -> %s", out_path)
    return out_path


def post_to_x(image_path):
    import tweepy
    auth = tweepy.OAuth1UserHandler(X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET)
    api_v1 = tweepy.API(auth)
    media = api_v1.media_upload(filename=image_path)
    client_v2 = tweepy.Client(
        consumer_key=X_API_KEY, consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN, access_token_secret=X_ACCESS_SECRET,
    )
    resp = client_v2.create_tweet(text="", media_ids=[media.media_id_string])
    log.info("Posted tweet id=%s", resp.data.get("id"))


def main():
    if not OPENAI_API_KEY:
        log.error("OPENAI_API_KEY is not set.")
        return 1
    ensure_font()
    concept = generate_concept()
    log.info("TOP: %s  |  BOTTOM: %s", concept["top_text"], concept["bottom_text"])
    image_bytes = generate_image(concept["image_prompt"])
    render_meme(image_bytes, concept["top_text"], concept["bottom_text"], OUT_PATH)
    if DRY_RUN:
        log.info("MEME_DRY_RUN=1 -> not posting. Set it to 0 to go live.")
        return 0
    missing = [n for n, v in {
        "X_API_KEY": X_API_KEY, "X_API_SECRET": X_API_SECRET,
        "X_ACCESS_TOKEN": X_ACCESS_TOKEN, "X_ACCESS_SECRET": X_ACCESS_SECRET,
    }.items() if not v]
    if missing:
        log.error("Missing X credentials: %s", ", ".join(missing))
        return 1
    post_to_x(OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
