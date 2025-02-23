import os
import json
import sys
import time
import torch
import re
import textwrap
from PIL import Image, ImageDraw, ImageFont
from TTS.api import TTS
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from pydub import AudioSegment
from moviepy.editor import CompositeVideoClip, ImageClip, concatenate_videoclips, VideoFileClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.audio.AudioClip import concatenate_audioclips
import concurrent.futures


def ensure_directory(path):
    os.makedirs(path, exist_ok=True)


def extract_text_from_epub(epub_file, start_text, end_text):
    book = epub.read_epub(epub_file)
    full_text = []
    capture = False
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.content, 'html.parser')
        content = soup.get_text(separator=' ')
        if start_text.lower() in content.lower():
            capture = True
        if capture:
            full_text.append(content)
        if end_text.lower() in content.lower():
            break
    return clean_text(" ".join(full_text))


def divide_text(text, max_length=25000):
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]


def clean_text(text):
    replacements = {
        'º': '','“': '', '”': '', '‘': '', '&': '', '’': '', '©': '', '«': '', '»': '',
        '–': '-', '¿': '', '¡': '', '…': '...', '*': '', '/': '', '—': '-',
        '→': '', '•': '', '%': '', '_': ' ', '=': ' ', '\n': ' ', '\r': ' '
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    numbers_to_words = {
        '0': 'cero', '1': 'uno', '2': 'dos', '3': 'tres', '4': 'cuatro',
        '5': 'cinco', '6': 'seis', '7': 'siete', '8': 'ocho', '9': 'nueve'
    }
    text = re.sub(r'\d', lambda x: numbers_to_words[x.group()], text)
    return re.sub(r'\s+', ' ', text).strip()


def wrap_text(text, max_width):
    lines = []
    for line in text.split('\n'):
        wrapped_lines = textwrap.wrap(line, width=max_width)
        lines.extend(wrapped_lines if wrapped_lines else [''])
    return lines


def create_custom_image(background_image, title, output_image, author):
    original_image = Image.open(background_image).convert("RGB")
    max_width, max_height = 1920, 1080
    original_image.thumbnail((max_width, max_height))
    draw = ImageDraw.Draw(original_image)

    # Usar una fuente más elegante y grande
    font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 100)
    font_author = ImageFont.truetype("DejaVuSans-Bold.ttf", 80)
    font_audiobook = ImageFont.truetype("DejaVuSans-Bold.ttf", 100)

    # Convertir texto a versalitas
    title = title.upper()
    author = author.upper()
    audiobook_text = "AUDIOLIBRO"

    # Ajustar el centro vertical para la distribución del texto
    wrapped_title = wrap_text(title, 25)
    line_heights = [draw.textbbox((0, 0), line, font=font_title)[3] for line in wrapped_title]
    total_title_height = sum(line_heights) + 10 * (len(wrapped_title) - 1)

    author_text_width, author_text_height = draw.textbbox((0, 0), author, font=font_author)[2:]
    audiobook_width, audiobook_height = draw.textbbox((0, 0), audiobook_text, font=font_audiobook)[2:]

    total_text_height = total_title_height + author_text_height + audiobook_height + 120
    start_y = (original_image.height - total_text_height) // 2

    # Dibujar bordes para mejorar la visibilidad del texto
    shadow_offset = 5 
    shadow_color = "black"
    title_color = "yellow"
    text_color = "white"

    # Dibujar título con borde negro
    y_text = start_y
    for line, line_height in zip(wrapped_title, line_heights):
        line_width = draw.textbbox((0, 0), line, font=font_title)[2]
        x_text = (original_image.width - line_width) // 2
        for dx, dy in [(-shadow_offset, 0), (shadow_offset, 0), (0, -shadow_offset), (0, shadow_offset)]:
            draw.text((x_text + dx, y_text + dy), line, font=font_title, fill=shadow_color)
        draw.text((x_text, y_text), line, font=font_title, fill=title_color)
        y_text += line_height + 10

    # Dibujar autor con borde negro
    x_author = (original_image.width - author_text_width) // 2
    y_author = y_text + 30
    for dx, dy in [(-shadow_offset, 0), (shadow_offset, 0), (0, -shadow_offset), (0, shadow_offset)]:
        draw.text((x_author + dx, y_author + dy), author, font=font_author, fill=shadow_color)
    draw.text((x_author, y_author), author, font=font_author, fill=text_color)

    # Dibujar "Audiolibro" con borde negro
    x_audiobook = (original_image.width - audiobook_width) // 2
    y_audiobook = y_text + author_text_height + 80
    for dx, dy in [(-shadow_offset, 0), (shadow_offset, 0), (0, -shadow_offset), (0, shadow_offset)]:
        draw.text((x_audiobook + dx, y_audiobook + dy), audiobook_text, font=font_audiobook, fill=shadow_color)
    draw.text((x_audiobook, y_audiobook), audiobook_text, font=font_audiobook, fill=text_color)

    original_image.save(output_image)


