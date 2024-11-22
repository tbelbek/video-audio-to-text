# backend/transcriber.py

import logging
import os
import sqlite3
import sys
import threading
import time
import uuid

import ffmpeg
import torch
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from openai import OpenAI

# Determine the script's directory
script_dir = os.path.dirname(os.path.abspath(__file__))

# Load environment variables
dotenv_path = os.path.join(script_dir, "..", "import", ".env")
load_dotenv(dotenv_path)

# Define paths inside the 'import' folder
IMPORT_FOLDER = os.path.join(script_dir, "import")  # Removed leading '/'
UPLOAD_FOLDER = os.path.join(IMPORT_FOLDER, "uploads")
AUDIO_FOLDER = os.path.join(IMPORT_FOLDER, "audio")
TRANSCRIPTIONS_FOLDER = os.path.join(IMPORT_FOLDER, "transcriptions")
SUMMARIES_FOLDER = os.path.join(IMPORT_FOLDER, "summaries")
DB_PATH = os.path.join(IMPORT_FOLDER, "transcriptions.db")
MODEL_CACHE_DIR = os.getenv(IMPORT_FOLDER, "model_cache")  # Corrected getenv usage
LOGS_FOLDER = os.path.join(IMPORT_FOLDER, "logs")
LOG_FILE = os.path.join(LOGS_FOLDER, "transcriber.log")

# Create necessary folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # Ensure 'uploads' directory exists
os.makedirs(AUDIO_FOLDER, exist_ok=True)
os.makedirs(TRANSCRIPTIONS_FOLDER, exist_ok=True)
os.makedirs(SUMMARIES_FOLDER, exist_ok=True)
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

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    logging.error("OPENAI_API_KEY not found in environment variables.")
    sys.exit(1)

client = OpenAI(api_key=openai_api_key)

# Set OpenAI API key from environment variable
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),  # This is the default and can be omitted
)

device = "cuda" if torch.cuda.is_available() else "cpu"
compute_type = "float16" if device == "cuda" else "float32"
model = "large-v3-turbo"

# Initialize Faster Whisper model
logging.info("Loading Faster Whisper model...")
model = WhisperModel(
    model, device=device, compute_type=compute_type, download_root=MODEL_CACHE_DIR
)
logging.info(f"Model loaded on {device} with compute_type={compute_type}.")
logging.info(f"Model {model} loaded.")

# Supported video and audio extensions
video_extensions = (".mkv", ".mp4", ".avi", ".mov", ".flv", ".wmv")
audio_extensions = (".mp3", ".wav", ".aac", ".flac", ".ogg", ".wma", ".m4a")

# Semaphore to limit the number of concurrent workers to 2
max_workers = 2
worker_semaphore = threading.Semaphore(max_workers)

# Lock for thread-safe database access
db_lock = threading.Lock()


def transcribe_video(video_path):
    """
    Extracts audio from the video, transcribes it using Faster Whisper,
    and returns the path to the transcription file along with other details.
    """
    unique_id = uuid.uuid4().hex

    # Create unique audio and transcription filenames
    audio_filename = f"audio_{unique_id}.wav"
    transcript_filename = f"transcription_{unique_id}.txt"

    audio_path = os.path.join(AUDIO_FOLDER, audio_filename)
    ffmpeg.input(video_path).output(
        audio_path, format="wav", acodec="pcm_s16le", ac=1, ar="16k"
    ).run(overwrite_output=True)

    # Transcribe using faster-whisper
    segments, info = model.transcribe(audio_path, beam_size=5)

    # Concatenate all segment texts
    transcription = " ".join([segment.text for segment in segments]).strip()

    transcript_path = os.path.join(TRANSCRIPTIONS_FOLDER, transcript_filename)
    with open(transcript_path, "w", encoding="utf-8") as file:
        file.write(transcription)

    return transcript_path, unique_id, os.path.basename(video_path)


def summarize_transcription(transcription):
    """
    Generates a summary of the transcription using OpenAI's GPT model.
    """
    if not transcription:
        logging.warning("Empty transcription received for summarization.")
        return "No Summary"

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Corrected model name
            messages=[
                {
                    "role": "system",
                    "content": "I would like for you to assume the role of a court clerk.",
                },
                {
                    "role": "user",
                    "content": f"""Generate a concise summary of the text below.
                    Text: {transcription}

                    Add a title to the summary.

                    Make sure your summary has useful and true information about the main points of the topic. Begin with a short introduction explaining the topic. If you can, use bullet points to list important details, and finish your summary with a concluding sentence. Return the summary in an html article format.Remove all markdown or unrelated to the summary content.""",
                },
            ],
            max_tokens=400,  # Adjust as needed
            temperature=0.3,  # Adjust for variability in responses
        )
        summary = response.choices[0].message.content.strip()
        return summary
    except Exception as e:
        logging.exception("Error during summarization:")
        return "No Summary"


