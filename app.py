import os
from io import BytesIO

import cv2
import numpy as np
import qrcode

from flask import Flask, render_template, request, send_file
from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageOps,
    UnidentifiedImageError,
)
from werkzeug.utils import secure_filename


app = Flask(__name__)

# --------------------------------------------------
# APPLICATION SETTINGS
# --------------------------------------------------

app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "poster_template.png")

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
DEFAULT_QR_TARGET_URL = "https://attendance-poster.onrender.com/"
QR_TARGET_URL = os.environ.get("QR_TARGET_URL", DEFAULT_QR_TARGET_URL)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
EVENT_TIME = "8:00 AM - 5:00 PM"

# --------------------------------------------------
# POSTER COORDINATES
# Designed for a 1024 x 1536 poster.
# --------------------------------------------------

PHOTO_CENTER = (510, 773)
PHOTO_RADIUS = 185
ERASE_RADIUS = 260

# QR code panel.
QR_BOX = (680, 1265, 872, 1445)

# Name plaque.
# The original template's name banner is approximately y=995 to y=1098.
# Cover the FULL original name area so old lettering cannot show through.
NAME_PLAQUE = (150, 995, 874, 1098)
NAME_CENTER = (512, 1047)
NAME_MAX_WIDTH = 650
NAME_MAX_SIZE = 58
NAME_MIN_SIZE = 18
NAME_COLOR = (255, 255, 255)
NAME_STROKE_COLOR = (0, 57, 20)
NAME_STROKE_WIDTH = 1


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------


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
            continue

    return ImageFont.load_default()


def fit_name_to_plaque(draw, name):
    """
    Keep the attendee's name on ONE line.
    Reduce the font until the complete name fits inside the plaque.
    """
    cleaned_name = " ".join(name.split()).upper()

    plaque_left, plaque_top, plaque_right, plaque_bottom = NAME_PLAQUE
    available_width = min(
        NAME_MAX_WIDTH,
        plaque_right - plaque_left - 70,
    )
    available_height = plaque_bottom - plaque_top - 24

    for size in range(NAME_MAX_SIZE, NAME_MIN_SIZE - 1, -1):
        font = load_font(size)
        bbox = draw.textbbox(
            (0, 0),
            cleaned_name,
            font=font,
            stroke_width=NAME_STROKE_WIDTH,
        )
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        if text_width <= available_width and text_height <= available_height:
            return cleaned_name, font

    # The form limits names to 45 characters, so this is a final
    # safety fallback for unusually wide names or missing font files.
    font = load_font(NAME_MIN_SIZE)
    return cleaned_name, font


# --------------------------------------------------
# REMOVE OLD PHOTO USING OPENCV INPAINTING
# --------------------------------------------------


def remove_original_photo(poster):
    image = np.array(poster.convert("RGB"))
    height, width = image.shape[:2]

    cx, cy = PHOTO_CENTER
    mask = np.zeros((height, width), dtype=np.uint8)

    cv2.circle(mask, (cx, cy), ERASE_RADIUS, 255, thickness=-1)

    cleaned = cv2.inpaint(image, mask, 7, cv2.INPAINT_TELEA)
    return Image.fromarray(cleaned)


# --------------------------------------------------
# GENERATE QR CODE
# --------------------------------------------------


def make_qr(url, size):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )

    qr.add_data(url)
    qr.make(fit=True)

    qr_image = qr.make_image(
        fill_color="black",
        back_color="white",
    ).convert("RGB")

    return qr_image.resize(
        (size, size),
        Image.Resampling.NEAREST,
    )


# --------------------------------------------------
# ADD UPLOADED PHOTO
# --------------------------------------------------


def add_uploaded_photo(poster, uploaded_photo):
    cx, cy = PHOTO_CENTER

    gold_radius = PHOTO_RADIUS + 14
    green_radius = PHOTO_RADIUS + 6

    draw = ImageDraw.Draw(poster)

    draw.ellipse(
        (cx - gold_radius, cy - gold_radius, cx + gold_radius, cy + gold_radius),
        fill=(218, 165, 32),
    )

    draw.ellipse(
        (cx - green_radius, cy - green_radius, cx + green_radius, cy + green_radius),
        fill=(0, 57, 20),
    )

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

    left = cx - PHOTO_RADIUS
    top = cy - PHOTO_RADIUS
    poster.paste(photo, (left, top), mask)

    return poster


