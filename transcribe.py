import ffmpeg
import whisper

# Load the Whisper model
model = whisper.load_model("base")

# Path to the video file
video_path = r"C:\Users\a000020\Videos\2024-11-21 09-17-33.mkv"

# Extract audio from the video
audio_path = "audio.wav"
ffmpeg.input(video_path).output(audio_path).run()

# Transcribe the audio
result = model.transcribe(audio_path)

# Define silence threshold in seconds
silence_threshold = 1.0

# Initialize variables for paragraph formation
paragraphs = []
current_paragraph = []
previous_end = 0.0

for segment in result["segments"]:
    start = segment["start"]
    end = segment["end"]
    text = segment["text"].strip()
    
    # Check if the silence between segments exceeds the threshold
    if current_paragraph and (start - previous_end) > silence_threshold:
        paragraphs.append(' '.join(current_paragraph))
        current_paragraph = []
    
    current_paragraph.append(text)
    previous_end = end

# Add the last paragraph
if current_paragraph:
    paragraphs.append(' '.join(current_paragraph))

# Write the paragraphs to a text file
with open("transcription_paragraphs.txt", "w", encoding="utf-8") as file:
    for paragraph in paragraphs:
        file.write(paragraph + "\n\n")