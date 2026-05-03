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
    tmp_audio_path = None
    tmp_video_path = None
    tmp_title_path = None
    tmp_hook_path = None

    try:
        if request.content_type and 'multipart/form-data' in request.content_type:
            title = request.form.get('title', 'AI Feature')
            hook = request.form.get('hook', '')
            audio_file = request.files.get('audio')
            if not audio_file:
                return jsonify({"error": "audio file is required"}), 400
            tmp_audio = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
            audio_file.save(tmp_audio.name)
            tmp_audio.close()
            tmp_audio_path = tmp_audio.name
        else:
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
            tmp_audio_path = tmp_audio.name

        # Write text to temp files to avoid special character escaping issues
        tmp_title = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        tmp_title.write(title[:60])
        tmp_title.close()
        tmp_title_path = tmp_title.name

        tmp_hook = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        tmp_hook.write(hook[:80])
        tmp_hook.close()
        tmp_hook_path = tmp_hook.name

        tmp_video_path = tempfile.mktemp(suffix='.mp4')

        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-i', tmp_audio_path,
            '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:r=30',
            '-shortest',
            '-vf', (
                f"drawtext=textfile='{tmp_title_path}'"
                f":fontcolor=white:fontsize=64"
                f":x=(w-text_w)/2:y=(h/2)-200"
                f":borderw=3:bordercolor=black,"
                f"drawtext=textfile='{tmp_hook_path}'"
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
            return jsonify({"error": "ffmpeg failed", "details": result.stderr[-2000:]}), 500

        return send_file(
            tmp_video_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=f'short_{uuid.uuid4().hex[:8]}.mp4'
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        for path in [tmp_audio_path, tmp_title_path, tmp_hook_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except:
                    pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
