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
            r = req.get(file_url, stream=True, timeout=30)
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
            # Reserve first 2s for title card, last 5s for CTA
            lyric_start_offset = 2.0
            lyric_end_offset = max(lyric_start_offset + len(lines) * 2, duration - 5.0)
            available = lyric_end_offset - lyric_start_offset
            time_per_line = available / len(lines)
            for i, line in enumerate(lines):
                f = write_txt(line)
                start = lyric_start_offset + i * time_per_line
                end = lyric_start_offset + (i + 1) * time_per_line
                lyric_files.append((f, start, end))

        # ── FFMPEG FILTER CHAIN ──────────────────────────────────────────
        filters = []

        # 1. Artist name — small, top center, subtle
        filters.append(
            f"drawtext=textfile='{artist_file}'"
            f":fontcolor=white@0.7:fontsize=22"
            f":x=(w-text_w)/2:y=50"
            f":borderw=2:bordercolor=black@0.9"
            f":expansion=none"
        )

        # 2. Song title — bold, just below artist
        filters.append(
            f"drawtext=textfile='{title_file}'"
            f":fontcolor=white:fontsize=48"
            f":x=(w-text_w)/2:y=85"
            f":borderw=4:bordercolor=black"
            f":shadowx=3:shadowy=3:shadowcolor=black@0.9"
            f":expansion=none"
        )

        # 3. Lyric lines — centered vertically, fade in/out feel via timing
        for (lfile, start, end) in lyric_files:
            filters.append(
                f"drawtext=textfile='{lfile}'"
                f":fontcolor=white:fontsize=26"
                f":x=(w-text_w)/2:y=(h*0.52)"
                f":borderw=3:bordercolor=black"
                f":shadowx=2:shadowy=2:shadowcolor=black@0.8"
                f":enable='between(t,{start:.2f},{end:.2f})'"
                f":expansion=none"
            )

        # 4. Scrolling hook — slow scroll, green, bottom of screen
        if hook_file:
            filters.append(
                f"drawtext=textfile='{hook_file}'"
                f":fontcolor=0x00FF7F:fontsize=22"
                f":y=h-55"
                f":x=w-18*t"
                f":borderw=2:bordercolor=black"
                f":shadowx=1:shadowy=1:shadowcolor=black@0.9"
                f":expansion=none"
            )

        # 5. Gold CTA — last 5 seconds, centered near bottom
        cta_file = write_txt("Stream now  link in bio")
        cta_start = max(0, duration - 5)
        filters.append(
            f"drawtext=textfile='{cta_file}'"
            f":fontcolor=0xFFD700:fontsize=30"
            f":x=(w-text_w)/2:y=h-120"
            f":borderw=3:bordercolor=black"
            f":shadowx=2:shadowy=2:shadowcolor=black@0.8"
            f":enable='between(t,{cta_start:.2f},{duration:.2f})'"
            f":expansion=none"
        )

        vf = ','.join(filters)

        # Output path
        video_path = tempfile.mktemp(suffix='.mp4')
        paths.append(video_path)

        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', 'color=c=0x0a0a0a:s=540x960:r=30',
            '-i', audio_tmp.name,
            '-map', '0:v', '-map', '1:a',
            '-shortest',
            '-threads', '1',
            '-vf', vf,
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '23',
            '-profile:v', 'high',
            '-level', '4.0',
            '-pix_fmt', 'yuv420p',
            '-r', '30',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-ac', '2',
            '-movflags', '+faststart',
            video_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({
                "error": "ffmpeg failed",
                "returncode": result.returncode,
                "stderr": result.stderr[-3000:]
            }), 500

        with open(video_path, 'rb') as f:
            video_bytes = f.read()

        if len(video_bytes) == 0:
            return jsonify({"error": "ffmpeg produced empty file"}), 500

        return send_file(
            io.BytesIO(video_bytes),
            mimetype='video/mp4',
            as_attachment=True,
            download_name=f'short_{uuid.uuid4().hex[:8]}.mp4'
        )

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

    finally:
        for p in paths:
            try:
                if p and os.path.exists(p):
                    os.unlink(p)
            except:
                pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
