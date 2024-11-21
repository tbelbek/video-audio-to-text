import os
import uuid

import ffmpeg
import whisper
from flask import (Flask, redirect, render_template, request,
                   send_from_directory, url_for)

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
TRANSCRIPTIONS_FOLDER = 'transcriptions'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TRANSCRIPTIONS_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['TRANSCRIPTIONS_FOLDER'] = TRANSCRIPTIONS_FOLDER

def transcribe_video(video_path, silence_threshold):
    model = whisper.load_model("base")
    
    # Generate a unique identifier
    unique_id = uuid.uuid4().hex
    
    # Create unique audio and transcription filenames
    audio_filename = f"audio_{unique_id}.wav"
    transcript_filename = f"transcription_{unique_id}.txt"
    
    audio_path = os.path.join(app.config['UPLOAD_FOLDER'], audio_filename)
    ffmpeg.input(video_path).output(audio_path).run()
    
    result = model.transcribe(audio_path)
    
    paragraphs = []
    current_paragraph = []
    previous_end = 0.0

    for segment in result["segments"]:
        start = segment["start"]
        end = segment["end"]
        text = segment["text"].strip()

        if current_paragraph and (start - previous_end) > silence_threshold:
            paragraphs.append(' '.join(current_paragraph))
            current_paragraph = []

        current_paragraph.append(text)
        previous_end = end

    if current_paragraph:
        paragraphs.append(' '.join(current_paragraph))

    transcript_path = os.path.join(app.config['TRANSCRIPTIONS_FOLDER'], transcript_filename)
    with open(transcript_path, "w", encoding="utf-8") as file:
        for paragraph in paragraphs:
            file.write(paragraph + "\n\n")
    
    return transcript_path

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        file = request.files.get('file')
        threshold = request.form.get('threshold', '1.0')
        try:
            silence_threshold = float(threshold)
        except ValueError:
            return render_template('index.html', error="Silence threshold must be a number.")
        
        if file:
            # Generate a unique filename for the uploaded file
            unique_id = uuid.uuid4().hex
            original_filename = os.path.splitext(file.filename)[0]
            file_extension = os.path.splitext(file.filename)[1]
            unique_filename = f"{original_filename}_{unique_id}{file_extension}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)
            
            transcript_path = transcribe_video(filepath, silence_threshold)
            filename = os.path.basename(transcript_path)
            return redirect(url_for('download_file', filename=filename))
    return render_template('index.html')

@app.route('/transcriptions/<filename>')
def download_file(filename):
    return send_from_directory(app.config['TRANSCRIPTIONS_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5001)