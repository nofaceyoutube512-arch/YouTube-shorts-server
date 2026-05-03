import os
import uuid
import subprocess
import tempfile
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/create-short', methods=['POST'])
def create_short():
    tmp_audio = None
    tmp_video = None

    try:
        title = None
        hook = None

        # Support both multipart (binary audio) and JSON (audio_url)
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Binary audio uploaded directly from Make
            title = request.form.get('title', 'AI Feature')
            hook = request.form.get('hook', '')
            audio_file = request.files.get('audio')
            if not audio_file:
                return jsonify({"error": "audio file is required"}), 400

            tmp_audio = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
            audio_file.save(tmp_audio.name)
            tmp_audio.close()
            audio_path = tmp_audio.name

        else:
            # JSON body with audio_url
            data = request.get_json(force=True)
            if not data:
                return jsonify({"error": "invalid request body"}), 400

            title = data.get('title', 'AI Feature')
            hook = data.get('hook', '')
            audio_url = data.get('audio_url')

            if not audio_url:
                return jsonify({"error": "audio_url is required"}), 400

            import urllib.request
            tmp_audio = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
            tmp_audio.close()
            urllib.request.urlretrieve(audio_url, tmp_audio.name)
            audio_path = tmp_audio.name

        # Generate output video path
        tmp_video_path = tempfile.mktemp(suffix='.mp4')

        # Sanitize text for ffmpeg drawtext
        def esc(text):
            return text.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")

        title_safe = esc(title[:60])
        hook_safe = esc(hook[:80])

        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-i', audio_path,
            '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:r=30',
            '-shortest',
            '-vf', (
                f"drawtext=text='{title_safe}'"
                f":fontcolor=white:fontsize=64"
                f":x=(w-text_w)/2:y=(h/2)-200"
                f":borderw=3:bordercolor=black,"
                f"drawtext=text='{hook_safe}'"
                f":fontcolor=0x00FF00:fontsize=48"
                f":x=(w-text_w)/2:y=(h/2)+50"
                f":borderw=2:bordercolor=black"
            ),
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            tmp_video_path
        ]

        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({"error": "ffmpeg failed", "details": result.stderr}), 500

        return send_file(
            tmp_video_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=f'short_{uuid.uuid4().hex[:8]}.mp4'
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if tmp_audio and os.path.exists(tmp_audio.name):
            os.unlink(tmp_audio.name)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
