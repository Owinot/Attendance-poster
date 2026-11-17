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

QR_TARGET_URL = os.environ.get("QR_TARGET_URL", PUBLIC_BASE_URL)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}

EVENT_TIME = "8:00 AM - 5:00 PM"


# --------------------------------------------------
# POSTER COORDINATES
# Adjust these if your template is positioned differently.
# Designed for a 1024 x 1536 poster.
# --------------------------------------------------

PHOTO_CENTER = (510, 773)

PHOTO_RADIUS = 185

# This must cover the entire original sample photo and frame.
ERASE_RADIUS = 260

# QR code white panel at the bottom right.
QR_BOX = (680, 1265, 872, 1445)

# Name position: keep the text centered inside the plaque below the photo.
NAME_CENTER = (510, 1065)
NAME_MAX_WIDTH = 440
NAME_MAX_SIZE = 62
NAME_MIN_SIZE = 22
NAME_LINE_SPACING = 8
NAME_TOP_PADDING = 18
NAME_BOTTOM_PADDING = 30
NAME_MIN_TOP = PHOTO_CENTER[1] + PHOTO_RADIUS + 20
NAME_MAX_BOTTOM = 1205

# Name text color.
NAME_COLOR = (255, 255, 255)


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


def wrap_name_lines(draw, name, font, max_width):
    cleaned_name = " ".join(name.split())

    if not cleaned_name:
        return [""]

    words = cleaned_name.split()
    lines = [words[0]]

    for word in words[1:]:
        candidate = f"{lines[-1]} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            lines[-1] = candidate
        else:
            lines.append(word)

    return lines


def fit_name(draw, name, max_width):
    cleaned_name = " ".join(name.split())
    if not cleaned_name:
        return load_font(NAME_MIN_SIZE), [""]

    for size in range(NAME_MAX_SIZE, NAME_MIN_SIZE - 1, -1):
        font = load_font(size)
        lines = wrap_name_lines(draw, cleaned_name, font, max_width)

        wrapped = "\n".join(lines)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=NAME_LINE_SPACING)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        if text_width <= max_width and text_height <= 180:
            return font, lines

    font = load_font(NAME_MIN_SIZE)
    return font, wrap_name_lines(draw, cleaned_name, font, max_width)


# --------------------------------------------------
# REMOVE OLD PHOTO USING OPENCV INPAINTING
# --------------------------------------------------


def remove_original_photo(poster):

    # Convert PIL image into OpenCV format.
    image = np.array(poster.convert("RGB"))

    height, width = image.shape[:2]

    cx, cy = PHOTO_CENTER

    # Create a black mask.
    mask = np.zeros((height, width), dtype=np.uint8)

    # Mark the original photo and frame area.
    cv2.circle(mask, (cx, cy), ERASE_RADIUS, 255, thickness=-1)

    # Reconstruct the background behind the original photo.
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

    qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    return qr_image.resize((size, size), Image.Resampling.NEAREST)


# --------------------------------------------------
# ADD UPLOADED PHOTO
# --------------------------------------------------


def add_uploaded_photo(poster, uploaded_photo):

    cx, cy = PHOTO_CENTER

    # Outer gold frame.
    gold_radius = PHOTO_RADIUS + 14

    # Inner dark green frame.
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

    # Correct the orientation of the uploaded photo.
    photo = ImageOps.exif_transpose(uploaded_photo).convert("RGB")

    diameter = PHOTO_RADIUS * 2

    # Crop and resize the photo to a square.
    photo = ImageOps.fit(
        photo,
        (diameter, diameter),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.35),
    )

    # Create a circular transparency mask.
    mask = Image.new("L", (diameter, diameter), 0)

    mask_draw = ImageDraw.Draw(mask)

    mask_draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=255)

    # Paste the photo onto the poster.
    left = cx - PHOTO_RADIUS
    top = cy - PHOTO_RADIUS

    poster.paste(photo, (left, top), mask)

    return poster


# --------------------------------------------------
# ADD NAME TO POSTER
# --------------------------------------------------


def add_name(poster, name):

    draw = ImageDraw.Draw(poster)

    font, lines = fit_name(draw, name, NAME_MAX_WIDTH)
    wrapped_name = "\n".join(lines)
    bbox = draw.multiline_textbbox((0, 0), wrapped_name, font=font, spacing=NAME_LINE_SPACING)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Keep the name inside the plaque band beneath the photo.
    safe_top = max(NAME_CENTER[1] - text_height // 2, NAME_MIN_TOP + NAME_TOP_PADDING)
    safe_bottom = NAME_MAX_BOTTOM - text_height - NAME_BOTTOM_PADDING
    text_top = min(max(safe_top, NAME_MIN_TOP), safe_bottom)
    text_left = NAME_CENTER[0] - text_width / 2

    draw.multiline_text(
        (text_left, text_top),
        wrapped_name,
        font=font,
        fill=NAME_COLOR,
        align="center",
        spacing=NAME_LINE_SPACING,
        stroke_width=0,
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

    # Center QR code inside its white panel.
    left = x1 + (box_width - qr_size) // 2
    top = y1 + (box_height - qr_size) // 2

    poster.paste(qr_image, (left, top))

    return poster


# --------------------------------------------------
# MAIN POSTER GENERATION FUNCTION
# --------------------------------------------------


def create_poster(name, uploaded_photo):

    # Check that the template exists.
    if not os.path.exists(TEMPLATE_PATH):
        raise FileNotFoundError("poster_template.png was not found.")

    # Open the original poster template.
    poster = Image.open(TEMPLATE_PATH).convert("RGB")

    poster = ImageOps.exif_transpose(poster)

    # IMPORTANT:
    # Remove the old sample photo before adding the new one.
    poster = remove_original_photo(poster)

    # Add the new uploaded photograph.
    poster = add_uploaded_photo(poster, uploaded_photo)

    # Add the attendee's name.
    poster = add_name(poster, name)

    # Add QR code.
    poster = add_qr_code(poster)

    # Save the completed poster into memory.
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

    # Validate name.
    if not name:
        return render_template(
            "index.html", event_time=EVENT_TIME, error="Please enter your name."
        ), 400

    if len(name) > 45:
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="Please keep your name to 45 characters or fewer.",
        ), 400

    # Validate uploaded photo.
    if not photo_file or not photo_file.filename:
        return render_template(
            "index.html", event_time=EVENT_TIME, error="Please choose a photograph."
        ), 400

    if not allowed_file(photo_file.filename):
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="Please upload a JPG or PNG image.",
        ), 400

    try:
        # Verify that the uploaded file is a valid image.
        image = Image.open(photo_file.stream)

        image.verify()

        # Reset the uploaded file stream.
        photo_file.stream.seek(0)

        # Open the image again for processing.
        image = Image.open(photo_file.stream)

        # Generate poster.
        poster_file = create_poster(name, image)

    except (UnidentifiedImageError, OSError, ValueError):
        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="That image could not be opened. Please try another JPG or PNG.",
        ), 400

    except FileNotFoundError as error:
        app.logger.error(str(error))

        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="The poster template could not be found. Please contact the administrator.",
        ), 500

    except Exception:
        app.logger.exception("Poster generation failed.")

        return render_template(
            "index.html",
            event_time=EVENT_TIME,
            error="Something went wrong while generating your poster. Please try again.",
        ), 500

    # Create a safe download filename.
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
