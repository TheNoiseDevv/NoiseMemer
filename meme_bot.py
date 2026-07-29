#!/usr/bin/env python3
"""
Meme Bot
--------
Generates ONE original, brand-safe meme (image + short caption) and posts it to X.

Guardrails (enforced in the prompt + a light keyword check):
- Branded community humor only. NO financial advice, price predictions,
  "buy/sell", "ape in", guaranteed gains, or FOMO/"don't miss out".
- No mocking people who didn't buy. SFW. No real people. No copyrighted
  characters or logos -> original mascot/imagery only.

Modes:
- MEME_DRY_RUN=1  -> generate concept + image, save it, DON'T post.
                     (In GitHub Actions the image is uploaded as an artifact
                      so you can view it. Note: image generation still costs
                      a few cents even in dry run.)
- MEME_DRY_RUN=0  -> post the image + caption to X for real.
"""

import os
import re
import sys
import json
import base64
import random
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("meme")

# --- Config ------------------------------------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
TEXT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")          # concept/caption writer
IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")   # image generator
COIN_NAME = os.environ.get("COIN_NAME", "The Loudest Coin")
DRY_RUN = os.environ.get("MEME_DRY_RUN", "1") == "1"                # default safe

X_API_KEY = os.environ.get("X_API_KEY", "")
X_API_SECRET = os.environ.get("X_API_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET", "")

OUT_PATH = os.environ.get("MEME_OUT", "meme.png")
MAX_CAPTION = 200

# Seeds so memes vary instead of repeating the same joke.
MEME_SITUATIONS = [
    "the coin's megaphone mascot being comically, endearingly LOUD",
    "a tiny mascot yelling into a giant megaphone in an empty room",
    "the mascot cheering on the community like an over-enthusiastic coach",
    "relatable 'crypto Twitter at 3am' energy, SFW and silly",
    "the mascot proudly wearing headphones because everything is too loud",
    "a wholesome 'gm' morning scene with the loud mascot whispering for once",
    "the mascot as a tiny DJ hyping a crowd of friendly blobs",
    "the mascot getting shushed in a library, refusing to be quiet",
    "an absurd 'volume knob turned to 11' visual gag",
    "the mascot high-fiving community members after a group call",
    "the mascot as a town crier ringing a bell nobody asked for",
    "a cozy 'community group chat' vibe with the loud mascot",
]

# Financial-promise language we never want in a caption.
BANNED = re.compile(
    r"\b(buy now|sell|ape in|aping|moon(shot)?|100x|1000x|to the moon|"
    r"get rich|guaranteed|financial advice|pump|don'?t miss|last chance|"
    r"you'?ll regret|dump)\b",
    re.IGNORECASE,
)

CONCEPT_SYSTEM = f"""You create ORIGINAL, brand-safe memes for {COIN_NAME}, a
community crypto project with a loud/megaphone theme. You are an automated,
openly-disclosed project account.

Return ONLY a JSON object: {{"image_prompt": "...", "caption": "..."}}

Rules you never break:
- Humor is about the brand's vibe and community culture. It is light, silly, wholesome.
- NEVER reference price, gains, buying, selling, "moon", "100x", getting rich,
  guarantees, or fear-of-missing-out. No financial advice of any kind.
- Never mock or shame anyone (especially people who don't hold the coin).
- image_prompt: describe a single clean, colorful, funny illustration. Use an
  ORIGINAL mascot (a friendly megaphone/loudspeaker character). No real people,
  no existing memes, no copyrighted characters, no brand logos, no text baked
  into the image.
- caption: a short, witty tweet under {MAX_CAPTION} characters. At most one
  hashtag. No links.
"""


def generate_concept() -> dict:
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
            temperature=0.9,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Concept was not valid JSON, retrying...")
            continue
        caption = data.get("caption", "").strip()
        prompt = data.get("image_prompt", "").strip()
        if not caption or not prompt:
            continue
        if len(caption) > MAX_CAPTION:
            caption = caption[:MAX_CAPTION].rsplit(" ", 1)[0]
        if BANNED.search(caption):
            log.warning("Caption tripped the no-hype filter, retrying...")
            continue
        return {"image_prompt": prompt, "caption": caption}

    raise RuntimeError("Could not produce a clean meme concept after 3 tries.")


def generate_image(image_prompt: str) -> bytes:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    full = (
        image_prompt
        + " Flat, clean, vibrant cartoon illustration. Original characters only. "
        "No text, no watermarks, no logos."
    )
    result = client.images.generate(model=IMAGE_MODEL, prompt=full, size="1024x1024", n=1)
    item = result.data[0]
    b64 = getattr(item, "b64_json", None)
    if b64:
        return base64.b64decode(b64)
    # dall-e-3 returns a URL by default
    import requests
    return requests.get(item.url, timeout=60).content


def post_to_x(caption: str, image_path: str) -> None:
    import tweepy
    auth = tweepy.OAuth1UserHandler(X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET)
    api_v1 = tweepy.API(auth)                       # v1.1, needed for media upload
    media = api_v1.media_upload(filename=image_path)
    client_v2 = tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_SECRET,
    )
    resp = client_v2.create_tweet(text=caption, media_ids=[media.media_id_string])
    log.info("Posted tweet id=%s", resp.data.get("id"))


def main() -> int:
    if not OPENAI_API_KEY:
        log.error("OPENAI_API_KEY is not set.")
        return 1

    concept = generate_concept()
    log.info("Caption (%d chars): %s", len(concept["caption"]), concept["caption"])
    log.info("Image prompt: %s", concept["image_prompt"])

    image_bytes = generate_image(concept["image_prompt"])
    with open(OUT_PATH, "wb") as f:
        f.write(image_bytes)
    log.info("Saved image to %s (%d bytes)", OUT_PATH, len(image_bytes))

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

    post_to_x(concept["caption"], OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
