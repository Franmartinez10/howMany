import os
import re
import math
import torch
import requests
import threading
import queue
from TTS.api import TTS
from moviepy.editor import (ImageClip, VideoFileClip, CompositeVideoClip, TextClip, 
                            AudioFileClip, concatenate_audioclips, concatenate_videoclips, CompositeAudioClip)
import tkinter as tk
from tkinter import (Tk, Label, Entry, Button, Text, filedialog, END, messagebox,
                     Frame, Canvas, Scrollbar)
from tkinter import ttk
from tkinter.simpledialog import askstring
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageColor
from io import BytesIO
from pytube import YouTube  # Para descargar videos de YouTube
import tkinter.font as tkfont

# Forzar el uso de ImageMagick en MoviePy
os.environ["IMAGEMAGICK_BINARY"] = "magick"

# Configuración de API
PEXELS_API_KEY = "XXX"
PIXABAY_API_KEY = "XXXX-XXXX"

# Cola de procesamiento y lista de tareas
processing_queue = queue.Queue()
tasks_list = []

#############################################
# FUNCIONES PARA MANIPULACIÓN DE LISTAS (Add/Remove/Move)
#############################################
def add_video(src_listbox, dest_listbox):
    selected = src_listbox.curselection()
    if selected:
        item = src_listbox.get(selected[0])
        dest_listbox.insert(tk.END, item)

def remove_video(listbox):
    selected = listbox.curselection()
    if selected:
        listbox.delete(selected[0])

def move_up(listbox):
    selected = listbox.curselection()
    if selected and selected[0] > 0:
        index = selected[0]
        text = listbox.get(index)
        listbox.delete(index)
        listbox.insert(index-1, text)
        listbox.selection_set(index-1)

def move_down(listbox):
    selected = listbox.curselection()
    if selected and selected[0] < listbox.size()-1:
        index = selected[0]
        text = listbox.get(index)
        listbox.delete(index)
        listbox.insert(index+1, text)
        listbox.selection_set(index+1)

#############################################
# Visual Loader: ventana modal con progress bar
#############################################
def show_loader(message="Procesando..."):
    loader_win = tk.Toplevel(gui_root)
    loader_win.title("Cargando")
    loader_win.geometry("300x100")
    loader_label = Label(loader_win, text=message, font=("Arial", 12))
    loader_label.pack(pady=10)
    pb = ttk.Progressbar(loader_win, mode="indeterminate")
    pb.pack(pady=10, padx=10, fill="x")
    pb.start(10)
    loader_win.transient(gui_root)
    loader_win.grab_set()
    gui_root.update_idletasks()
    return loader_win

#############################################
# ÁREA SCROLLABLE
#############################################
def create_scrollable_frame(parent):
    canvas = Canvas(parent)
    scrollbar = Scrollbar(parent, orient="vertical", command=canvas.yview)
    scrollable_frame = Frame(canvas)
    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    return scrollable_frame

#############################################
# FUNCIONES AUXILIARES COMUNES
#############################################
def update_thumbnail(file_path, thumbnail_label):
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in [".mp4", ".mov", ".avi", ".mkv"]:
            clip = VideoFileClip(file_path)
            t = 1 if clip.duration > 1 else 0
            frame = clip.get_frame(t)
            im = Image.fromarray(frame)
        else:
            im = Image.open(file_path)
        im.thumbnail((200, 150))
        photo = ImageTk.PhotoImage(im)
        thumbnail_label.config(image=photo)
        thumbnail_label.image = photo
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo generar la miniatura: {str(e)}")

def select_bg(bg_var, bg_label, preview_thumbnail):
    filename = filedialog.askopenfilename(
        title="Selecciona una imagen o video de fondo",
        filetypes=[("Media Files", "*.jpg *.jpeg *.png *.mp4 *.mov *.avi *.mkv")]
    )
    if filename:
        bg_var.set(filename)
        bg_label.set(os.path.basename(filename))
        try:
            ext = os.path.splitext(filename)[1].lower()
            if ext in [".mp4", ".mov", ".avi", ".mkv"]:
                clip = VideoFileClip(filename)
                t = 1 if clip.duration > 1 else 0
                frame = clip.get_frame(t)
                im = Image.fromarray(frame)
            else:
                im = Image.open(filename)
            im.thumbnail((200, 150))
            photo = ImageTk.PhotoImage(im)
            preview_thumbnail.config(image=photo)
            preview_thumbnail.image = photo
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar la miniatura del fondo: {str(e)}")

def select_cover_file(cover_path, cover_label, cover_thumbnail_label):
    filename = filedialog.askopenfilename(
        title="Selecciona una imagen o video",
        filetypes=[("Media Files", "*.jpg *.jpeg *.png *.mp4 *.mov *.avi *.mkv")]
    )
    if filename:
        cover_path.set(filename)
        cover_label.config(text=os.path.basename(filename))
        try:
            ext = os.path.splitext(filename)[1].lower()
            if ext in [".mp4", ".mov", ".avi", ".mkv"]:
                clip = VideoFileClip(filename)
                t = 1 if clip.duration > 1 else 0
                frame = clip.get_frame(t)
                im = Image.fromarray(frame)
            else:
                im = Image.open(filename)
            im.thumbnail((400, 300))
            photo = ImageTk.PhotoImage(im)
            cover_thumbnail_label.config(image=photo)
            cover_thumbnail_label.image = photo
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar la miniatura: {str(e)}")

def select_voice_sample(voice_var, voice_label):
    filename = filedialog.askopenfilename(
        title="Selecciona un sample de voz",
        initialdir="/Users/framartinez/examples",  # Ajusta esta ruta según corresponda
        filetypes=[("Audio Files", "*.mp3 *.wav *.ogg")]
    )
    if filename:
        voice_var.set(filename)
        voice_label.config(text=os.path.basename(filename))