def create_audio(text, output_file, tts):
    text = clean_text(text)
    tts.tts_to_file(text=text, file_path=output_file, noise_scale=0.4, noise_scale_w=0.4, length_scale=1)


def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def create_video(audio_file, background_image, output_file):
    # Cargar el audio del audiolibro y el audio de bienvenida
    bienvenida_audio = "mensaje_bienvenida.mp3"

    if not os.path.exists(bienvenida_audio):
        print(f"Archivo de bienvenida '{bienvenida_audio}' no encontrado. Procediendo sin introducción.")
        audio_clip = AudioFileClip(audio_file)
    else:
        bienvenida_clip = AudioFileClip(bienvenida_audio)
        main_audio_clip = AudioFileClip(audio_file)
        audio_clip = concatenate_audioclips([bienvenida_clip, main_audio_clip])

    # Obtener la duración total
    audio_duration = audio_clip.duration

    # Crear el fondo de video con la imagen
    background_clip = ImageClip(background_image, duration=audio_duration)

    # Añadir el audio al fondo de imagen
    final_clip = background_clip.set_audio(audio_clip)

    # Guardar el video con la introducción
    final_clip.write_videofile(output_file, fps=24)


def create_subtitles(text, audio_file, subtitle_file):
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    words = text.split()
    block_size = 4
    num_blocks = (len(words) + block_size - 1) // block_size
    block_duration = audio_duration / num_blocks if num_blocks else 0

    with open(subtitle_file, 'w', encoding='utf-8') as f:
        for i in range(num_blocks):
            start_time = i * block_duration
            end_time = (i + 1) * block_duration
            phrase = " ".join(words[i * block_size: (i + 1) * block_size])
            start_time_str = format_time(start_time)
            end_time_str = format_time(end_time)
            f.write(f"{i+1}\n{start_time_str} --> {end_time_str}\n{phrase}\n\n")


def merge_subtitles(output_dir, num_parts):
    final_subtitle_file = os.path.join(output_dir, "final_subtitles.srt")
    with open(final_subtitle_file, 'w', encoding='utf-8') as outfile:
        counter = 1
        for i in range(num_parts):
            subtitle_file = os.path.join(output_dir, f"subtitles_{i}.srt")
            if os.path.exists(subtitle_file):
                with open(subtitle_file, 'r', encoding='utf-8') as infile:
                    lines = infile.readlines()
                    for line in lines:
                        if line.strip().isdigit():
                            outfile.write(f"{counter}\n")
                            counter += 1
                        else:
                            outfile.write(line)
                    outfile.write("\n")
                    return final_subtitle_file


def parse_srt_time(time_str):
    h, m, s_ms = time_str.split(":")
    s, ms = s_ms.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def format_srt_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def merge_subtitles_group(subtitle_files, clips_group, output_subtitle_file):
    """
    Fusiona los archivos de subtítulos de un grupo de clips,
    ajustando los tiempos según la duración acumulada.
    """
    cumulative_offset = 0.0
    counter = 1
    with open(output_subtitle_file, 'w', encoding='utf-8') as outfile:
        for sub_file, clip in zip(subtitle_files, clips_group):
            if not os.path.exists(sub_file):
                continue
            with open(sub_file, 'r', encoding='utf-8') as infile:
                content = infile.read().strip()
            if not content:
                continue
            blocks = content.split("\n\n")
            for block in blocks:
                lines = block.splitlines()
                if len(lines) < 3:
                    continue
                times_line = lines[1]
                if " --> " in times_line:
                    start_str, end_str = times_line.split(" --> ")
                    new_start = parse_srt_time(start_str) + cumulative_offset
                    new_end = parse_srt_time(end_str) + cumulative_offset
                    new_times_line = f"{format_srt_time(new_start)} --> {format_srt_time(new_end)}"
                    new_block = f"{counter}\n{new_times_line}\n" + "\n".join(lines[2:]) + "\n\n"
                    outfile.write(new_block)
                    counter += 1
            cumulative_offset += clip.duration
    return output_subtitle_file


