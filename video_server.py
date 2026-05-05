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

def split_title(title, max_chars=25):
    """Split title into two lines at a word boundary near the middle."""
    words = title.split()
    best_split = 0
    best_diff = float('inf')
    for i in range(1, len(words)):
        line1 = ' '.join(words[:i])
        line2 = ' '.join(words[i:])
        diff = abs(len(line1) - len(line2))
        if diff < best_diff and len(line1) <= max_chars and len(line2) <= max_chars:
            best_diff = diff
            best_split = i
    if best_split == 0:
        # fallback: just split at max_chars
        line1 = title[:max_chars].rsplit(' ', 1)[0]
        line2 = title[len(line1):].strip()
    else:
        line1 = ' '.join(words[:best_split])
        line2 = ' '.join(words[best_split:])
    return line1, line2

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
        hook = request.form.get('hook', '')[:120]

        # Split title into two lines
        line1, line2 = split_title(title)

        # Save audio
        audio_tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        audio_file.save(audio_tmp.name)
        audio_tmp.close()
        paths.append(audio_tmp.name)

        # Save title line 1
        title1_tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        title1_tmp.write(line1)
        title1_tmp.close()
        paths.append(title1_tmp.name)

        # Save title line 2
        title2_tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        title2_tmp.write(line2)
        title2_tmp.close()
        paths.append(title2_tmp.name)

        # Save hook text
        hook_tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        hook_tmp.write(hook)
        hook_tmp.close()
        paths.append(hook_tmp.name)

        # Output path
        video_path = tempfile.mktemp(suffix='.mp4')
        paths.append(video_path)

        scroll_speed = 60

        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', 'color=c=0x0a0a0a:s=540x960:r=30',
            '-i', audio_tmp.name,
            '-map', '0:v', '-map', '1:a',
            '-shortest',
            '-threads', '1',
            '-vf', (
                # Title line 1 — static, centered, white, bold
                f"drawtext=textfile='{title1_tmp.name}'"
                f":fontcolor=white:fontsize=34"
                f":x=(w-text_w)/2:y=(h/2)-120"
                f":borderw=4:bordercolor=black"
                f":shadowx=2:shadowy=2:shadowcolor=black@0.8"
                f":expansion=none,"
                # Title line 2 — static, centered, white, bold
                f"drawtext=textfile='{title2_tmp.name}'"
                f":fontcolor=white:fontsize=34"
                f":x=(w-text_w)/2:y=(h/2)-70"
                f":borderw=4:bordercolor=black"
                f":shadowx=2:shadowy=2:shadowcolor=black@0.8"
                f":expansion=none,"
                # Scrolling hook — green ticker
                f"drawtext=textfile='{hook_tmp.name}'"
                f":fontcolor=0x00FF7F:fontsize=22"
                f":y=(h/2)+40"
                f":x=w-{scroll_speed}*t"
                f":borderw=2:bordercolor=black"
                f":shadowx=1:shadowy=1:shadowcolor=black@0.9"
                f":expansion=none"
            ),
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
