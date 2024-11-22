import io
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime
from xml.sax.saxutils import escape  # Import for XML escaping

from dotenv import load_dotenv
from flask import (Flask, Response, flash, redirect, render_template, request,
                   send_file, send_from_directory, url_for)
from werkzeug.utils import secure_filename

# Determine the script's directory
script_dir = os.path.dirname(os.path.abspath(__file__))

# Load environment variables
dotenv_path = os.path.join(script_dir, "import/.env")
load_dotenv(dotenv_path)

# Define paths inside the 'import' folder
IMPORT_FOLDER = os.path.join(script_dir, "import")
UPLOAD_FOLDER = os.path.join(IMPORT_FOLDER, "uploads")
TRANSCRIPTIONS_FOLDER = os.path.join(IMPORT_FOLDER, "transcriptions")
DB_PATH = os.path.join(IMPORT_FOLDER, "transcriptions.db")
LOGS_FOLDER = os.path.join(IMPORT_FOLDER, "logs")
LOG_FILE = os.path.join(LOGS_FOLDER, "app_frontend.log")
SECRET_KEY_FILE = os.path.join(
    IMPORT_FOLDER, "secret.key"
)  # File to store the secret key

# Create necessary folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TRANSCRIPTIONS_FOLDER, exist_ok=True)
os.makedirs(LOGS_FOLDER, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),  # Logs to stdout
        logging.FileHandler(LOG_FILE, encoding="utf-8"),  # Logs to file
    ],
)

# Initialize SQLite database
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS transcriptions (
        id TEXT PRIMARY KEY,
        filename TEXT UNIQUE,
        title TEXT,
        transcription TEXT,
        summary TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""
)
conn.commit()

# Initialize Flask app
app = Flask(__name__)
# Set the secret key from the file
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["TRANSCRIPTIONS_FOLDER"] = TRANSCRIPTIONS_FOLDER

# Supported video extensions
video_extensions = (".mkv", ".mp4", ".avi", ".mov", ".flv", ".wmv")
audio_extensions = (".mp3", ".wav", ".aac", ".flac", ".ogg", ".wma", ".m4a")


def get_secret_key():
    """
    Retrieves the secret key from a file or generates a new one if the file does not exist.
    """
    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, "rb") as key_file:
            secret_key = key_file.read()
            logging.info("Loaded secret key from file.")
    else:
        secret_key = os.urandom(24)
        with open(SECRET_KEY_FILE, "wb") as key_file:
            key_file.write(secret_key)
            logging.info("Generated new secret key and saved to file.")
    return secret_key


app.secret_key = get_secret_key()


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files.get("file")
        if file:
            filename = secure_filename(file.filename)
            if not filename.lower().endswith(video_extensions + audio_extensions):
                flash("Unsupported file type.", "danger")
                return redirect(url_for("index"))

            unique_id = uuid.uuid4().hex
            original_filename = os.path.splitext(filename)[0]
            file_extension = os.path.splitext(filename)[1]
            unique_filename = f"{original_filename}_{unique_id}{file_extension}"
            filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
            file.save(filepath)
            logging.info(f"Uploaded file: {unique_filename}")

            # Check if file is already in DB
            cursor.execute(
                "SELECT status FROM transcriptions WHERE filename = ?",
                (unique_filename,),
            )
            result = cursor.fetchone()
            if result:
                status = result[0]
                if status in ("completed", "processing"):
                    logging.info(
                        f"File already processed or in process: {unique_filename}"
                    )
                    flash("Already transcribed.", "warning")
                elif status == "failed":
                    logging.info(f"Reprocessing failed file: {unique_filename}")
                    flash("Reprocessing file.", "info")
            else:
                # Insert new entry with 'pending' status
                transcription_id = uuid.uuid4().hex
                cursor.execute(
                    """
                    INSERT INTO transcriptions (id, filename, status)
                    VALUES (?, ?, 'pending')
                    """,
                    (transcription_id, unique_filename),
                )
                conn.commit()
                logging.info(f"Added to queue: {unique_filename}")
                flash("Added to queue.", "success")

            return redirect(url_for("index"))

    # Fetch transcription list
    cursor.execute(
        "SELECT id, filename, status FROM transcriptions ORDER BY created_at DESC"
    )
    transcriptions = cursor.fetchall()

    return render_template("index.html", transcriptions=transcriptions)


@app.route("/transcriptions/<filename>")
def download_file(filename):
    try:
        # Query the database for the transcription, summary, and title with the given filename
        cursor.execute(
            "SELECT transcription, summary, title FROM transcriptions WHERE filename = ?",
            (filename,),
        )
        result = cursor.fetchone()

        if result and result[0]:
            transcription_content, summary_content, title = result
            # Use 'title' in the download filename if it exists
            download_filename = (
                f"{title if title else filename}_transcription_summary.html"
            )

            # Format the content as HTML
            html_content = f"""<!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <title>{title if title else 'Transcription Summary'}</title>
                </head>
                <body>
                    <article>
                        <header>
                            <h1>{title if title else 'No Title'}</h1>
                        </header>
                        <section class="summary">
                            <h2>Summary</h2>
                            <p>{summary_content}</p>
                        </section>
                        <section class="transcription">
                            <h2>Transcription</h2>
                            <p>{transcription_content}</p>
                        </section>
                    </article>
                </body>
                </html>"""

            # Create a BytesIO object from the HTML content
            buffer = io.BytesIO()
            buffer.write(html_content.encode("utf-8"))
            buffer.seek(0)

            # Send the content as a downloadable HTML file
            return send_file(
                buffer,
                as_attachment=True,
                download_name=download_filename,
                mimetype="text/html",
            )
        else:
            flash("Transcription not found.", "danger")
            return redirect(url_for("index"))
    except Exception as e:
        logging.error(f"Error downloading transcription for {filename}: {e}")
        flash("An error occurred while downloading the transcription.", "danger")
        return redirect(url_for("index"))


