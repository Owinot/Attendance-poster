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
PHOTO_BOX = (310, 573, 710, 973)      # circular photo area inside the gold frame
PHOTO_CENTER = (510, 773)
PHOTO_RADIUS = 200
NAME_BOX = (172, 1010, 852, 1083)     # inside the existing green-and-gold name plaque
QR_BOX = (680, 1265, 872, 1445)       # white QR panel at the bottom-right


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

    # Prepare a square, centre-cropped portrait and clip it to a circle.
    photo = ImageOps.exif_transpose(uploaded_photo).convert("RGB")
    diameter = PHOTO_RADIUS * 2
    photo = ImageOps.fit(photo, (diameter, diameter), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))
    mask = Image.new("L", (diameter, diameter), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=255)

    left = PHOTO_CENTER[0] - PHOTO_RADIUS
    top = PHOTO_CENTER[1] - PHOTO_RADIUS
    poster.paste(photo, (left, top), mask)

    # Replace only the name inside the existing plaque; preserve its gold outline.
    draw = ImageDraw.Draw(poster)
    draw.rounded_rectangle(NAME_BOX, radius=34, fill=(0, 57, 20))
    clean_name = " ".join(name.strip().split())[:45]
    font = fit_name(draw, clean_name, max_width=620)
    bbox = draw.textbbox((0, 0), clean_name, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (poster.width - text_w) / 2
    y = NAME_BOX[1] + ((NAME_BOX[3] - NAME_BOX[1]) - text_h) / 2 - bbox[1]
    draw.text((x, y), clean_name, font=font, fill=(255, 255, 255))

    time_font = load_font(24)
    time_bbox = draw.textbbox((0, 0), EVENT_TIME, font=time_font)
    time_x = 178 - time_bbox[0]
    time_y = 1214 - time_bbox[1]
    draw.text((time_x, time_y), EVENT_TIME, font=time_font, fill=(255, 255, 255))

    # Replace the template's sample QR with a real QR pointing to the live form.
    qr_size = 176
    qr_img = make_qr(PUBLIC_BASE_URL + "/", qr_size)
    qr_x = 678
    qr_y = 1267
    # White backing ensures a clear quiet zone and reliable scanning.
    draw.rectangle((QR_BOX[0], QR_BOX[1], QR_BOX[2], QR_BOX[3]), fill="white")
    poster.paste(qr_img, (qr_x, qr_y))

    output = BytesIO()
    poster.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


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
        return render_template("index.html", error="Please keep your name to 45 characters or fewer."), 400
    if not photo_file or not photo_file.filename:
        return render_template("index.html", error="Please choose a photograph."), 400
    if not allowed_file(photo_file.filename):
        return render_template("index.html", error="Please upload a JPG or PNG image."), 400

    try:
        image = Image.open(photo_file.stream)
        image.verify()
        photo_file.stream.seek(0)
        image = Image.open(photo_file.stream)
        poster_file = create_poster(name, image)
    except (UnidentifiedImageError, OSError, ValueError):
        return render_template("index.html", error="That image could not be opened. Please try another JPG or PNG."), 400

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
