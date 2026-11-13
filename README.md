# Annual Career Summit 2026 — Automatic Poster Generator

This Flask app lets attendees submit their name and photo and download a personalised
"I WILL BE ATTENDING" poster. The summit design, logo, FREE ENTRY label, date and
venue remain fixed.

## Files
- `app.py` — Flask routes and poster generation
- `poster_template.png` — supplied summit poster design
- `templates/index.html` — mobile-friendly form
- `static/style.css` — form styling

## Run locally

1. Install Python 3.10 or newer.
2. Open a terminal in this folder.
3. Create and activate a virtual environment:

   macOS/Linux:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   Windows:
   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   ```

4. Install packages:
   ```bash
   pip install -r requirements.txt
   ```

5. Start the app:
   ```bash
   python app.py
   ```

6. Open `http://127.0.0.1:5000`.

## Important: make the QR code work for everyone

A QR code cannot point to `127.0.0.1` for public visitors. Deploy this app to a public
HTTPS address first, then set the environment variable `PUBLIC_BASE_URL` to that
exact public address (for example, `https://your-app.example.com`) and redeploy.
The poster generator will then place a real QR code linking to the public form.

For Render, a typical start command is:
```bash
gunicorn app:app
```
Set `PUBLIC_BASE_URL` in the service's environment variables to the deployed HTTPS URL.

## Privacy and production notes

- Uploaded photos are processed in memory for the response and are not written to a
  public uploads folder by this app.
- The app limits uploads to 8 MB and accepts JPG/PNG images.
- Before sharing widely, deploy over HTTPS, test on several phones, and consider adding
  rate limiting and a short privacy notice/contact for questions.
- The QR code printed on the final public campaign poster should point to the deployed
  app URL, not the old Google Forms `/edit` URL.
# Attendance-poster
# Attendance-poster
