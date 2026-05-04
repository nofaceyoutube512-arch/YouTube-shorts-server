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
        # Get audio file
        audio_file = request.files.get('audio')
        if not audio_file:
            return jsonify({"error": "audio file is required", "files": list(request.files.keys()), "content_type": str(request.content_type)}), 400

        title = request.form.get('title', 'AI Tips')[:60]
        hook = request.form.get('hook', '')[:80]

        # Save audio to temp file
        audio_tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        audio_file.save(audio_tmp.name)
        audio_tmp.close()
        paths.append(audio_tmp.name)

        # Save title to temp file
        title_tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        title_tmp.write(title)
        title_tmp.close()
        paths.append(title_tmp.name)

        # Save hook to temp file
        hook_tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        hook_tmp.write(hook)
        hook_tmp.close()
        paths.append(hook_tmp.name)

        # Output video path
        video_path = tempfile.mktemp(suffix='.mp4')
        paths.append(video_path)

        # Build video with FFmpeg
        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:r=30',
            '-i', audio_tmp.name,
            '-map', '0:v', '-map', '1:a',
            '-shortest',
            '-vf', (
                f"drawtext=textfile='{title_tmp.name}':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=700:borderw=3:bordercolor=black,"
                f"drawtext=textfile='{hook_tmp.name}':fontcolor=00ff00:fontsize=44:x=(w-text_w)/2:y=820:borderw=2:bordercolor=black"
            ),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '128k',
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

        # Read into memory and return
        with open(video_path, 'rb') as f:
            video_bytes = f.read()

        if len(video_bytes) == 0:
            return jsonify({"error": "ffmpeg produced empty file", "stderr": result.stderr[-2000:]}), 500

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
