import os
import uuid

import ffmpeg
import whisper

# Define paths
VIDEOS_FOLDER = r"C:\Users\a000020\Videos"
AUDIO_FOLDER = os.path.join(VIDEOS_FOLDER, "audio")
TRANSCRIPTIONS_FOLDER = os.path.join(VIDEOS_FOLDER, "transcriptions")

# Create folders if they don't exist
os.makedirs(AUDIO_FOLDER, exist_ok=True)
os.makedirs(TRANSCRIPTIONS_FOLDER, exist_ok=True)

# Initialize Whisper model
print("Loading Whisper model...")
model = whisper.load_model("base")
print("Model loaded.")

# Define silence threshold in seconds
silence_threshold = 1.0

# Supported video extensions
video_extensions = ('.mkv', '.mp4', '.avi', '.mov', '.flv', '.wmv')

# Iterate through all files in the Videos folder
for filename in os.listdir(VIDEOS_FOLDER):
    if filename.lower().endswith(video_extensions):
        video_path = os.path.join(VIDEOS_FOLDER, filename)
        unique_id = uuid.uuid4().hex
        audio_filename = f"audio_{unique_id}.wav"
        transcript_filename = f"{os.path.splitext(filename)[0]}_{unique_id}.txt"
        audio_path = os.path.join(AUDIO_FOLDER, audio_filename)
        transcript_path = os.path.join(TRANSCRIPTIONS_FOLDER, transcript_filename)
        
        try:
            print(f"Processing video: {filename}")
            
            # Extract audio
            ffmpeg.input(video_path).output(audio_path).run(overwrite_output=True)
            print("Audio extracted.")
            
            # Transcribe audio
            print("Transcribing audio...")
            result = model.transcribe(audio_path)
            print("Transcription completed.")
            
            # Write transcription to file
            with open(transcript_path, 'w', encoding='utf-8') as f:
                f.write(result['text'])
        
        except Exception as e:
            print(f"Error processing {filename}: {e}")
        
        finally:
            # Optionally, remove the extracted audio file
            if os.path.exists(audio_path):
                os.remove(audio_path)
                print("Temporary audio file removed.\n")