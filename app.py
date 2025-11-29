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

# Clean start
if os.path.exists(UPLOAD_FOLDER): shutil.rmtree(UPLOAD_FOLDER)
if os.path.exists(OUTPUT_FOLDER): shutil.rmtree(OUTPUT_FOLDER)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def save_base64_file(data, prefix):
    if not data: return None
    try:
        if "," in data:
            header, encoded = data.split(",", 1)
        else:
            encoded = data
            
        ext = "bin"
        if "image" in str(data)[:30]: ext = "jpg"
        elif "audio" in str(data)[:30]: ext = "mp3"
        elif "video" in str(data)[:30]: ext = "mp4"
        
        file_data = base64.b64decode(encoded)
        filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        with open(filepath, "wb") as f:
            f.write(file_data)
        return filepath
    except Exception as e:
        print(f"File Save Error: {str(e)}")
        return None

@app.route('/', methods=['GET'])
def home():
    return "News Video Server is Running!"

@app.route('/render', methods=['POST'])
def render_video():
    try:
        # Cleanup old files
        for f in os.listdir(UPLOAD_FOLDER): os.remove(os.path.join(UPLOAD_FOLDER, f))
        for f in os.listdir(OUTPUT_FOLDER): os.remove(os.path.join(OUTPUT_FOLDER, f))

        data = request.json
        print("Processing Request...")

        # 1. Save Assets
        main_audio = save_base64_file(data.get('audioData'), "audio")
        bg_music = save_base64_file(data.get('bgmData'), "bgm")
        logo = save_base64_file(data.get('logoData'), "logo")
        
        clips = data.get('clips', [])
        if not main_audio or not clips:
            return jsonify({"error": "Audio and Images required"}), 400

        # 2. Build Command
        inputs = []
        filter_complex = []
        
        # Audio Input [0]
        inputs.extend(['-i', main_audio])
        input_count = 1
        
        visual_streams = []
        
        for i, clip in enumerate(clips):
            path = save_base64_file(clip.get('imageData'), f"img_{i}")
            dur = str(clip.get('duration', 5))
            
            # Loop image for duration
            inputs.extend(['-loop', '1', '-t', dur, '-i', path])
            
            # CRITICAL FIX: format=yuv420p added to ensure compatibility
            filter_complex.append(
                f"[{input_count}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
                f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}];"
            )
            visual_streams.append(f"[v{i}]")
            input_count += 1
            
        # Concat
        concat_str = "".join(visual_streams)
        filter_complex.append(f"{concat_str}concat=n={len(visual_streams)}:v=1:a=0[base];")
        last_vid = "[base]"

        # Logo
        if logo:
            inputs.extend(['-i', logo])
            filter_complex.append(f"[{input_count}:v]scale=120:-1[logo_s];")
            filter_complex.append(f"{last_vid}[logo_s]overlay=20:20[vid_logo];")
            last_vid = "[vid_logo]"
            input_count += 1

        # Audio Mix
        last_aud = "[0:a]"
        if bg_music:
            inputs.extend(['-i', bg_music])
            filter_complex.append(f"[{input_count}:a]volume=0.1[bgm];[0:a][bgm]amix=inputs=2:duration=first[aud_mix];")
            last_aud = "[aud_mix]"

        output_file = os.path.join(OUTPUT_FOLDER, "final.mp4")
        
        cmd = [
            'ffmpeg', '-y',
            *inputs,
            '-filter_complex', "".join(filter_complex),
            '-map', last_vid,
            '-map', last_aud,
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-shortest',
            output_file
        ]

        # Run command and CAPTURE ERROR if fails
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print("FFmpeg Error:", result.stderr)
            return jsonify({"error": f"FFmpeg Failed: {result.stderr[-200:]}"}), 500

        return send_file(output_file, as_attachment=True, download_name="video.mp4")

    except Exception as e:
        print(f"Server Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
