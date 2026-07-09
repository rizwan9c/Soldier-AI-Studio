import gradio as ui
import requests
import io
import os
import zipfile
import asyncio
import edge_tts
import sqlite3
from datetime import datetime, timedelta
from PIL import Image
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# Database setup for Admin Panel & Users
DB_FILE = "users_database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            plan TEXT,
            expiry TEXT,
            status TEXT,
            today_count INTEGER,
            total_count INTEGER
        )
    ''')
    # Add a default admin user for testing if not exists
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('admin', 'admin123', 'Admin', 'Unlimited', 'Active', 0, 0)")
    conn.commit()
    conn.close()

# Initialize Database
init_db()

# Admin Functions
def add_new_user(username, password, plan):
    if not username or not password:
        return "Username and Password cannot be empty."
    expiry_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users VALUES (?, ?, ?, ?, 'Active', 0, 0)", (username, password, plan, expiry_date))
        conn.commit()
        conn.close()
        return f"User '{username}' added successfully under '{plan}' plan! Expires on {expiry_date}."
    except sqlite3.IntegrityError:
        return "Error: Username already exists."

def get_all_users_table():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, plan, expiry, today_count, total_count, status FROM users WHERE plan != 'Admin'")
    rows = cursor.fetchall()
    conn.close()
    return rows

# Core AI Models Configuration
API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"

def query_flux(prompt, width, height):
    payload = {"inputs": prompt, "parameters": {"width": width, "height": height}}
    response = requests.post(API_URL, json=payload)
    if response.status_code == 200: return response.content
    else: raise Exception("API Error")

def generate_single_image(prompt, size, style):
    final_prompt = f"{prompt}, {style}" if style and style != "Default" else prompt
    width, height = 1024, 1024
    if size == "Landscape / YouTube (1280x720)": width, height = 1280, 720
    elif size == "Portrait / Reels (720x1280)": width, height = 720, 1280
    try: return Image.open(io.BytesIO(query_flux(final_prompt, width, height)))
    except: return None

def generate_bulk_images(bulk_prompts_text, size, style):
    prompts = [p.strip() for p in bulk_prompts_text.split("\n") if p.strip()][:20]
    if not prompts: return None, "Please enter prompts."
    width, height = 1024, 1024
    if size == "Landscape / YouTube (1280x720)": width, height = 1280, 720
    elif size == "Portrait / Reels (720x1280)": width, height = 720, 1280
    zip_filename = "bulk_images.zip"
    with zipfile.ZipFile(zip_filename, 'w') as img_zip:
        for i, prompt in enumerate(prompts):
            try:
                img_bytes = query_flux(f"{prompt}, {style}", width, height)
                img_zip.writestr(f"image_{i+1}.jpg", img_bytes)
            except: continue
    return zip_filename, "Bulk generation complete."

async def generate_voice(text, voice_name, output_path):
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(output_path)

def create_video_from_script(script_text, size, style, language):
    lines = [line.strip() for line in script_text.split("\n") if line.strip()]
    if not lines: return None, "Please write script lines."
    width, height = 1024, 1024
    if size == "Landscape / YouTube (1280x720)": width, height = 1280, 720
    elif size == "Portrait / Reels (720x1280)": width, height = 720, 1280
    voice_map = {"Urdu (Pakistan) - Male": "ur-PK-AsadNeural", "English (US) - Male": "en-US-GuyNeural"}
    selected_voice = voice_map.get(language, "ur-PK-AsadNeural")
    video_clips = []
    full_text = " ".join(lines)
    audio_path = "temp_full_voice.mp3"
    asyncio.run(generate_voice(full_text, selected_voice, audio_path))
    try:
        audio_clip = AudioFileClip(audio_path)
        total_duration = audio_clip.duration
        duration_per_scene = total_duration / len(lines)
        for i, line in enumerate(lines):
            img_bytes = query_flux(f"{line}, {style}", width, height)
            img_path = f"temp_img_{i}.jpg"
            with open(img_path, "wb") as f: f.write(img_bytes)
            clip = ImageClip(img_path).set_duration(duration_per_scene)
            video_clips.append(clip)
        final_video = concatenate_videoclips(video_clips, method="compose")
        final_video = final_video.set_audio(audio_clip)
        output_video_path = "soldier_output_video.mp4"
        final_video.write_videofile(output_video_path, fps=24, codec="libx264", audio_codec="aac")
        for i in range(len(lines)):
            if os.path.exists(f"temp_img_{i}.jpg"): os.remove(f"temp_img_{i}.jpg")
        if os.path.exists(audio_path): os.remove(audio_path)
        return output_video_path, "Video created successfully!"
    except Exception as e: return None, f"Error: {str(e)}"

def voice_wrapper(text, language):
    audio_path = "generated_voice.mp3"
    voice_map = {"Urdu (Pakistan) - Male": "ur-PK-AsadNeural", "English (US) - Male": "en-US-GuyNeural"}
    asyncio.run(generate_voice(text, voice_map.get(language, "ur-PK-AsadNeural"), audio_path))
    return audio_path, "Voice ready."


# Web Interface Layout (UI)
with ui.Blocks(title="Soldier AI Studio") as demo:
    ui.Markdown("# Soldier AI Studio")
    
    with ui.Row():
        size_dropdown = ui.Dropdown(choices=["Square (1024x1024)", "Landscape / YouTube (1280x720)", "Portrait / Reels (720x1280)"], value="Square (1024x1024)", label="Select Aspect Ratio")
        style_dropdown = ui.Dropdown(choices=["Default", "cinematic, dramatic lighting, 4k", "realistic photo, high detail"], value="Default", label="Select Visual Style")

    with ui.Tabs():
        with ui.TabItem("Single Image Generator"):
            with ui.Row():
                with ui.Column():
                    prompt_input = ui.Textbox(label="Image Prompt", placeholder="Describe what you want...")
                    generate_btn = ui.Button("Generate Image", variant="primary")
                with ui.Column(): output_image = ui.Image(label="Output Result")
            generate_btn.click(fn=generate_single_image, inputs=[prompt_input, size_dropdown, style_dropdown], outputs=output_image)

        with ui.TabItem("✨ Bulk Images (Auto)"):
            with ui.Row():
                with ui.Column():
                    bulk_input = ui.TextArea(label="Enter Bulk Prompts", placeholder="One prompt per line...", lines=5)
                    bulk_generate_btn = ui.Button("Generate All", variant="primary")
                with ui.Column():
                    bulk_status = ui.Textbox(label="Status")
                    download_file = ui.File(label="Download ZIP")
            bulk_generate_btn.click(fn=generate_bulk_images, inputs=[bulk_input, size_dropdown, style_dropdown], outputs=[download_file, bulk_status])

        with ui.TabItem("🎙️ AI Voice Generator"):
            with ui.Row():
                with ui.Column():
                    script_input = ui.TextArea(label="Enter Script", lines=4)
                    lang_dropdown = ui.Dropdown(choices=["Urdu (Pakistan) - Male", "English (US) - Male"], value="Urdu (Pakistan) - Male", label="Voice Language")
                    voice_generate_btn = ui.Button("Generate Voice", variant="primary")
                with ui.Column():
                    voice_status = ui.Textbox(label="Status")
                    output_audio = ui.Audio(label="Play Audio", type="filepath")
            voice_generate_btn.click(fn=voice_wrapper, inputs=[script_input, lang_dropdown], outputs=[output_audio, voice_status])

        with ui.TabItem("🎬 Script to Video"):
            with ui.Row():
                with ui.Column():
                    video_script_input = ui.TextArea(label="Enter Video Script (Line by Line)", lines=5)
                    video_lang_dropdown = ui.Dropdown(choices=["Urdu (Pakistan) - Male", "English (US) - Male"], value="Urdu (Pakistan) - Male", label="Select Video Voice")
                    video_generate_btn = ui.Button("Create Video", variant="primary")
                with ui.Column():
                    video_status = ui.Textbox(label="Status")
                    output_video = ui.Video(label="Final Video Result")
            video_generate_btn.click(fn=create_video_from_script, inputs=[video_script_input, size_dropdown, style_dropdown, video_lang_dropdown], outputs=[output_video, video_status])

        # TAB 5: Soldier Admin Panel (NEW)
        with ui.TabItem("🛡️ Soldier Admin Panel"):
            ui.Markdown("### Create and Manage User Accounts")
            with ui.Row():
                with ui.Column():
                    ui.Markdown("#### ➕ Add New User")
                    new_user = ui.Textbox(label="New Username")
                    new_pass = ui.Textbox(label="New Password", type="password")
                    plan_type = ui.Dropdown(choices=["Basic", "Pro"], value="Basic", label="Select Plan")
                    add_user_btn = ui.Button("Create User", variant="primary")
                    admin_status = ui.Textbox(label="System Log", interactive=False)
                
                with ui.Column():
                    ui.Markdown("#### 👥 Active Users Database")
                    users_table = ui.Dataframe(
                        headers=["User", "Plan", "Expiry Date", "Today Usage", "Total Usage", "Status"],
                        datatype=["str", "str", "str", "int", "int", "str"],
                        value=get_all_users_table()
                    )
                    refresh_btn = ui.Button("Refresh User List")

            # Admin Button clicks
            add_user_btn.click(fn=add_new_user, inputs=[new_user, new_pass, plan_type], outputs=admin_status).then(
                fn=get_all_users_table, outputs=users_table
            )
            refresh_btn.click(fn=get_all_users_table, outputs=users_table)

if __name__ == "__main__":
    demo.launch()