def process_transcription(transcription_id, video_path, unique_id):
    """
    Processes the transcription: transcribe the video, summarize the transcription,
    and update the database accordingly.
    """
    try:
        filename = os.path.basename(video_path)

        logging.info(f"[Worker] Processing video: {filename}")

        # Transcribe the video
        transcript_path, unique_id, original_filename = transcribe_video(video_path)
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcription = f.read()

        logging.info("[Worker] Summarizing transcription...")
        summary = summarize_transcription(transcription)
        summary_filename = f"summary_{unique_id}.txt"
        summary_path = os.path.join(SUMMARIES_FOLDER, summary_filename)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary)
        logging.info("[Worker] Summary created.")

        # Extract title from summary
        title = summary.split("\n")[0] if summary else "No Title"

        # Update the transcription entry in the database
        with db_lock:
            cursor.execute(
                """
                UPDATE transcriptions
                SET title = ?, transcription = ?, summary = ?, status = 'completed'
                WHERE id = ?
                """,
                (title, transcription, summary, transcription_id),
            )
            conn.commit()
        logging.info("[Worker] Data saved to database.")

    except Exception as e:
        logging.error(f"[Worker] Error processing {filename}: {e}")
        # Update status to 'failed'
        with db_lock:
            cursor.execute(
                "UPDATE transcriptions SET status = 'failed' WHERE id = ?",
                (transcription_id,),
            )
            conn.commit()
    finally:
        # Optionally, remove the extracted audio file
        audio_filename = f"audio_{unique_id}.wav"
        audio_path = os.path.join(AUDIO_FOLDER, audio_filename)
        if os.path.exists(audio_path):
            os.remove(audio_path)
            logging.info("[Worker] Temporary audio file removed.\n")
        
        # Optionally, remove the original video file
        video_filename = os.path.basename(video_path)
        video_path_full = os.path.join(UPLOAD_FOLDER, video_filename)
        if os.path.exists(video_path_full):
            os.remove(video_path_full)
            logging.info("[Worker] Uploaded video file removed.\n")
            
        # Release the semaphore to allow new workers
        worker_semaphore.release()


def main():
    """
    Main loop that continuously checks the database for pending transcriptions
    and starts a new thread for each pending file, limited to 2 concurrent threads.
    """
    while True:
        with db_lock:
            # Fetch one transcription with 'pending' status
            cursor.execute(
                "SELECT id, filename FROM transcriptions WHERE status = 'pending' LIMIT 1"
            )
            pending_transcription = cursor.fetchone()

        if pending_transcription:
            transcription_id, filename = pending_transcription
            filepath = os.path.join(UPLOAD_FOLDER, filename)

            if not os.path.exists(filepath):
                logging.warning(f"File not found: {filepath}")
                with db_lock:
                    # Update status to 'failed' if file does not exist
                    cursor.execute(
                        "UPDATE transcriptions SET status = 'failed' WHERE id = ?",
                        (transcription_id,),
                    )
                    conn.commit()
                continue

            # Acquire semaphore before starting a new worker
            worker_semaphore.acquire()

            # Retrieve unique_id for cleanup in worker
            unique_id = uuid.uuid4().hex

            # Update status to 'processing'
            with db_lock:
                cursor.execute(
                    "UPDATE transcriptions SET status = 'processing' WHERE id = ?",
                    (transcription_id,),
                )
                conn.commit()
                logging.info(f"Added to queue: {filename}")

            # Start a new worker thread
            worker_thread = threading.Thread(
                target=process_transcription,
                args=(transcription_id, filepath, unique_id),
                daemon=True,
            )
            worker_thread.start()
        else:
            # No pending transcriptions found
            time.sleep(5)  # Wait before checking again

def reset_processing_transcriptions(cursor, conn):
    """
    Resets any transcriptions marked as 'processing' to 'pending' to ensure they are reprocessed.
    """
    try:
        # Fetch all transcriptions with status 'processing'
        cursor.execute("SELECT id, filename FROM transcriptions WHERE status = 'processing'")
        processing_transcriptions = cursor.fetchall()

        if processing_transcriptions:
            logging.info(f"Found {len(processing_transcriptions)} transcription(s) in 'processing' state. Resetting to 'pending'.")
            for transcription in processing_transcriptions:
                transcription_id, filename = transcription
                cursor.execute("UPDATE transcriptions SET status = 'pending' WHERE id = ?", (transcription_id,))
                logging.info(f"Resetting transcription ID: {transcription_id}, Filename: {filename} to 'pending'.")
            conn.commit()
            logging.info("All 'processing' transcriptions have been reset to 'pending'.")
        else:
            logging.info("No transcriptions found in 'processing' state.")
    except Exception as e:
        logging.error(f"Error resetting 'processing' transcriptions: {e}")

if __name__ == "__main__":
    NUM_WORKERS = 2  # Maximum number of concurrent workers

    logging.info(f"Starting transcription service with max {NUM_WORKERS} workers.")

    # Initialize database connection
    script_dir = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(script_dir, "import", "transcriptions.db")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    # Reset any transcriptions left in 'processing' state
    reset_processing_transcriptions(cursor, conn)

    # Start the main loop in a separate thread to keep the main thread free
    main_thread = threading.Thread(target=main, daemon=True)
    main_thread.start()
    logging.info("Main transcription thread started.")

    # Keep the main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logging.info("Shutting down transcription service.")