def get_metadata_from_epub(epub_file):
    try:
        book = epub.read_epub(epub_file)
    except Exception as e:
        print(f"Error al leer el archivo ePub: {e}")
        sys.exit(1)
    title = book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else "Desconocido"
    author = book.get_metadata('DC', 'creator')[0][0] if book.get_metadata('DC', 'creator') else "Anónimo"
    return title, author


def group_indices(clips, max_group_duration=11 * 3600):
    groups = []
    current_group = []
    current_duration = 0.0
    for i, clip in enumerate(clips):
        if current_duration + clip.duration > max_group_duration and current_group:
            groups.append(current_group)
            current_group = [i]
            current_duration = clip.duration
        else:
            current_group.append(i)
            current_duration += clip.duration
    if current_group:
        groups.append(current_group)
    return groups


def group_clips(clips, max_group_duration=11 * 3600):
    """
    Agrupa los clips de video de manera que la duración total de cada grupo no supere max_group_duration.
    """
    groups = []
    current_group = []
    current_duration = 0.0

    for clip in clips:
        if current_duration + clip.duration > max_group_duration and current_group:
            groups.append(current_group)
            current_group = [clip]
            current_duration = clip.duration
        else:
            current_group.append(clip)
            current_duration += clip.duration

    if current_group:
        groups.append(current_group)
    return groups


def process_video_groups(video_clips, output_dir, max_group_duration=11 * 3600):
    """
    Toma una lista de clips y genera videos concatenados para cada grupo, donde cada grupo tiene una duración máxima de max_group_duration.
    """
    groups = group_clips(video_clips, max_group_duration)
    final_videos = []

    for i, group in enumerate(groups):
        final_video_path = os.path.join(output_dir, f"final_video_part_{i+1}.mp4")
        concatenated_clip = concatenate_videoclips(group)
        concatenated_clip.write_videofile(final_video_path, fps=24, codec="libx264")
        final_videos.append(final_video_path)

    return final_videos


