import os
import io
import uuid
import subprocess
import tempfile
import requests as req
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)

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

        title = request.form.get('title', 'Unknown')[:80]
        artist = request.form.get('artist', 'Isaiah Khan')[:80]
        hook = request.form.get('hook', '')[:120]
        lyrics_raw = request.form.get('lyrics', '')

        # Parse lyrics lines
        if lyrics_raw:
            lines = [l.strip() for l in lyrics_raw.split('|') if l.strip()]
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

        # Build drawtext filters
        filters = []

        # Artist name — top, small, always visible
        filters.append(
            f"drawtext=text='{artist}'"
            f":fontcolor=white@0.6:fontsize=20"
            f":x=(w-text_w)/2:y=60"
            f":borderw=2:bordercolor=black@0.8"
            f":expansion=none"
        )

        # Song title — below artist, always visible
        safe_title = title.replace("'", "\\'")
        filters.append(
            f"drawtext=text='{safe_title}'"
            f":fontcolor=white:fontsize=32"
            f":x=(w-text_w)/2:y=100"
            f":borderw=3:bordercolor=black"
            f":expansion=none"
        )

        # Lyric lines — timed, centered, large
        if lines:
            time_per_line = duration / len(lines)
            for i, line in enumerate(lines):
                start = i * time_per_line
                end = start + time_per_line
                safe_line = line.replace("'", "\\'").replace(":", "\\:")
                filters.append(
                    f"drawtext=text='{safe_line}'"
                    f":fontcolor=white:fontsize=38"
                    f":x=(w-text_w)/2:y=(h/2)-20"
                    f":borderw=4:bordercolor=black"
                    f":shadowx=2:shadowy=2:shadowcolor=black@0.8"
                    f":enable='between(t,{start:.2f},{end:.2f})'"
                    f":expansion=none"
                )

        # Scrolling hook at bottom
        if hook:
            safe_hook = hook.replace("'", "\\'")
            filters.append(
                f"drawtext=text='{safe_hook}'"
                f":fontcolor=0x00FF7F:fontsize=22"
                f":y=h-80"
                f":x=w-60*t"
                f":borderw=2:bordercolor=black"
                f":shadowx=1:shadowy=1:shadowcolor=black@0.9"
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
