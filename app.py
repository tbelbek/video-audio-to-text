import os
import queue  # Import queue module
import sqlite3
import threading
import time
import uuid
from datetime import datetime

import ffmpeg
import openai
import whisper
from dotenv import load_dotenv  # Import dotenv
from flask import (Flask, Response, redirect, render_template, request,
                   send_from_directory, url_for)

# Determine the script's directory
script_dir = os.path.dirname(os.path.abspath(__file__))

dotenv_path = os.path.join(script_dir, "import", ".env")
load_dotenv(dotenv_path)

# Define paths inside the 'import' folder
IMPORT_FOLDER = os.path.join(script_dir, "import")
UPLOAD_FOLDER = os.path.join(IMPORT_FOLDER, "uploads")
AUDIO_FOLDER = os.path.join(IMPORT_FOLDER, "audio")
TRANSCRIPTIONS_FOLDER = os.path.join(IMPORT_FOLDER, "transcriptions")
SUMMARIES_FOLDER = os.path.join(IMPORT_FOLDER, "summaries")
DB_PATH = os.path.join(IMPORT_FOLDER, "transcriptions.db")

# Create folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)
os.makedirs(TRANSCRIPTIONS_FOLDER, exist_ok=True)
os.makedirs(SUMMARIES_FOLDER, exist_ok=True)

# Initialize SQLite database
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS transcriptions (
        id TEXT PRIMARY KEY,
        filename TEXT UNIQUE,
        title TEXT,
        transcription TEXT,
        summary TEXT
    )
""")
conn.commit()

# Set OpenAI API key from environment variable
openai.api_key = os.getenv('OPENAI_API_KEY')

# Initialize Whisper model
print("Loading Whisper model...")
model = whisper.load_model("base")
print("Model loaded.")

# Supported video extensions
video_extensions = ('.mkv', '.mp4', '.avi', '.mov', '.flv', '.wmv')

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['TRANSCRIPTIONS_FOLDER'] = TRANSCRIPTIONS_FOLDER

# Initialize transcription queue
transcription_queue = queue.Queue()

def transcribe_video(video_path):
    # Generate a unique identifier
    unique_id = uuid.uuid4().hex

    # Create unique audio and transcription filenames
    audio_filename = f"audio_{unique_id}.wav"
    transcript_filename = f"transcription_{unique_id}.txt"

    audio_path = os.path.join(AUDIO_FOLDER, audio_filename)
    ffmpeg.input(video_path).output(audio_path).run(overwrite_output=True)

    result = model.transcribe(audio_path)

    transcription = result["text"].strip()

    transcript_path = os.path.join(TRANSCRIPTIONS_FOLDER, transcript_filename)
    with open(transcript_path, "w", encoding="utf-8") as file:
        file.write(transcription)

    return transcript_path, unique_id, os.path.basename(video_path)

def summarize_transcription(transcription):
    try:
        response = openai.ChatCompletion.create(
            model="mini",
            messages=[
                {"role": "system", "content": "I would like for you to assume the role of a court clerk"},
                {"role": "user", "content": f"""Generate a concise summary of the text below.
Text: {transcription}

Add a title to the summary.

Make sure your summary has useful and true information about the main points of the topic.
Begin with a short introduction explaining the topic. If you can, use bullet points to list important details,
and finish your summary with a concluding sentence."""},
            ],
            max_tokens=40,
            temperature=0.3,
        )
        summary = response.choices[0].message['content'].strip()
        return summary
    except Exception as e:
        print(f"Error during summarization: {e}")
        return "No Summary"

def worker():
    while True:
        video_path = transcription_queue.get()
        if video_path is None:
            break
        try:
            filename = os.path.basename(video_path)
            # Check if already transcribed
            cursor.execute("SELECT id FROM transcriptions WHERE filename = ?", (filename,))
            if cursor.fetchone():
                print(f"Skipping already transcribed video: {filename}")
                transcription_queue.task_done()
                continue

            print(f"Processing video: {filename}")

            transcript_path, unique_id, original_filename = transcribe_video(video_path)
            with open(transcript_path, 'r', encoding='utf-8') as f:
                transcription = f.read()

            print("Summarizing transcription...")
            summary = summarize_transcription(transcription)
            summary_filename = f"summary_{unique_id}.txt"
            summary_path = os.path.join(SUMMARIES_FOLDER, summary_filename)
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(summary)
            print("Summary created.")

            # Extract title from summary
            title = summary.split('\n')[0] if summary else "No Title"

            # Insert into SQLite database
            cursor.execute("""
                INSERT INTO transcriptions (id, filename, title, transcription, summary)
                VALUES (?, ?, ?, ?, ?)
            """, (unique_id, original_filename, title, transcription, summary))
            conn.commit()
            print("Data saved to database.")

        except Exception as e:
            print(f"Error processing {filename}: {e}")

        finally:
            # Optionally, remove the extracted audio file
            audio_filename = f"audio_{unique_id}.wav"
            audio_path = os.path.join(AUDIO_FOLDER, audio_filename)
            if os.path.exists(audio_path):
                os.remove(audio_path)
                print("Temporary audio file removed.\n")
            transcription_queue.task_done()

def batch_transcribe():
    while True:
        for filename in os.listdir(IMPORT_FOLDER):
            if filename.lower().endswith(video_extensions):
                video_path = os.path.join(IMPORT_FOLDER, filename)
                transcription_queue.put(video_path)
                print(f"Added to queue: {filename}")
        # Wait for 5 minutes before next check
        time.sleep(300)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        file = request.files.get('file')
        if file:
            # Generate a unique filename for the uploaded file
            unique_id = uuid.uuid4().hex
            original_filename = os.path.splitext(file.filename)[0]
            file_extension = os.path.splitext(file.filename)[1]
            unique_filename = f"{original_filename}_{unique_id}{file_extension}"
            filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
            file.save(filepath)

            transcription_queue.put(filepath)
            print(f"Uploaded and added to queue: {unique_filename}")

            return redirect(url_for('download_file', filename=unique_filename))
    return render_template('index.html')

@app.route('/transcriptions/<filename>')
def download_file(filename):
    return send_from_directory(TRANSCRIPTIONS_FOLDER, filename, as_attachment=True)

def get_transcriptions():
    cursor.execute("SELECT filename, title, transcription, summary FROM transcriptions ORDER BY ROWID DESC")
    rows = cursor.fetchall()
    return rows

def generate_rss(transcriptions):
    rss_items = ""
    for filename, title, transcription, summary in transcriptions:
        rss_items += f"""
        <item>
            <title>{title}</title>
            <description>{summary}</description>
            <link>http://localhost:5001/transcriptions/{filename}</link>
            <pubDate>{datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
        </item>
        """
    rss_feed = f"""<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
        <channel>
            <title>Video Transcriptions RSS Feed</title>
            <link>http://localhost:5001/</link>
            <description>RSS feed of video transcriptions and summaries.</description>
            {rss_items}
        </channel>
    </rss>"""
    return rss_feed

@app.route('/rss')
def rss():
    transcriptions = get_transcriptions()
    rss_feed = generate_rss(transcriptions)
    return Response(rss_feed, mimetype='application/rss+xml')

if __name__ == '__main__':
    # Start worker thread
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

    # Start batch transcription thread
    batch_thread = threading.Thread(target=batch_transcribe, daemon=True)
    batch_thread.start()

    # Run Flask app
    app.run(debug=True, port=5001)