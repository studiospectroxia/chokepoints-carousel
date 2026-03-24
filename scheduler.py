"""
scheduler.py
------------
GitHub Actions version.
1. Picks next pending entry
2. Generates carousel
3. Uploads slides to Cloudinary
4. Writes pending_post.json to repo (Worker reads this on /approve)
5. Sends Telegram preview
"""

import os, json, sys, asyncio, hashlib, base64
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import requests

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
DB_PATH    = SCRIPT_DIR / "chokepoints.json"
OUTPUT_DIR = SCRIPT_DIR / "output_v2"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_raw_ids  = os.getenv("TELEGRAM_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_ID", "")
CHAT_IDS  = [int(x.strip()) for x in _raw_ids.split(",") if x.strip()]

CLOUDINARY_CLOUD = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_KEY   = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_SEC   = os.getenv("CLOUDINARY_API_SECRET")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO  = os.getenv("GITHUB_REPO")  # e.g. "yourname/chokepoints-carousel"


# ── DATABASE ──────────────────────────────────────────────────────────────────
def get_next_pending():
    with open(DB_PATH) as f:
        db = json.load(f)
    for e in db:
        if e.get("post_status") == "pending":
            return e
    return None


def mark_as_generated(entry_name):
    with open(DB_PATH) as f:
        db = json.load(f)
    for e in db:
        if e["name"] == entry_name:
            e["post_status"] = "generated"
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2)


# ── CLOUDINARY ────────────────────────────────────────────────────────────────
def upload_to_cloudinary(file_path, public_id):
    timestamp = str(int(datetime.now().timestamp()))
    params    = f"public_id={public_id}&timestamp={timestamp}"
    signature = hashlib.sha1((params + CLOUDINARY_SEC).encode()).hexdigest()

    url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD}/image/upload"
    with open(file_path, "rb") as f:
        resp = requests.post(url, data={
            "api_key":   CLOUDINARY_KEY,
            "timestamp": timestamp,
            "public_id": public_id,
            "signature": signature,
        }, files={"file": f}, timeout=30)

    if resp.status_code == 200:
        return resp.json()["secure_url"]
    raise Exception(f"Cloudinary upload failed: {resp.status_code} {resp.text}")


def upload_slides(entry, slide_paths):
    slug = entry["name"].lower().replace(" ", "_")
    urls = []
    for i, path in enumerate(slide_paths, 1):
        public_id = f"chokepoints/{slug}_slide_{i:02d}"
        print(f"  Uploading slide {i}/6...", end=" ", flush=True)
        url = upload_to_cloudinary(path, public_id)
        urls.append(url)
        print("done.")
    return urls


# ── CAPTION ───────────────────────────────────────────────────────────────────
def build_caption(entry):
    c      = entry["carousel"]
    region = entry.get("region", "").lower()
    tags   = ["#geopolitics", "#worldhistory", "#geography", "#maps",
              "#didyouknow", "#globalaffairs", "#chokepoints", "#learnhistory"]
    if "asia" in region or "pacific" in region:
        tags += ["#asia", "#pacific"]
    if "middle east" in region or "gulf" in region:
        tags += ["#middleeast", "#energy"]
    if "europe" in region:
        tags += ["#europe", "#nato"]
    if "africa" in region:
        tags += ["#africa"]

    return (
        f"{c['slide1']['headline']}\n\n"
        f"{c['slide1']['body']}\n\n"
        f"Swipe to find out more →\n\n"
        f"{' '.join(tags[:12])}"
    )


# ── PENDING_POST.JSON → GITHUB ────────────────────────────────────────────────
def write_pending_post_to_github(entry, image_urls):
    """
    Writes pending_post.json to the GitHub repo so the Cloudflare
    Worker can read it when /approve is received.
    """
    pending = {
        "name":       entry["name"],
        "caption":    build_caption(entry),
        "image_urls": image_urls,
        "generated":  datetime.now().isoformat(),
    }
    content      = json.dumps(pending, indent=2)
    content_b64  = base64.b64encode(content.encode()).decode()
    api_url      = f"https://api.github.com/repos/{GITHUB_REPO}/contents/pending_post.json"
    headers      = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github+json",
        "User-Agent":    "chokepoints-scheduler",
    }

    # Check if file already exists (need its SHA to update)
    existing = requests.get(api_url, headers=headers)
    sha      = existing.json().get("sha") if existing.status_code == 200 else None

    body = {
        "message": f"pending post: {entry['name']}",
        "content": content_b64,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(api_url, headers=headers, json=body)
    if resp.status_code in (200, 201):
        print("  pending_post.json written to GitHub.")
    else:
        raise Exception(f"GitHub write failed: {resp.status_code} {resp.text}")


# ── TELEGRAM PREVIEW ──────────────────────────────────────────────────────────
async def send_telegram_preview(entry, slide_paths):
    from telegram import Bot, InputMediaPhoto

    bot     = Bot(token=BOT_TOKEN)
    caption = (
        f"*{entry['name']}*\n\n"
        f"_{entry['carousel']['slide1']['headline']}_\n\n"
        f"{entry['carousel']['slide1']['body']}\n\n"
        f"Region: {entry.get('region', '—')}\n\n"
        f"/approve — post · /reject — regenerate · /skip — skip"
    )

    media = []
    for i, path in enumerate(slide_paths):
        with open(path, "rb") as f:
            media.append(InputMediaPhoto(
                media=f.read(),
                caption=caption if i == 0 else None,
                parse_mode="Markdown" if i == 0 else None,
            ))

    for chat_id in CHAT_IDS:
        print(f"  Sending preview to {chat_id}...")
        await bot.send_media_group(chat_id=chat_id, media=media)
        await bot.send_message(
            chat_id=chat_id,
            text="👆 Today's carousel.\n\n/approve → post to Instagram\n/reject → regenerate\n/skip → skip"
        )


async def notify_exhausted():
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    for chat_id in CHAT_IDS:
        await bot.send_message(
            chat_id=chat_id,
            text="📭 *All chokepoints posted.*\n\nAdd more entries to continue.",
            parse_mode="Markdown"
        )


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  Chokepoints Scheduler")
    print("=" * 50)

    # Step 1: Get next entry
    entry = get_next_pending()
    if not entry:
        print("  No pending entries.")
        asyncio.run(notify_exhausted())
        sys.exit(0)

    print(f"\n  Entry: {entry['name']}")

    # Step 2: Generate slides
    OUTPUT_DIR.mkdir(exist_ok=True)
    slug        = entry["name"].lower().replace(" ", "_")
    slide_paths = [OUTPUT_DIR / f"{slug}_slide_{i:02d}.png" for i in range(1, 7)]

    if all(p.exists() for p in slide_paths):
        print("  Slides already exist, skipping generation.")
    else:
        print("  Generating slides...")
        from generate_carousel_v2 import generate
        generate(entry)

    # Step 3: Upload to Cloudinary
    print("\n  Uploading to Cloudinary...")
    image_urls = upload_slides(entry, slide_paths)

    # Step 4: Write pending_post.json to GitHub
    print("\n  Writing pending_post.json to GitHub...")
    write_pending_post_to_github(entry, image_urls)

    # Step 5: Mark as generated
    mark_as_generated(entry["name"])

    # Step 6: Send Telegram preview
    print("\n  Sending Telegram preview...")
    asyncio.run(send_telegram_preview(entry, slide_paths))

    print("\n  Done. Waiting for /approve from Telegram.")


if __name__ == "__main__":
    main()