def get_transcriptions():
    cursor.execute(
        "SELECT filename, title, transcription, summary, status FROM transcriptions ORDER BY created_at DESC"
    )
    rows = cursor.fetchall()
    return rows


@app.route("/remove_transcription", methods=["POST"])
def remove_transcription():
    transcription_id = request.form.get("transcription_id")
    if not transcription_id:
        flash("No transcription ID provided.", "danger")
        return redirect(url_for("index"))

    try:
        # Fetch the transcription details from the database
        cursor.execute(
            "SELECT filename, status FROM transcriptions WHERE id = ?",
            (transcription_id,),
        )
        result = cursor.fetchone()
        if not result:
            flash("Transcription not found.", "danger")
            return redirect(url_for("index"))

        filename, status = result

        # Prevent removal if transcription is still processing
        if status == "processing":
            flash("Cannot remove a transcription that is still processing.", "warning")
            return redirect(url_for("index"))

        # Begin transaction
        cursor.execute("DELETE FROM transcriptions WHERE id = ?", (transcription_id,))
        conn.commit()

        # Remove the uploaded file from the server
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            logging.info(f"Removed file: {filename}")

        # Optionally, remove associated transcription files if stored separately
        # For example, if transcription and summary are saved as separate files:
        # transcription_file = os.path.join(app.config["TRANSCRIPTIONS_FOLDER"], f"{filename}_transcription.txt")
        # summary_file = os.path.join(app.config["TRANSCRIPTIONS_FOLDER"], f"{filename}_summary.txt")
        # for path in [transcription_file, summary_file]:
        #     if os.path.exists(path):
        #         os.remove(path)
        #         logging.info(f"Removed transcription file: {path}")

        flash(f"Transcription '{filename}' has been removed successfully.", "success")
    except Exception as e:
        logging.error(f"Error removing transcription {transcription_id}: {e}")
        flash("An error occurred while trying to remove the transcription.", "danger")

    return redirect(url_for("index"))


def generate_rss(transcriptions):
    rss_items = ""
    for transcription in transcriptions:
        try:
            filename, transcription, summary, status, created_at = transcription
            if status == "completed":
                link = f"https://transcribe.tbelbek.com/transcriptions/{filename}"
                
                # Escape XML-sensitive characters
                safe_summary = escape(summary) if summary else "No Summary Available."
                safe_transcription = escape(transcription) if transcription else "No Transcription Available."
                
                # Convert created_at to datetime object if it's a string
                if isinstance(created_at, str):
                    try:
                        # Adjust the format string based on your actual created_at format
                        created_at_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        logging.warning(f"Invalid date format for transcription '{filename}'. Using current UTC time.")
                        created_at_dt = datetime.utcnow()
                elif isinstance(created_at, datetime):
                    created_at_dt = created_at
                else:
                    logging.warning(f"Unsupported type for created_at in transcription '{filename}'. Using current UTC time.")
                    created_at_dt = datetime.utcnow()
                
                # Format the date to RFC 2822
                pub_date = created_at_dt.strftime('%a, %d %b %Y %H:%M:%S +0000')
                
                # Format the content to include title, summary, and transcription with HTML formatting
                description_content = f"""
                <article>
                    <header>
                        <h1>{safe_title}</h1>
                    </header>
                    <section class="summary">
                        <h2>Summary</h2>
                        <p>{safe_summary}</p>
                    </section>
                    <section class="transcription">
                        <h2>Transcription</h2>
                        <p>{safe_transcription}</p>
                    </section>
                </article>
                """
                
                # Append the RSS item with CDATA section for description
                rss_items += f"""
                <item>
                    <title>{safe_title}</title>
                    <description><![CDATA[
                    {description_content}
                    ]]></description>
                    <link>{link}</link>
                    <pubDate>{pub_date}</pubDate>
                </item>
                """
        except Exception as e:
            logging.exception(f"Error processing transcription {transcription}: {e}")
            continue  # Skip to the next transcription in case of error
    
    rss_feed = f"""<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
        <channel>
            <title>Video Transcriptions RSS Feed</title>
            <link>https://transcribe.tbelbek.com/rss</link>
            <description>RSS feed of video transcriptions and summaries.</description>
            {rss_items}
        </channel>
    </rss>"""
    return rss_feed


@app.route("/rss")
def rss():
    transcriptions = get_transcriptions()
    rss_feed = generate_rss(transcriptions)
    return Response(rss_feed, mimetype="application/rss+xml")


@app.route("/transcriptions")
def list_transcriptions():
    transcriptions = get_transcriptions()
    return render_template("transcriptions.html", transcriptions=transcriptions)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
