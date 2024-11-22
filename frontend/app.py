import io
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime

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
SECRET_KEY_FILE = os.path.join(IMPORT_FOLDER, "secret.key")  # File to store the secret key

# Create necessary folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TRANSCRIPTIONS_FOLDER, exist_ok=True)
os.makedirs(LOGS_FOLDER, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),                # Logs to stdout
        logging.FileHandler(LOG_FILE, encoding='utf-8')  # Logs to file
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
                    logging.info(f"File already processed or in process: {unique_filename}")
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
    cursor.execute("SELECT id, filename, status FROM transcriptions ORDER BY created_at DESC")
    transcriptions = cursor.fetchall()

    return render_template("index.html", transcriptions=transcriptions)


@app.route("/transcriptions/<filename>")
def download_file(filename):
    try:
        # Query the database for the transcription with the given filename
        cursor.execute(
            "SELECT transcription, title FROM transcriptions WHERE filename = ?",
            (filename,)
        )
        result = cursor.fetchone()
        
        if result and result[0]:
            transcription_content, title = result
            # If 'title' exists, use it as part of the download filename
            download_filename = f"{title if title else filename}_transcription.txt"
            
            # Create a BytesIO object from the transcription content
            buffer = io.BytesIO()
            buffer.write(transcription_content.encode('utf-8'))
            buffer.seek(0)
            
            # Send the transcription as a downloadable file
            return send_file(
                buffer,
                as_attachment=True,
                download_name=download_filename,
                mimetype='text/plain'
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


def generate_rss(transcriptions):
    rss_items = ""
    for filename, title, transcription, summary, status in transcriptions:
        if status == "completed":
            link = f"https://yourdomain.com/transcriptions/{filename}"  # Replace with your domain
            rss_items += f"""
            <item>
                <title>{title}</title>
                <description>{summary}</description>
                <link>{link}</link>
                <pubDate>{datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
            </item>
            """
    rss_feed = f"""<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
        <channel>
            <title>Video Transcriptions RSS Feed</title>
            <link>https://yourdomain.com/</link>  <!-- Replace with your domain -->
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