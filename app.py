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

# Folders Reset
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
    return "News Server Live (Final v4)"

@app.route('/render', methods=['POST'])
def render_video():
    try:
        # Clear old files to prevent overflow
        for f in os.listdir(UPLOAD_FOLDER): os.remove(os.path.join(UPLOAD_FOLDER, f))
        for f in os.listdir(OUTPUT_FOLDER): os.remove(os.path.join(OUTPUT_FOLDER, f))

        data = request.json
        print("Starting Render...")

        # 1. Save Files
        main_audio = save_base64_file(data.get('audioData'), "audio")
        bg_music = save_base64_file(data.get('bgmData'), "bgm")
        logo = save_base64_file(data.get('logoData'), "logo")
        
        clips = data.get('clips', [])
        if not main_audio or not clips:
            return jsonify({"error": "No Audio or Images found"}), 400

        # 2. Build FFmpeg Command
        inputs = []
        filter_complex = []
        
        # Input 0: Main Audio
        inputs.extend(['-i', main_audio])
        input_count = 1
        
        visual_streams = []
        
        for i, clip in enumerate(clips):
            path = save_base64_file(clip.get('imageData'), f"img_{i}")
            dur = str(clip.get('duration', 5))
            
            # Input image looped
            inputs.extend(['-loop', '1', '-t', dur, '-i', path])
            
            # --- MAGIC FIX IS HERE ---
            # scale=...: fit image in 1280x720
            # pad=1280:720:-1:-1 : The -1:-1 tells FFmpeg to AUTO CENTER (No maths error)
            # format=yuv420p : Ensures correct color format
            filter_complex.append(
                f"[{input_count}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
                f"pad=1280:720:-1:-1:color=black,setsar=1,format=yuv420p[v{i}];"
            )
            visual_streams.append(f"[v{i}]")
            input_count += 1
            
        # Concat All Clips
        concat_str = "".join(visual_streams)
        filter_complex.append(f"{concat_str}concat=n={len(visual_streams)}:v=1:a=0[base];")
        last_vid = "[base]"

        # Add Logo (if exists)
        if logo:
            inputs.extend(['-i', logo])
            # Resize logo to 150px width
            filter_complex.append(f"[{input_count}:v]scale=150:-1[logo_s];")
            # Overlay at top-left
            filter_complex.append(f"{last_vid}[logo_s]overlay=20:20[vid_logo];")
            last_vid = "[vid_logo]"
            input_count += 1

        # Mix Audio (if bgm exists)
        last_aud = "[0:a]"
        if bg_music:
            inputs.extend(['-i', bg_music])
            # Voice=1.0 volume, BGM=0.1 volume
            filter_complex.append(f"[{input_count}:a]volume=0.1[bgm];[0:a][bgm]amix=inputs=2:duration=first[aud_mix];")
            last_aud = "[aud_mix]"

        output_file = os.path.join(OUTPUT_FOLDER, "final_hd.mp4")
        
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

        # Execute
        subprocess.run(cmd, check=True)
        print("Render Success!")

        return send_file(output_file, as_attachment=True, download_name="news_video.mp4")

    except subprocess.CalledProcessError as e:
        print(f"FFmpeg Error: {e}")
        return jsonify({"error": "Video Rendering Failed on Server"}), 500
    except Exception as e:
        print(f"General Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