# --------------------------------------------------
# ADD NAME TO POSTER
# --------------------------------------------------


def add_name(poster, name):
    draw = ImageDraw.Draw(poster)

    # Draw the attendee's name plaque over the complete old name area.
    # This hides any sample name already printed on the template.
    plaque_left, plaque_top, plaque_right, plaque_bottom = NAME_PLAQUE

    draw.rounded_rectangle(
        NAME_PLAQUE,
        radius=55,
        fill=(0, 70, 25),
        outline=(245, 190, 20),
        width=9,
    )

    # Fit the complete name on one line instead of wrapping it.
    display_name, font = fit_name_to_plaque(draw, name)

    # Anchor="mm" centers the actual text at this point.
    # This avoids manual width calculations and multiline alignment issues.
    draw.text(
        NAME_CENTER,
        display_name,
        font=font,
        fill=NAME_COLOR,
        anchor="mm",
        stroke_width=NAME_STROKE_WIDTH,
        stroke_fill=NAME_STROKE_COLOR,
    )

    return poster


# --------------------------------------------------
# ADD QR CODE TO POSTER
# --------------------------------------------------


def add_qr_code(poster):
    x1, y1, x2, y2 = QR_BOX

    box_width = x2 - x1
    box_height = y2 - y1
    qr_size = min(box_width, box_height) - 20

    qr_image = make_qr(QR_TARGET_URL, qr_size)

    left = x1 + (box_width - qr_size) // 2
    top = y1 + (box_height - qr_size) // 2

    poster.paste(qr_image, (left, top))
    return poster


# --------------------------------------------------
# MAIN POSTER GENERATION FUNCTION
# --------------------------------------------------


def create_poster(name, uploaded_photo):
    if not os.path.exists(TEMPLATE_PATH):
        raise FileNotFoundError("poster_template.png was not found.")

    poster = Image.open(TEMPLATE_PATH).convert("RGB")
    poster = ImageOps.exif_transpose(poster)

    # These coordinates are designed for the 1024 x 1536 template.
    if poster.size != (1024, 1536):
        raise ValueError(
            "The poster template must be 1024 x 1536 pixels. "
            f"Current size: {poster.width} x {poster.height}."
        )

    poster = remove_original_photo(poster)
    poster = add_uploaded_photo(poster, uploaded_photo)
    poster = add_name(poster, name)
    poster = add_qr_code(poster)

    output = BytesIO()
    poster.save(output, format="PNG", optimize=True)
    output.seek(0)

    return output


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------


@app.get("/")
def index():
    return render_template("index.html", event_time=EVENT_TIME)


# --------------------------------------------------
# GENERATE POSTER ROUTE
# --------------------------------------------------


@app.post("/generate")
def generate():
    name = request.form.get("name", "").strip()
    photo_file = request.files.get("photo")

    if not name:
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="Please enter your name.",
        ), 400

    if len(name) > 45:
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="Please keep your name to 45 characters or fewer.",
        ), 400

    if not photo_file or not photo_file.filename:
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="Please choose a photograph.",
        ), 400

    if not allowed_file(photo_file.filename):
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="Please upload a JPG or PNG image.",
        ), 400

    try:
        image = Image.open(photo_file.stream)
        image.verify()

        photo_file.stream.seek(0)
        image = Image.open(photo_file.stream)

        poster_file = create_poster(name, image)

    except (UnidentifiedImageError, OSError, ValueError) as error:
        app.logger.warning("Invalid uploaded image or poster: %s", error)
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error=(
                "The image could not be processed, or the poster template "
                "has the wrong dimensions. Please check the files and try again."
            ),
        ), 400

    except FileNotFoundError as error:
        app.logger.error(str(error))
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error=(
                "The poster template could not be found. "
                "Please contact the administrator."
            ),
        ), 500

    except Exception:
        app.logger.exception("Poster generation failed.")
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="Something went wrong while generating your poster. Please try again.",
        ), 500

    safe_name = secure_filename("_".join(name.split()))[:45] or "attendee"

    return send_file(
        poster_file,
        mimetype="image/png",
        as_attachment=True,
        download_name=f"career_summit_{safe_name}.png",
    )


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
    )
