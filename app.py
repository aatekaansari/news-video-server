import os
import base64
import subprocess
import uuid
import shutil
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = '/tmp'
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'outputs')

# Reset folders on every request (Render free tier के लिए जरूरी)
if os.path.exists(UPLOAD_FOLDER):
    shutil.rmtree(UPLOAD_FOLDER)
if os.path.exists(OUTPUT_FOLDER):
    shutil.rmtree(OUTPUT_FOLDER)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def save_base64_file(data, prefix):
    if not data:
        return None
    try:
        if "," in data:
            header, encoded = data.split(",", 1)
        else:
            encoded = data

        # Extension detect
        ext = "jpg"
        if data.startswith("data:audio"):
            ext = "mp3"
        elif data.startswith("data:video"):
            ext = "mp4")

        file_data = base64.b64decode(encoded)
        if len(file_data) == 0:
            return None

        filename = f"{prefix}_{uuid.uuid4().hex[:10]}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        with open(filepath, "wb") as f:
            f.write(file_data)
        return filepath
    except Exception as e:
        print(f"File Save Error: {str(e)}")
        return None


@app.route('/', methods=['GET'])
def home():
    return "News Server Live (V7 – Fully Fixed Audio + Image)"


@app.route('/render', methods=['POST'])
def render_video():
    try:
        # Cleanup old files
        for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
            if os.path.exists(folder):
                shutil.rmtree(folder)
            os.makedirs(folder, exist_ok=True)

        data = request.json

        main_audio = save_base64_file(data.get('audioData'), "audio")
        bg_music = save_base64_file(data.get('bgmData'), "bgm")
        logo = save_base64_file(data.get('logoData'), "logo")
        clips = data.get('clips', [])

        if not main_audio or not clips:
            return jsonify({"error": "Audio ya images missing hain"}), 400

        # FFmpeg command parts
        inputs = []
        filter_complex = []
        input_index = 0

        # 0: Main Audio
        inputs += ['-i', main_audio]
        input_index += 1

        # Images (loop + duration)
        video_filters = []
        for i, clip in enumerate(clips):
            img_path = save_base64_file(clip.get('imageData'), f"img_{i}")
            if not img_path:
                continue
            dur = str(clip.get('duration', 5))

            inputs += ['-loop', '1', '-t', dur, '-i', img_path]
            v_idx = input_index
            input_index += 1

            video_filters.append(
                f"[{v_idx}:v]scale=1280:720:force_original_aspect_ratio=increase,"
                f"crop=1280:720,format=yuv420p[v{i}];"
            )

        # Concat all images
        concat_parts = "".join(f"[v{i}]" for i in range(len(video_filters)))
        video_filters.append(f"{concat_parts}concat=n={len(video_filters)}:v=1:a=0[vidbase];")
        last_video = "[vidbase]"

        # Logo overlay
        if logo:
            inputs += ['-i', logo]
            filter_complex.append(f"[{input_index}:v]scale=150:-1[logo];")
            filter_complex.append(f"{last_video}[logo]overlay=20:20[vidout];")
            last_video = "[vidout]"
            input_index += 1

        else:
            filter_complex.append(f"{last_video}[vidout];")
            last_video = "[vidout]"

        # Audio mixing
        if bg_music:
            inputs += ['-i', bg_music]
            filter_complex.append(f"[{input_index}:a]volume=0.15[bgm];")
            filter_complex.append(f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[audout];")
            final_audio_map = "[audout]"
        else:
            final_audio_map = "[0:a]"

        # Full filter
        filter_complex.extend(video_filters)
        filter_complex_str = "".join(filter_complex)

        output_path = os.path.join(OUTPUT_FOLDER, "final_hd.mp4")

        cmd = [
            'ffmpeg', '-y',
            *inputs,
            '-filter_complex', filter_complex_str,
            '-map', last_video,
            '-map', final_audio_map,
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-crf', '18',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            '-shortest',
            output_path
        ]

        print("Running FFmpeg:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            print("FFmpeg Error:", result.stderr)
            return jsonify({"error": "FFmpeg failed", "details": result.stderr}), 500

        return send_file(output_path, as_attachment=True, download_name="News_Video_HD.mp4")

    except Exception as e:
        print("Server Error:", str(e))
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