def load_processed_books():
    if os.path.exists("processed_books.json"):
        try:
            with open("processed_books.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Convertir la lista en diccionario usando el campo "epub_file" como clave
                    return {entry.get("epub_file", ""): entry for entry in data if "epub_file" in entry}
                elif isinstance(data, dict):
                    return data
        except json.JSONDecodeError:
            return {}
    return {}


def save_processed_books(processed_books):
    with open("processed_books.json", "w", encoding="utf-8") as f:
        json.dump(list(processed_books.values()), f, indent=4)


def process_book(book_info, processed_books):
    epub_file = book_info.get("epub_file")
    if not epub_file:
        print("Error: El libro no tiene un archivo ePub definido.")
        return

    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        tts = TTS("tts_models/es/css10/vits", gpu=(device == "cuda"))

        if not os.path.exists(epub_file):
            raise FileNotFoundError(f"El archivo ePub no se encuentra: {epub_file}")

        start_text = book_info.get("start_text", "")
        end_text = book_info.get("end_text", "")
        background_image = book_info.get("background_image", "")
        base_output_dir = book_info.get("output_dir", "")
        title, author = get_metadata_from_epub(epub_file)
        output_dir = os.path.join(base_output_dir, f"{title} - {author}")
        ensure_directory(output_dir)

        text = extract_text_from_epub(epub_file, start_text, end_text)
        if not text:
            raise ValueError("No se pudo extraer el texto del libro.")

        text_parts = divide_text(text)
        video_clips = []
        subtitle_files = []
        temp_files = []

        processed_entry = processed_books.get(epub_file, {
            "title": title,
            "author": author,
            "epub_file": epub_file,
            "start_text": start_text,
            "end_text": end_text,
            "background_image": background_image,
            "output_dir": output_dir,
            "processing_started": True,
            "processing_completed": False,
            "current_step": "Starting",
            "final_videos": [],
            "final_subtitles": [],
            "processed": False,
            "error": False
        })
        processed_books[epub_file] = processed_entry
        save_processed_books(processed_books)

        start_part = 0
        if "Processing part" in processed_entry["current_step"]:
            try:
                start_part = int(processed_entry["current_step"].split("part ")[-1].split("/")[0])
            except ValueError:
                start_part = 0

        for i, part in enumerate(text_parts[start_part:], start=start_part):
            audio_file = os.path.join(output_dir, f"audio_{i}.wav")
            video_file = os.path.join(output_dir, f"video_{i}.mp4")
            subtitle_file = os.path.join(output_dir, f"subtitles_{i}.srt")
            image_file = os.path.join(output_dir, f"image_{i}.jpg")

            processed_entry["current_step"] = f"Processing part {i+1}/{len(text_parts)}"
            save_processed_books(processed_books)

            create_audio(part, audio_file, tts)
            create_custom_image(background_image, title, image_file, author)
            create_video(audio_file, image_file, video_file)
            create_subtitles(part, audio_file, subtitle_file)

            clip = VideoFileClip(video_file)
            video_clips.append(clip)
            subtitle_files.append(subtitle_file)
            temp_files.extend([audio_file, video_file, subtitle_file])

        max_duration = 11 * 3600
        total_duration = sum(clip.duration for clip in video_clips)

        if total_duration <= max_duration:
            final_video = os.path.join(output_dir, "final_video.mp4")
            concatenate_videoclips(video_clips).write_videofile(final_video, fps=24)
            processed_entry["final_videos"].append(final_video)
            merged_subtitle = merge_subtitles_group(subtitle_files, video_clips, os.path.join(output_dir, "final_subtitles.srt"))
            processed_entry["final_subtitles"].append(merged_subtitle)
        else:
            final_videos = process_video_groups(video_clips, output_dir, max_duration)
            processed_entry["final_videos"].extend(final_videos)
            index_groups = group_indices(video_clips, max_duration)
            for idx, group in enumerate(index_groups):
                group_subtitle_files = [os.path.join(output_dir, f"subtitles_{i}.srt") for i in group]
                group_clips = [video_clips[i] for i in group]
                output_subtitle_file = os.path.join(output_dir, f"final_subtitles_part_{idx+1}.srt")
                merged_subtitle = merge_subtitles_group(group_subtitle_files, group_clips, output_subtitle_file)
                processed_entry["final_subtitles"].append(merged_subtitle)

        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)

        processed_entry["processing_completed"] = True
        processed_entry["processed"] = True
        processed_entry["current_step"] = "Completed"

    except Exception as e:
        print(f"Error procesando libro {epub_file}: {e}")
        if epub_file in processed_books:
            processed_entry = processed_books[epub_file]
            processed_entry["error"] = True
            processed_entry["current_step"] = f"Error: {str(e)}"
            save_processed_books(processed_books)

    save_processed_books(processed_books)
    print(f"Procesado: {title if 'title' in locals() else 'Desconocido'}")


def main():
    # 1) Leer el archivo de entrada (books_batch.json)
    with open("books_batch.json", "r", encoding="utf-8") as f:
        books_batch = json.load(f)

    # 2) Leer (o inicializar) el archivo de libros procesados usando load_processed_books()
    processed_books = load_processed_books()

    # 3) Filtrar libros que ya han sido procesados
    books_to_process = [
        book for book in books_batch
        if not any(
            os.path.basename(entry.get("epub_file", "")) == os.path.basename(book.get("epub_file", ""))
            and entry.get("processed")
            for entry in processed_books.values()
        )
    ]

    # 4) Ejecutar procesamiento en paralelo con ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(process_book, book, processed_books): book for book in books_to_process}
        for future in concurrent.futures.as_completed(futures):
            book = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"Error procesando {book.get('epub_file', 'desconocido')}: {e}")

    # 5) Guardar el estado final de los libros procesados
    save_processed_books(processed_books)


if __name__ == "__main__":
    main()