#############################################
# FUNCIONES PARA "CREAR CARÁTULAS" CON EDITOR EXTENDIDO
#############################################
def generate_cover_with_text(file_path, cover_text, border_width=2, border_color="black"):
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".mp4", ".mov", ".avi", ".mkv"]:
            clip = VideoFileClip(file_path)
            t = 1 if clip.duration > 1 else 0
            frame = clip.get_frame(t)
            base_im = Image.fromarray(frame).convert("RGBA")
        else:
            base_im = Image.open(file_path).convert("RGBA")
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo abrir el archivo: {str(e)}")
        return None

    try:
        custom_font_size = int(font_size_var.get())
    except:
        custom_font_size = int(base_im.width * 0.08)
    try:
        font_path = font_type_var.get() or "Impact.ttf"
        font = ImageFont.truetype(font_path, custom_font_size)
    except Exception:
        font = ImageFont.load_default()

    color_default = font_color_var.get().split(",")[0].strip()
    try:
        colors_input = colors_var.get().strip()
    except Exception as e:
        colors_input = ""
    if colors_input:
        colors_list = [c.strip() for c in colors_input.split(",")]
    else:
        colors_list = []

    lines = cover_text.splitlines()
    try:
        line_spacing = int(interlineado_var.get())
    except:
        line_spacing = 10
    try:
        custom_margin = int(margin_var.get())
    except:
        custom_margin = 30
    try:
        custom_padding = int(padding_var.get())
    except:
        custom_padding = border_width + 30

    rendered_lines = []
    max_line_width = 0
    total_height = 0
    dummy_img = Image.new("RGB", (1000, 1000))
    dummy_draw = ImageDraw.Draw(dummy_img)

    for i, line in enumerate(lines):
        col_color = colors_list[i] if i < len(colors_list) and colors_list[i] else color_default
        bbox = dummy_draw.textbbox((0, 0), line, font=font, stroke_width=border_width)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        line_img = Image.new("RGBA", (w + 2 * custom_padding, h + 2 * custom_padding), (0, 0, 0, 0))
        draw = ImageDraw.Draw(line_img)
        try:
            draw.text((custom_padding, custom_padding), line, font=font, fill=col_color,
                      stroke_width=border_width, stroke_fill=border_color)
        except Exception as e:
            messagebox.showerror("Error", f"Error en el color '{col_color}': {e}")
            draw.text((custom_padding, custom_padding), line, font=font, fill="white",
                      stroke_width=border_width, stroke_fill=border_color)
        rendered_lines.append(line_img)
        if line_img.width > max_line_width:
            max_line_width = line_img.width
        total_height += line_img.height + line_spacing

    if rendered_lines:
        total_height -= line_spacing
        text_img = Image.new("RGBA", (max_line_width, total_height), (0, 0, 0, 0))
        current_y = 0
        for line_img in rendered_lines:
            x_offset = (max_line_width - line_img.width) // 2
            text_img.paste(line_img, (x_offset, current_y), line_img)
            current_y += line_img.height + line_spacing

        new_width = max_line_width + 2 * custom_margin
        new_height = total_height + 2 * custom_margin
        canvas_img = Image.new("RGBA", (new_width, new_height), (0, 0, 0, 0))
        canvas_img.paste(text_img, (custom_margin, custom_margin), text_img)

        base_width, base_height = base_im.size
        pos = ((base_width - new_width) // 2, (base_height - new_height) // 2)
        final_im = base_im.copy()
        final_im.paste(canvas_img, pos, canvas_img)
        return final_im
    else:
        return base_im

def generate_cover_preview():
    file_path = cover_file_var.get()
    cover_text = cover_text_box.get("1.0", END)
    try:
        bw = int(border_width_var.get())
    except:
        bw = 2
    bc = border_color_var.get() or "black"
    im = generate_cover_with_text(file_path, cover_text, border_width=bw, border_color=bc)
    if im:
        im.thumbnail((400, 300))
        photo = ImageTk.PhotoImage(im)
        cover_preview_label.config(image=photo)
        cover_preview_label.image = photo

def save_cover():
    cover_text = cover_text_box.get("1.0", END)
    try:
        bw = int(border_width_var.get())
    except:
        bw = 2
    bc = border_color_var.get() or "black"
    im = generate_cover_with_text(cover_file_var.get(), cover_text, border_width=bw, border_color=bc)
    if im:
        # Forzamos que se guarde como PNG
        output_file = filedialog.asksaveasfilename(
            title="Guardar Carátula",
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png")]
        )
        if output_file:
            try:
                im.save(output_file, "PNG")
                messagebox.showinfo("Éxito", f"Carátula guardada en: {output_file}")
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo guardar la carátula: {str(e)}")


#############################################
# FUNCIONES PARA AUDIO, VIDEO Y GENERACIÓN
#############################################
def split_text_for_audio(text, max_length=300):
    words = text.split()
    chunks = []
    current_chunk = []
    current_length = 0
    for word in words:
        if current_length + len(word) + 1 > max_length and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_length = 0
        current_chunk.append(word)
        current_length += len(word) + 1
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks

def split_text_for_subtitles(text, words_per_chunk=3):
    words = text.split()
    chunks = []
    current_chunk = []
    for word in words:
        current_chunk.append(word)
        if len(current_chunk) >= words_per_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks

def generate_audio(text, output_file):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    chunks = split_text_for_audio(text, max_length=300)
    audio_clips = []
    speaker_sample = voice_sample_var.get()
    for i, chunk in enumerate(chunks):
        chunk_file = output_file.replace(".wav", f"_{i}.wav")
        tts.tts_to_file(text=chunk, speaker_wav=speaker_sample, language='es', file_path=chunk_file)
        print(f"Generando audio para el fragmento {i}: {chunk}")
        audio_clips.append(AudioFileClip(chunk_file))
    if audio_clips:
        final_audio = concatenate_audioclips(audio_clips)
        final_audio.write_audiofile(output_file)
        for clip in audio_clips:
            clip.close()

def load_background(bg_path, duration):
    ext = os.path.splitext(bg_path)[1].lower()
    if ext in [".mp4", ".mov", ".avi", ".mkv"]:
        clip = VideoFileClip(bg_path)
        if clip.duration > duration:
            clip = clip.subclip(0, duration)
        return clip.set_duration(duration)
    else:
        return ImageClip(bg_path).set_duration(duration)

def create_video(title, text, output_video, audio_file, bg_path, amplitude, period, zoom_factor):
    audio_clip = AudioFileClip(audio_file)
    duration = audio_clip.duration
    bg_clip = load_background(bg_path, duration)
    def dynamic_position(t):
        return (amplitude * math.sin(2 * math.pi * t / period),
                amplitude * math.cos(2 * math.pi * t / period))
    animated_clip = bg_clip.set_position(dynamic_position)
    zoom_clip = animated_clip.resize(lambda t: 1 + zoom_factor * math.sin(2 * math.pi * t / duration))
    background_clip = zoom_clip.set_duration(duration)
    w, h = background_clip.size

    # Parámetros de subtítulos (estos valores podrían venir de variables definidas en la GUI)
    max_text_width = int(w * 0.8)
    subtitle_font = subtitle_font_var.get() if subtitle_font_var.get() else "Futura-Bold"  # Ej: "Futura-Bold"
    subtitle_font_size = int(subtitle_font_size_var.get()) if subtitle_font_size_var.get() else 80
    subtitle_color = subtitle_color_var.get() if subtitle_color_var.get() else "white"
    subtitle_stroke_width = int(subtitle_stroke_width_var.get()) if subtitle_stroke_width_var.get() else 2
    subtitle_stroke_color = subtitle_stroke_color_var.get() if subtitle_stroke_color_var.get() else "black"
    # Posición vertical relativa al fondo (en píxeles desde el bottom)
    subtitle_bottom_margin = int(subtitle_bottom_margin_var.get()) if subtitle_bottom_margin_var.get() else 50
    # Transformación de texto: 'upper', 'lower' o 'none'
    subtitle_transform = subtitle_transform_var.get() if subtitle_transform_var.get() in ["upper", "lower"] else "none"

    # Dividir el texto en fragmentos para subtítulos
    subtitle_chunks = split_text_for_subtitles(text, words_per_chunk=5)
    subtitle_clips = []
    chunk_duration = duration / len(subtitle_chunks) if subtitle_chunks else duration
    time_position = 0
    for chunk in subtitle_chunks:
        if chunk.strip():
            # Aplica la transformación si se requiere
            if subtitle_transform == "upper":
                chunk = chunk.upper()
            elif subtitle_transform == "lower":
                chunk = chunk.lower()
            # Crear TextClip con los parámetros de estilo
            text_clip = TextClip(
                chunk,
                fontsize=subtitle_font_size,
                font=subtitle_font,
                color=subtitle_color,
                stroke_color=subtitle_stroke_color,
                stroke_width=subtitle_stroke_width,
                method='caption',
                size=(max_text_width, None),
                align='center'
            )
            # Posicionar: centrado horizontalmente y a "subtitle_bottom_margin" píxeles del fondo
            text_clip = text_clip.set_position(("center", h - text_clip.h - subtitle_bottom_margin))\
                                 .set_duration(chunk_duration)\
                                 .set_start(time_position)
            subtitle_clips.append(text_clip)
            time_position += chunk_duration

    final_clip = CompositeVideoClip([background_clip] + subtitle_clips)
    final_clip = final_clip.set_audio(audio_clip)
    final_clip = final_clip.set_fps(24)
    final_clip.write_videofile(output_video, fps=24, codec="libx264", audio_codec="aac")

def sanitize_filename(filename):
    filename = re.sub(r'[^a-zA-Z0-9_-]', '_', filename)
    filename = filename.replace(" ", "_")
    return filename[:100]

def run_generation(title, text, bg_path_value, amplitude, period, zoom_factor):
    safe_title = sanitize_filename(title)
    project_folder = os.path.join("Relatos", "export", safe_title)
    os.makedirs(project_folder, exist_ok=True)
    existing = [f for f in os.listdir(project_folder) if f.endswith(".mp4")]
    index = len(existing) + 1
    video_file = os.path.join(project_folder, f"{safe_title}_{index}.mp4")
    audio_file = os.path.join("Relatos", "audio_temp", f"{safe_title}_{index}.wav")
    os.makedirs('Relatos/audio_temp', exist_ok=True)
    os.makedirs('Relatos/video_temp', exist_ok=True)
    
    print(f"Generando audio para: {safe_title}")
    generate_audio(text, audio_file)
    print(f"Generando video para: {safe_title}")
    create_video(safe_title, text, video_file, audio_file, bg_path_value, amplitude, period, zoom_factor)
    print(f"Video generado: {video_file}")
    return video_file

def on_generate_task():
    title = title_entry.get().strip()
    text = text_box.get("1.0", END).strip()
    bg = bg_var.get().strip()
    if not title or not text or not bg:
        messagebox.showerror("Error", "Ingresa título, texto y selecciona un fondo.")
        return
    try:
        amplitude = float(amp_entry.get().strip())
        period = float(period_entry.get().strip())
        zoom_factor = float(zoom_entry.get().strip())
    except Exception:
        messagebox.showerror("Error", "Verifica que los parámetros de efectos sean números válidos.")
        return
    task = {"title": title, "text": text, "bg": bg, "amplitude": amplitude, "period": period, "zoom_factor": zoom_factor}
    processing_queue.put(task)
    tasks_list.append(task)
    update_queue_listbox()
    messagebox.showinfo("Tarea agregada", f"Se agregó a la cola el video: {title}")

def update_queue_listbox():
    queue_listbox.delete(0, END)
    for task in tasks_list:
        queue_listbox.insert(END, f"Título: {task['title']}")

def process_tasks():
    while True:
        task = processing_queue.get()
        try:
            gui_root.after(0, lambda: global_loader.start())
            video_file = run_generation(task['title'], task['text'], task['bg'],
                                        task['amplitude'], task['period'], task['zoom_factor'])
            gui_root.after(0, lambda: messagebox.showinfo("Proceso finalizado", f"Video generado: {video_file}"))
        except Exception as e:
            gui_root.after(0, lambda: messagebox.showerror("Error en tarea", f"Error al procesar '{task['title']}': {e}"))
        finally:
            if task in tasks_list:
                tasks_list.remove(task)
            gui_root.after(0, update_queue_listbox)
            gui_root.after(0, lambda: global_loader.stop())
            processing_queue.task_done()

#############################################
# NUEVA FUNCIÓN: Ensamblar Películas (montar_pelicula)
#############################################
def montar_pelicula(assembly_listbox):
    # Verifica que haya elementos en la lista de ensamblaje
    videos = assembly_listbox.get(0, END)
    if not videos:
        messagebox.showerror("Error", "No hay videos en la lista de ensamblaje.")
        return
    try:
        loader = show_loader("Ensamblando película...")
        clips = []
        for video in videos:
            clip = VideoFileClip(video)
            clips.append(clip)
        # Une los clips (se usa 'compose' para compatibilidad de tamaños)
        final_clip = concatenate_videoclips(clips, method="compose")
        # Si se ha seleccionado una canción de fondo, se añade
        if background_music_file.get():
            bg_music = AudioFileClip(background_music_file.get())
            # Si el clip tiene audio original, se compone; de lo contrario se asigna la música
            if final_clip.audio:
                final_audio = CompositeAudioClip([final_clip.audio, bg_music.set_duration(final_clip.duration)])
            else:
                final_audio = bg_music.set_duration(final_clip.duration)
            final_clip = final_clip.set_audio(final_audio)
        # Pregunta al usuario dónde guardar el vídeo ensamblado
        output_path = filedialog.asksaveasfilename(title="Guardar Película Ensamblada", defaultextension=".mp4", filetypes=[("MP4 Video", "*.mp4")])
        if output_path:
            final_clip.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")
            messagebox.showinfo("Éxito", f"Película ensamblada guardada en: {output_path}")
        for clip in clips:
            clip.close()
        loader.destroy()
    except Exception as e:
        loader.destroy()
        messagebox.showerror("Error", f"Error al ensamblar película: {str(e)}")

#############################################
# FUNCIONES PARA DESCARGAR VIDEO DESDE YOUTUBE
#############################################
def download_youtube_video(url, output_path):
    try:
        yt = YouTube(url)
        stream = yt.streams.filter(file_extension='mp4', progressive=True).order_by('resolution').desc().first()
        if stream:
            downloaded_file = stream.download(output_path=os.path.dirname(output_path))
            os.rename(downloaded_file, output_path)
            return output_path
        else:
            messagebox.showerror("Error", "No se encontró un stream MP4 disponible.")
            return None
    except Exception as e:
        messagebox.showerror("Error", f"Error al descargar desde YouTube: {e}")
        return None

def download_youtube_background():
    yt_url = askstring("Descargar desde YouTube", "Ingresa la URL del video de YouTube:")
    if yt_url:
        local_video_path = os.path.join("Relatos", "youtube_video.mp4")
        result = download_youtube_video(yt_url, local_video_path)
        if result:
            bg_var.set(result)
            bg_label_var.set(os.path.basename(result))
            update_thumbnail(result, preview_thumbnail)
            messagebox.showinfo("Video descargado", f"Video de YouTube descargado: {result}")

#############################################
# FUNCIONES DE BÚSQUEDA DE FONDO (Pexels, Pixabay y YouTube)
#############################################
def search_pexels(query, per_page=10):
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={query}&per_page={per_page}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return data.get("videos", [])
    else:
        messagebox.showerror("Error", "Error en la búsqueda en Pexels.")
        return []

def search_pixabay(query, per_page=10):
    url = f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={query}&per_page={per_page}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("hits", [])
    else:
        messagebox.showerror("Error", "Error en la búsqueda en Pixabay.")
        return []

def download_video(url, output_path):
    r = requests.get(url, stream=True)
    if r.status_code == 200:
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    else:
        messagebox.showerror("Error", "No se pudo descargar el video.")

def display_video_results(videos, container, source="pexels"):
    for widget in container.winfo_children():
        widget.destroy()
    columns = 3
    row = 0
    col = 0
    for video in videos:
        if source == "pexels":
            thumb_url = video.get("image")
        else:
            picture_id = video.get("picture_id")
            thumb_url = f"https://i.vimeocdn.com/video/{picture_id}_295x166.jpg" if picture_id else ""
        try:
            r = requests.get(thumb_url)
            if r.status_code == 200:
                im = Image.open(BytesIO(r.content))
                im.thumbnail((150, 100))
                photo = ImageTk.PhotoImage(im)
            else:
                photo = None
        except Exception:
            photo = None
        result_frame = Frame(container, bd=1, relief="solid", padx=5, pady=5)
        result_frame.grid(row=row, column=col, padx=5, pady=5)
        if photo:
            btn = Button(result_frame, image=photo, command=lambda v=video, src=source: select_video_result(v, src),
                         bg="white", fg="black")
            btn.image = photo
            btn.pack()
        else:
            btn = Button(result_frame, text="Sin miniatura", command=lambda v=video, src=source: select_video_result(v, src),
                         bg="white", fg="black")
            btn.pack()
        vid_id = video.get("id", "N/A")
        duration = video.get("duration", "N/A")
        lbl = Label(result_frame, text=f"ID: {vid_id}\nDur: {duration}s", wraplength=150)
        lbl.pack()
        col += 1
        if col >= columns:
            col = 0
            row += 1

def select_video_result(video, source):
    if source == "pexels":
        video_files = video.get("video_files", [])
        if video_files:
            sorted_videos = sorted(video_files, key=lambda x: x.get("width", 0))
            video_url = sorted_videos[-1]["link"]
            local_video_path = os.path.join("Relatos", "background_video.mp4")
            download_video(video_url, local_video_path)
            bg_var.set(local_video_path)
            bg_label_var.set(os.path.basename(local_video_path))
            update_thumbnail(local_video_path, preview_thumbnail)
            messagebox.showinfo("Video seleccionado", f"Video descargado: {local_video_path}")
        else:
            messagebox.showerror("Error", "No se encontraron archivos de video en el resultado.")
    else:
        videos_data = video.get("videos", {})
        if videos_data:
            highest = max(videos_data.values(), key=lambda x: x.get("width", 0))
            video_url = highest.get("url")
            local_video_path = os.path.join("Relatos", "background_video.mp4")
            download_video(video_url, local_video_path)
            bg_var.set(local_video_path)
            bg_label_var.set(os.path.basename(local_video_path))
            update_thumbnail(local_video_path, preview_thumbnail)
            messagebox.showinfo("Video seleccionado", f"Video descargado: {local_video_path}")
        else:
            messagebox.showerror("Error", "No se encontraron archivos de video en el resultado.")

def search_videos(source="pexels"):
    global results_frame
    query = search_entry.get().strip()
    if not query:
        messagebox.showerror("Error", "Ingrese una consulta para buscar.")
        return
    videos = search_pexels(query) if source=="pexels" else search_pixabay(query)
    display_video_results(videos, results_frame, source=source)

#############################################
# Pestaña "Crear Pelis" (TAB 1)
#############################################
def crear_pelis_tab(tab):
    scroll_frame = create_scrollable_frame(tab)
    
    # Dividir el scroll_frame en dos columnas: izquierda (datos básicos) y derecha (parámetros y fondo)
    left_frame = Frame(scroll_frame)
    right_frame = Frame(scroll_frame)
    left_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    right_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
    scroll_frame.columnconfigure(0, weight=1)
    scroll_frame.columnconfigure(1, weight=1)
    
    # --- COLIZQUIERDA: Datos básicos ---
    Label(left_frame, text="Título del Relato:", font=("Arial", 10)).grid(row=0, column=0, sticky="w", pady=5)
    global title_entry; title_entry = Entry(left_frame, width=40)
    title_entry.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
    
    Label(left_frame, text="Texto del Relato:", font=("Arial", 10)).grid(row=2, column=0, sticky="nw", pady=5)
    global text_box; text_box = Text(left_frame, width=40, height=10, wrap="word")
    text_box.grid(row=3, column=0, padx=5, pady=5, sticky="ew")
    # Ejemplo en la pestaña de "Crear Pelis"
    Label(left_frame, text="Fuente para Subtítulos:", font=("Arial", 10)).grid(row=11, column=0, sticky="w", pady=2)
    global subtitle_font_var; subtitle_font_var = tk.StringVar(value="Futura-Bold")
    Entry(left_frame, textvariable=subtitle_font_var, width=15, font=("Arial", 10)).grid(row=11, column=1, sticky="w", pady=2)

    Label(left_frame, text="Tamaño Subtítulos:", font=("Arial", 10)).grid(row=12, column=0, sticky="w", pady=2)
    global subtitle_font_size_var; subtitle_font_size_var = tk.StringVar(value="80")
    Entry(left_frame, textvariable=subtitle_font_size_var, width=5, font=("Arial", 10)).grid(row=12, column=1, sticky="w", pady=2)

    Label(left_frame, text="Color Texto:", font=("Arial", 10)).grid(row=13, column=0, sticky="w", pady=2)
    global subtitle_color_var; subtitle_color_var = tk.StringVar(value="white")
    Entry(left_frame, textvariable=subtitle_color_var, width=10, font=("Arial", 10)).grid(row=13, column=1, sticky="w", pady=2)

    Label(left_frame, text="Grosor del Borde:", font=("Arial", 10)).grid(row=14, column=0, sticky="w", pady=2)
    global subtitle_stroke_width_var; subtitle_stroke_width_var = tk.StringVar(value="2")
    Entry(left_frame, textvariable=subtitle_stroke_width_var, width=5, font=("Arial", 10)).grid(row=14, column=1, sticky="w", pady=2)

    Label(left_frame, text="Color del Borde:", font=("Arial", 10)).grid(row=15, column=0, sticky="w", pady=2)
    global subtitle_stroke_color_var; subtitle_stroke_color_var = tk.StringVar(value="black")
    Entry(left_frame, textvariable=subtitle_stroke_color_var, width=10, font=("Arial", 10)).grid(row=15, column=1, sticky="w", pady=2)

    Label(left_frame, text="Margen Inferior (px):", font=("Arial", 10)).grid(row=16, column=0, sticky="w", pady=2)
    global subtitle_bottom_margin_var; subtitle_bottom_margin_var = tk.StringVar(value="50")
    Entry(left_frame, textvariable=subtitle_bottom_margin_var, width=5, font=("Arial", 10)).grid(row=16, column=1, sticky="w", pady=2)

    Label(left_frame, text="Transformación (upper/lower):", font=("Arial", 10)).grid(row=17, column=0, sticky="w", pady=2)
    global subtitle_transform_var; subtitle_transform_var = tk.StringVar(value="none")
    Entry(left_frame, textvariable=subtitle_transform_var, width=10, font=("Arial", 10)).grid(row=17, column=1, sticky="w", pady=2)

    
    # --- COLDERECHA: Parámetros y selección de fondo ---
    Label(right_frame, text="Efectos:", font=("Arial", 12, "bold")).grid(row=0, column=0, sticky="w", pady=5)
    
    # Parámetro: Amplitud
    Label(right_frame, text="Amplitud:", font=("Arial", 10)).grid(row=1, column=0, sticky="w", pady=2)
    global amp_entry; amp_entry = Entry(right_frame, width=10)
    amp_entry.insert(0, "5")
    amp_entry.grid(row=1, column=1, padx=5, pady=2, sticky="w")
    
    # Parámetro: Periodo
    Label(right_frame, text="Periodo:", font=("Arial", 10)).grid(row=2, column=0, sticky="w", pady=2)
    global period_entry; period_entry = Entry(right_frame, width=10)
    period_entry.insert(0, "5")
    period_entry.grid(row=2, column=1, padx=5, pady=2, sticky="w")
    
    # Parámetro: Zoom Factor
    Label(right_frame, text="Zoom Factor:", font=("Arial", 10)).grid(row=3, column=0, sticky="w", pady=2)
    global zoom_entry; zoom_entry = Entry(right_frame, width=10)
    zoom_entry.insert(0, "0.05")
    zoom_entry.grid(row=3, column=1, padx=5, pady=2, sticky="w")
    
    # Selección de fondo
    Label(right_frame, text="Fondo (archivo):", font=("Arial", 12, "bold")).grid(row=4, column=0, columnspan=2, pady=5, sticky="w")
    global bg_var; bg_var = tk.StringVar()
    Button(right_frame, text="Seleccionar Archivo", command=lambda: select_bg(bg_var, bg_label_var, preview_thumbnail),
           bg="white", fg="black").grid(row=5, column=0, sticky="w", padx=5, pady=5)
    global bg_label_var; bg_label_var = tk.StringVar(value="Ningún archivo seleccionado")
    Label(right_frame, textvariable=bg_label_var, font=("Arial", 10)).grid(row=5, column=1, sticky="w", padx=5, pady=5)
    
    # Selección de sample de voz
    Label(right_frame, text="Sample de Voz:", font=("Arial", 10)).grid(row=6, column=0, sticky="w", pady=2)
    global voice_sample_var; voice_sample_var = tk.StringVar(value="/Users/framartinez/examples/voz_es.mp3")
    Button(right_frame, text="Seleccionar Sample", command=lambda: select_voice_sample(voice_sample_var, voice_sample_label),
           bg="white", fg="black").grid(row=6, column=1, padx=5, pady=2, sticky="w")
    global voice_sample_label; voice_sample_label = Label(right_frame, text=os.path.basename(voice_sample_var.get()), font=("Arial", 10))
    voice_sample_label.grid(row=6, column=2, sticky="w", padx=5, pady=2)
    
    # Buscador de fondo y resultados: dentro de un frame
    global search_frame
    search_frame = Frame(right_frame, bd=2, relief="groove", padx=5, pady=5)
    search_frame.grid(row=7, column=0, columnspan=3, pady=5, sticky="ew")
    Label(search_frame, text="Buscar fondo en:", font=("Arial", 10)).grid(row=0, column=0, sticky="w")
    global search_entry; search_entry = Entry(search_frame, width=25)
    search_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
    Button(search_frame, text="Pexels", command=lambda: search_videos(source="pexels"),
           bg="lightblue").grid(row=0, column=2, padx=5, pady=5)
    Button(search_frame, text="Pixabay", command=lambda: search_videos(source="pixabay"),
           bg="lightgreen").grid(row=0, column=3, padx=5, pady=5)
    Button(search_frame, text="YouTube", command=download_youtube_background,
           bg="lightcoral").grid(row=0, column=4, padx=5, pady=5)
    
    global results_frame
    results_frame = Frame(search_frame, bd=2, relief="sunken")
    results_frame.grid(row=1, column=0, columnspan=5, pady=5, sticky="nsew")
    for i in range(5):
        search_frame.columnconfigure(i, weight=1)
    
    global preview_thumbnail; preview_thumbnail = Label(right_frame, bd=2, relief="groove")
    preview_thumbnail.grid(row=8, column=0, columnspan=3, pady=5, sticky="ew")
    
    # Cola de tareas y loader global (loader en la cola de procesamiento)
    global queue_frame_main
    queue_frame_main = Frame(right_frame, bd=2, relief="groove", padx=5, pady=5)
    queue_frame_main.grid(row=9, column=0, columnspan=3, pady=5, sticky="ew")
    Label(queue_frame_main, text="Cola de tareas pendientes:", font=("Arial", 10)).pack(anchor="w")
    global queue_listbox; queue_listbox = tk.Listbox(queue_frame_main, width=40, height=5)
    queue_listbox.pack(anchor="w", padx=5, pady=5, fill="both", expand=True)
    global global_loader
    global_loader = ttk.Progressbar(queue_frame_main, mode="indeterminate")
    global_loader.pack(fill="x", padx=5, pady=5)
    
    Button(right_frame, text="Agregar Video a la Cola", command=on_generate_task,
           bg="blue", fg="white", font=("Arial", 12)).grid(row=10, column=0, columnspan=3, pady=5)
    
    left_frame.columnconfigure(0, weight=1)
    right_frame.columnconfigure(0, weight=1)
    right_frame.columnconfigure(1, weight=1)
    right_frame.columnconfigure(2, weight=1)

#############################################
# Pestaña "Ensamblar Pelis" (TAB 2)
#############################################
def open_video_assembler():
    assembler_win = tk.Toplevel(gui_root)
    assembler_win.title("Ensamblador de Películas")
    assembler_win.geometry("750x600")
    
    # Marco para vídeos disponibles
    available_frame = Frame(assembler_win, padx=10, pady=10, bd=2, relief="groove")
    available_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
    Label(available_frame, text="Videos Disponibles:", font=("Arial", 12, "bold")).pack(anchor="w")
    available_listbox = tk.Listbox(assembler_win, selectmode=tk.SINGLE, width=40, height=15)
    available_listbox.pack(in_=available_frame, fill="both", expand=True, padx=5, pady=5)
    
    # Marco para vídeos a ensamblar
    assembly_frame = Frame(assembler_win, padx=10, pady=10, bd=2, relief="groove")
    assembly_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
    Label(assembly_frame, text="Videos para Ensamblaje:", font=("Arial", 12, "bold")).pack(anchor="w")
    assembly_listbox = tk.Listbox(assembler_win, selectmode=tk.SINGLE, width=40, height=15)
    assembly_listbox.pack(in_=assembly_frame, fill="both", expand=True, padx=5, pady=5)
    
    # Marco de controles para mover vídeos
    control_frame = Frame(assembler_win, padx=10, pady=10)
    control_frame.grid(row=0, column=1, padx=5, pady=5)
    Button(control_frame, text="Agregar >>", command=lambda: add_video(available_listbox, assembly_listbox),
           width=12, bg="white", fg="black").pack(pady=10)
    Button(control_frame, text="<< Quitar", command=lambda: remove_video(assembly_listbox),
           width=12, bg="white", fg="black").pack(pady=10)
    
    reorder_frame = Frame(assembler_win, padx=10, pady=10)
    reorder_frame.grid(row=1, column=2, padx=5, pady=5)
    Button(reorder_frame, text="Mover Arriba", command=lambda: move_up(assembly_listbox),
           width=15, bg="white", fg="black").pack(pady=5)
    Button(reorder_frame, text="Mover Abajo", command=lambda: move_down(assembly_listbox),
           width=15, bg="white", fg="black").pack(pady=5)
    
    # Cargar vídeos disponibles desde export
    export_root = os.path.join("Relatos", "export")
    for root_dir, dirs, files in os.walk(export_root):
        for file in files:
            if file.endswith(".mp4"):
                full_path = os.path.join(root_dir, file)
                available_listbox.insert(END, full_path)
    
    # --- NUEVO: Selección de Canción de Fondo opcional ---
    global background_music_file
    background_music_file = tk.StringVar(value="")
    music_frame = Frame(assembler_win, padx=10, pady=10, bd=2, relief="groove")
    music_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
    Button(music_frame, text="Seleccionar Canción de Fondo", command=lambda: background_music_file.set(filedialog.askopenfilename(
        title="Selecciona una Canción de Fondo", filetypes=[("Audio Files", "*.mp3 *.wav *.ogg")])
    )).pack(side="left", padx=5)
    Label(music_frame, textvariable=background_music_file).pack(side="left", padx=5)
    
    # Botón para montar película (se mueve a row=3 para evitar problemas de layout)
    Button(assembler_win, text="Montar Película", command=lambda: montar_pelicula(assembly_listbox),
           bg="green", fg="white", font=("Arial", 12)).grid(row=3, column=0, columnspan=3, pady=10)
    
    assembler_win.grid_rowconfigure(0, weight=1)
    assembler_win.grid_columnconfigure(0, weight=1)
    assembler_win.grid_columnconfigure(1, weight=0)
    assembler_win.grid_columnconfigure(2, weight=1)

def ensamblar_pelis_tab(tab):
    scroll_frame = create_scrollable_frame(tab)
    Button(scroll_frame, text="Abrir Ensamblador de Películas", command=open_video_assembler,
           bg="darkorange", fg="white", font=("Arial", 12)).pack(pady=10)

#############################################
# Pestaña "Crear Carátulas" (TAB 3)
#############################################
def crear_caratulas_tab(tab):
    scroll_frame = create_scrollable_frame(tab)
    Label(scroll_frame, text="Selecciona un archivo para la Carátula:", font=("Arial", 12, "bold")).grid(row=0, column=0, sticky="w")
    global cover_file_var; cover_file_var = tk.StringVar()
    Button(scroll_frame, text="Seleccionar Archivo", command=lambda: select_cover_file(cover_file_var, cover_file_label, cover_preview_label),
           bg="white", fg="black", font=("Arial", 12)).grid(row=0, column=1, sticky="w", padx=5, pady=5)
    global cover_file_label; cover_file_label = Label(scroll_frame, text="Ningún archivo seleccionado", font=("Arial", 10))
    cover_file_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Texto para Carátula:", font=("Arial", 10)).grid(row=2, column=0, sticky="w", padx=5, pady=5)
    global cover_text_box; cover_text_box = Text(scroll_frame, width=50, height=5, font=("Arial", 10))
    cover_text_box.grid(row=2, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Color de Fuente (único):", font=("Arial", 10)).grid(row=3, column=0, sticky="w", padx=5, pady=5)
    global font_color_var; font_color_var = tk.StringVar(value="white")
    Entry(scroll_frame, textvariable=font_color_var, width=20, font=("Arial", 10)).grid(row=3, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Colores por Línea (separados por coma):", font=("Arial", 10)).grid(row=4, column=0, sticky="w", padx=5, pady=5)
    global colors_var; colors_var = tk.StringVar(value="")
    Entry(scroll_frame, textvariable=colors_var, width=20, font=("Arial", 10)).grid(row=4, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Tipo de Fuente (ruta o nombre):", font=("Arial", 10)).grid(row=5, column=0, sticky="w", padx=5, pady=5)
    global font_type_var; font_type_var = tk.StringVar(value="Impact.ttf")
    Entry(scroll_frame, textvariable=font_type_var, width=20, font=("Arial", 10)).grid(row=5, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Tamaño de Fuente:", font=("Arial", 10)).grid(row=6, column=0, sticky="w", padx=5, pady=5)
    global font_size_var; font_size_var = tk.StringVar(value="100")
    Entry(scroll_frame, textvariable=font_size_var, width=5, font=("Arial", 10)).grid(row=6, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Interlineado:", font=("Arial", 10)).grid(row=7, column=0, sticky="w", padx=5, pady=5)
    global interlineado_var; interlineado_var = tk.StringVar(value="-80")
    Entry(scroll_frame, textvariable=interlineado_var, width=5, font=("Arial", 10)).grid(row=7, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Padding (espacio interno):", font=("Arial", 10)).grid(row=8, column=0, sticky="w", padx=5, pady=5)
    global padding_var; padding_var = tk.StringVar(value="80")
    Entry(scroll_frame, textvariable=padding_var, width=5, font=("Arial", 10)).grid(row=8, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Margen (espacio externo):", font=("Arial", 10)).grid(row=9, column=0, sticky="w", padx=5, pady=5)
    global margin_var; margin_var = tk.StringVar(value="10")
    Entry(scroll_frame, textvariable=margin_var, width=5, font=("Arial", 10)).grid(row=9, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Color de Borde:", font=("Arial", 10)).grid(row=10, column=0, sticky="w", padx=5, pady=5)
    global border_color_var; border_color_var = tk.StringVar(value="black")
    Entry(scroll_frame, textvariable=border_color_var, width=20, font=("Arial", 10)).grid(row=10, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Grosor del Borde:", font=("Arial", 10)).grid(row=11, column=0, sticky="w", padx=5, pady=5)
    global border_width_var; border_width_var = tk.StringVar(value="2")
    Entry(scroll_frame, textvariable=border_width_var, width=5, font=("Arial", 10)).grid(row=11, column=1, sticky="w", padx=5, pady=5)
    
    Label(scroll_frame, text="Alineación (izquierda, centro, derecha):", font=("Arial", 10)).grid(row=12, column=0, sticky="w", padx=5, pady=5)
    global alignment_var; alignment_var = tk.StringVar(value="center")
    Entry(scroll_frame, textvariable=alignment_var, width=20, font=("Arial", 10)).grid(row=12, column=1, sticky="w", padx=5, pady=5)
    
    Button(scroll_frame, text="Generar Vista Previa", command=generate_cover_preview,
           bg="white", fg="black", font=("Arial", 10)).grid(row=13, column=0, sticky="w", padx=5, pady=5)
    global cover_preview_label; cover_preview_label = Label(scroll_frame, bd=2, relief="sunken")
    cover_preview_label.grid(row=13, column=1, sticky="w", padx=5, pady=5)
    Button(scroll_frame, text="Guardar Carátula", command=save_cover,
           bg="white", fg="black", font=("Arial", 10)).grid(row=14, column=0, columnspan=2, padx=5, pady=5)

#############################################
# Pestaña "Subir a YouTube" (TAB 4)
#############################################
def subir_a_youtube_tab(tab):
    scroll_frame = create_scrollable_frame(tab)
    
    Label(scroll_frame, text="Subir Video a YouTube", font=("Arial", 14, "bold")).grid(row=0, column=0, columnspan=2, pady=10)
    
    # Archivo de video
    Label(scroll_frame, text="Archivo de Video:", font=("Arial", 10)).grid(row=1, column=0, sticky="w", padx=5, pady=5)
    global video_file_var; video_file_var = tk.StringVar()
    Button(scroll_frame, text="Seleccionar Video", command=lambda: video_file_var.set(filedialog.askopenfilename(
        title="Selecciona un video",
        filetypes=[("Video Files", "*.mp4 *.mov *.avi *.mkv")]
    )), bg="white", fg="black").grid(row=1, column=1, sticky="w", padx=5, pady=5)
    
    # Título
    Label(scroll_frame, text="Título:", font=("Arial", 10)).grid(row=2, column=0, sticky="w", padx=5, pady=5)
    global yt_title_var; yt_title_var = tk.StringVar()
    Entry(scroll_frame, textvariable=yt_title_var, width=40).grid(row=2, column=1, sticky="w", padx=5, pady=5)
    
    # Descripción
    Label(scroll_frame, text="Descripción:", font=("Arial", 10)).grid(row=3, column=0, sticky="nw", padx=5, pady=5)
    global yt_description_text; yt_description_text = Text(scroll_frame, width=40, height=5)
    yt_description_text.grid(row=3, column=1, sticky="w", padx=5, pady=5)
    
    # Etiquetas
    Label(scroll_frame, text="Etiquetas (separadas por coma):", font=("Arial", 10)).grid(row=4, column=0, sticky="w", padx=5, pady=5)
    global yt_tags_var; yt_tags_var = tk.StringVar()
    Entry(scroll_frame, textvariable=yt_tags_var, width=40).grid(row=4, column=1, sticky="w", padx=5, pady=5)
    
    # Privacidad
    Label(scroll_frame, text="Privacidad:", font=("Arial", 10)).grid(row=5, column=0, sticky="w", padx=5, pady=5)
    global yt_privacy_var; yt_privacy_var = tk.StringVar(value="public")
    privacy_options = ["public", "unlisted", "private"]
    yt_privacy_menu = ttk.Combobox(scroll_frame, textvariable=yt_privacy_var, values=privacy_options, state="readonly")
    yt_privacy_menu.grid(row=5, column=1, sticky="w", padx=5, pady=5)
    
    # Subtítulos
    Label(scroll_frame, text="Subtítulos (opcional):", font=("Arial", 10)).grid(row=6, column=0, sticky="w", padx=5, pady=5)
    global yt_subtitles_var; yt_subtitles_var = tk.StringVar()
    Button(scroll_frame, text="Seleccionar Archivo", command=lambda: yt_subtitles_var.set(filedialog.askopenfilename(
        title="Selecciona un archivo de subtítulos",
        filetypes=[("Subtitle Files", "*.srt *.vtt")]
    )), bg="white", fg="black").grid(row=6, column=1, sticky="w", padx=5, pady=5)
    
    # Botón de subida
    Button(scroll_frame, text="Subir Video a YouTube", command=upload_to_youtube, bg="red", fg="white", font=("Arial", 12, "bold")).grid(row=7, column=0, columnspan=2, pady=10)

def upload_to_youtube():
    video_path = video_file_var.get()
    title = yt_title_var.get()
    description = yt_description_text.get("1.0", END).strip()
    tags = [tag.strip() for tag in yt_tags_var.get().split(",") if tag.strip()]
    privacy = yt_privacy_var.get()
    subtitles_path = yt_subtitles_var.get()
    
    if not video_path or not title:
        messagebox.showerror("Error", "Selecciona un video y escribe un título.")
        return
    
    # Mostrar loader durante la "subida" (simulada)
    loader = show_loader("Subiendo video a YouTube...")
    info = f"Video: {video_path}\nTítulo: {title}\nDescripción: {description}\nEtiquetas: {tags}\nPrivacidad: {privacy}\nSubtítulos: {subtitles_path}"
    print("Subiendo video a YouTube con la siguiente información:")
    print(info)
    # Simulación de tiempo de subida (podrías usar threading o similar para procesos largos)
    loader.after(2000, lambda: [loader.destroy(), messagebox.showinfo("Subida", "Video subido (simulado). Revisa la consola para ver la información.")])

#############################################
# CONFIGURACIÓN DEL NOTEBOOK Y VENTANA PRINCIPAL
#############################################
if __name__ == "__main__":
    threading.Thread(target=process_tasks, daemon=True).start()
    gui_root = Tk()
    gui_root.title("Generador de Video y Herramientas")
    gui_root.geometry("1100x700")
    
    notebook = ttk.Notebook(gui_root)
    notebook.pack(fill="both", expand=True)
    
    tab1 = Frame(notebook)
    tab2 = Frame(notebook)
    tab3 = Frame(notebook)
    tab4 = Frame(notebook)  # Pestaña para subir videos a YouTube
    
    notebook.add(tab1, text="Crear Pelis")
    notebook.add(tab2, text="Ensamblar Pelis")
    notebook.add(tab3, text="Crear Carátulas")
    notebook.add(tab4, text="Subir a YouTube")

    
    crear_pelis_tab(tab1)
    ensamblar_pelis_tab(tab2)
    crear_caratulas_tab(tab3)
    subir_a_youtube_tab(tab4)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    
    gui_root.mainloop()
