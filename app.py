import os
from io import BytesIO

import qrcode
from flask import Flask, render_template, request, send_file
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB upload limit

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "poster_template.png")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
EVENT_TIME = "8:00 AM - 5:00 PM"

# Coordinates are tuned to the supplied 1024 x 1536 summit poster.
PHOTO_BOX = (285, 548, 735, 998)  # circular photo area inside the gold frame
PHOTO_CENTER = (510, 773)
PHOTO_RADIUS = 185
ORIGINAL_FRAME_RADIUS = 248  # inside the existing green-and-gold name plaque
QR_BOX = (680, 1265, 872, 1445)  # white QR panel at the bottom-right


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def load_font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def make_qr(url, size):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return qr_image.resize((size, size), Image.Resampling.NEAREST)


def fit_name(draw, name, max_width, max_size=64, min_size=24):
    for size in range(max_size, min_size - 1, -1):
        font = load_font(size)
        bbox = draw.textbbox((0, 0), name, font=font, stroke_width=0)
        if bbox[2] - bbox[0] <= max_width:
            return font
    return load_font(min_size)


def create_poster(name, uploaded_photo):
    poster = Image.open(TEMPLATE_PATH).convert("RGB")
    poster = ImageOps.exif_transpose(poster)
    draw = ImageDraw.Draw(poster)

    # 1. Erase the old sample photo & old gold ring from the template
    # Sample the background color just outside the original frame so it blends seamlessly
    bg_color = poster.getpixel(
        (PHOTO_CENTER[0], PHOTO_CENTER[1] - ORIGINAL_FRAME_RADIUS - 5)
    )
    draw.ellipse(
        (
            PHOTO_CENTER[0] - ORIGINAL_FRAME_RADIUS,
            PHOTO_CENTER[1] - ORIGINAL_FRAME_RADIUS,
            PHOTO_CENTER[0] + ORIGINAL_FRAME_RADIUS,
            PHOTO_CENTER[1] + ORIGINAL_FRAME_RADIUS,
        ),
        fill=bg_color,
    )

    # 2. Draw a new, smaller gold and dark-green circular frame
    gold_radius = PHOTO_RADIUS + 14
    green_radius = PHOTO_RADIUS + 6
    draw.ellipse(
        (
            PHOTO_CENTER[0] - gold_radius,
            PHOTO_CENTER[1] - gold_radius,
            PHOTO_CENTER[0] + gold_radius,
            PHOTO_CENTER[1] + gold_radius,
        ),
        fill=(218, 165, 32),  # Gold outer ring
    )
    draw.ellipse(
        (
            PHOTO_CENTER[0] - green_radius,
            PHOTO_CENTER[1] - green_radius,
            PHOTO_CENTER[0] + green_radius,
            PHOTO_CENTER[1] + green_radius,
        ),
        fill=(0, 57, 20),  # Dark green inner ring
    )

    # 3. Prepare the square, centre-cropped portrait and clip it to the new smaller circle
    photo = ImageOps.exif_transpose(uploaded_photo).convert("RGB")
    diameter = PHOTO_RADIUS * 2
    photo = ImageOps.fit(
        photo,
        (diameter, diameter),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.35),
    )

    mask = Image.new("L", (diameter, diameter), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=255)

    left = PHOTO_CENTER[0] - PHOTO_RADIUS
    top = PHOTO_CENTER[1] - PHOTO_RADIUS
    poster.paste(photo, (left, top), mask)

    # ... keep the rest of your NAME_BOX, EVENT_TIME, and QR_BOX code below ...


@app.get("/")
def index():
    return render_template("index.html", event_time=EVENT_TIME)


@app.post("/generate")
def generate():
    name = request.form.get("name", "").strip()
    photo_file = request.files.get("photo")

    if not name:
        return render_template("index.html", error="Please enter your name."), 400
    if len(name) > 45:
        return render_template(
            "index.html", error="Please keep your name to 45 characters or fewer."
        ), 400
    if not photo_file or not photo_file.filename:
        return render_template("index.html", error="Please choose a photograph."), 400
    if not allowed_file(photo_file.filename):
        return render_template(
            "index.html", error="Please upload a JPG or PNG image."
        ), 400

    try:
        image = Image.open(photo_file.stream)
        image.verify()
        photo_file.stream.seek(0)
        image = Image.open(photo_file.stream)
        poster_file = create_poster(name, image)
    except (UnidentifiedImageError, OSError, ValueError):
        return render_template(
            "index.html",
            error="That image could not be opened. Please try another JPG or PNG.",
        ), 400

    safe_name = "_".join(name.split())[:45] or "attendee"
    return send_file(
        poster_file,
        mimetype="image/png",
        as_attachment=True,
        download_name=f"career_summit_{safe_name}.png",
    )


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
