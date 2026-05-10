import os
import io
import uuid
import subprocess
import tempfile
import requests as req
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)

def sanitize(text):
    """Remove characters that break ffmpeg drawtext."""
    replacements = ["'", '"', ":", "%", "[", "]", ",", ";", "\\", "{", "}", "(", ")", "=", "&", "@", "#", "!", "?", "*"]
    for ch in replacements:
        text = text.replace(ch, "")
    return text.strip()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/debug', methods=['POST'])
def debug():
    return jsonify({
        "content_type": str(request.content_type),
        "files": list(request.files.keys()),
        "form": list(request.form.keys()),
        "has_audio": 'audio' in request.files
    })

@app.route('/create-short', methods=['POST'])
def create_short():
    paths = []
    try:
        audio_file = request.files.get('audio')
        file_url = request.form.get('file_url')

        if not audio_file and not file_url:
            return jsonify({
                "error": "audio file or file_url is required",
                "files": list(request.files.keys()),
                "content_type": str(request.content_type)
            }), 400

        title = sanitize(request.form.get('title', 'Unknown')[:80])
        artist = sanitize(request.form.get('artist', 'Isaiah Khan')[:80])
        hook = sanitize(request.form.get('hook', '')[:120])
        lyrics_raw = request.form.get('lyrics', '')

        # Parse lyrics lines
        if lyrics_raw:
            lines = [sanitize(l.strip()) for l in lyrics_raw.split('|') if l.strip()]
        else:
            lines = []

        # Save audio
        audio_tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        if file_url:
            r = req.get(file_url, stream=True)
            for chunk in r.iter_content(chunk_size=8192):
                audio_tmp.write(chunk)
        else:
            audio_file.save(audio_tmp.name)
        audio_tmp.close()
        paths.append(audio_tmp.name)

        # Get audio duration
        probe = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries',
            'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_tmp.name
        ], capture_output=True, text=True)
        duration = float(probe.stdout.strip()) if probe.stdout.strip() else 90.0

        # Write text files for drawtext
        def write_txt(content):
            tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
            tmp.write(content)
            tmp.close()
            paths.append(tmp.name)
            return tmp.name

        artist_file = write_txt(artist)
        title_file = write_txt(title)
        hook_file = write_txt(hook) if hook else None

        # Build lyric line text files and timing
        lyric_files = []
        if lines:
            time_per_line = duration / len(lines)
            for i, line in enumerate(lines):
                f = write_txt(line)
                lyric_files.append((f, i * time_per_line, (i + 1) * time_per_line))

        # Build ffmpeg filter
        filters = []

        # Artist name
        filters.append(
            f"drawtext=textfile='{artist_file}'"
            f":font
