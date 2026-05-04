import os
import io
import uuid
import subprocess
import tempfile
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
        if not audio_file:
            return jsonify({
                "error": "audio file is required",
                "files": list(request.files.keys()),
                "content_type": str(request.content_type)
            }), 400

        title = request.form.get('title', 'AI Tips')[:80]
        hook = request.form.get('hook', '')[:100]

        # Save audio
        audio_tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        audio_file.save(audio_tmp.name)
        audio_tmp.close()
        paths.append(audio_tmp.name)

        # Save title text
        title_tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        title_tmp.write(title)
        title_tmp.close()
        paths.append(title_tmp.name)

        # Save hook text
        hook_tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        hook_tmp.write(hook)
        hook_tmp.close()
        paths.append(hook_tmp.name)

        # Output path
        video_path = tempfile.mktemp(suffix='.mp4')
        paths.append(video_path)

        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', 'color=c=black:s=540x960:r=24',
            '-i', audio_tmp.name,
            '-map', '0:v', '-map', '1:a',
            '-shortest',
            '-threads', '1',
            '-vf', (
                # Title: white, smaller font, word wrap at 480px wide
                f"drawtext=textfile='{title_tmp.name}'"
                f":fontcolor=white"
                f":fontsize=24"
                f":x=30"
                f":y=300"
                f":borderw=2"
                f":bordercolor=black"
                f":line_spacing=8"
                f":expansion=none,"
                # Hook: green, smaller font, below title
                f"drawtext=textfile='{hook_tmp.name}'"
                f":fontcolor=00ff00"
                f":fontsize=20"
                f":x=30"
                f":y=390"
                f":borderw=2"
                f":bordercolor=black"
                f":line_spacing=6"
                f":expansion=none"
            ),
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-c:a', 'aac',
            '-b:a', '96k',
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
