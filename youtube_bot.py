import yt_dlp
import telebot
from telebot import types
import os
import uuid
import traceback

# --- Configuración ---
Token = os.environ.get("BOT_TOKEN") # Reemplaza con tu token real
bot = telebot.TeleBot(Token)

RUTA_DESCARGA = "/tmp/descargas"
FFMPEG_PATH = "/usr/bin/ffmpeg"
TELEGRAM_MAX_SIZE_MB = 50 

if not os.path.exists(RUTA_DESCARGA):
    os.makedirs(RUTA_DESCARGA)

# Diccionario global para mapear IDs → enlaces
pendientes = {}

# Función de validación de enlaces
def es_enlace_youtube(enlace):
    return any(x in enlace for x in ['youtube.com/watch?v=', 'youtu.be/', 'youtube.com/shorts/'])

# Manejador de mensajes entrantes (enlaces)
@bot.message_handler(func=lambda message: True)
def recibir_enlace(message):
    enlace = message.text.strip()
    chat_id = message.chat.id
    message_id = message.message_id

    if not es_enlace_youtube(enlace):
        bot.reply_to(message, "⚠️ Solo acepto enlaces de YouTube.")
        return

    # NUEVO: Eliminar el mensaje del usuario que contenía el enlace
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        print(f"No se pudo borrar el mensaje {message_id} del chat {chat_id}: {e}")

    # Generar un ID corto para este pedido
    pedido_id = str(uuid.uuid4())[:8]
    pendientes[pedido_id] = enlace

    # Crear botones inline
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_mp3 = types.InlineKeyboardButton("🎵 Mp3", callback_data=f"mp3|{pedido_id}")
    btn_mp4 = types.InlineKeyboardButton("🎬 Mp4", callback_data=f"mp4|{pedido_id}")
    markup.add(btn_mp3, btn_mp4)

    # Enviar mensaje con botones
    bot.send_message(
        chat_id,
        "¿En qué formato quieres descargarlo?",
        reply_markup=markup,
        parse_mode="Markdown" # Para que el enlace se vea bien
    )

# Manejador de respuestas a los botones
@bot.callback_query_handler(func=lambda call: True)
def procesar_callback(call):
    filename = None 
    chat_id = call.message.chat.id
    # MODIFICADO: Guardamos el ID del mensaje de estado para poder editarlo o borrarlo
    status_message_id = call.message.message_id
    
    try:
        tipo, pedido_id = call.data.split('|')
        enlace = pendientes.pop(pedido_id, None) 

        if not enlace:
            bot.answer_callback_query(call.id, "❌ Este pedido ya ha sido procesado o ha expirado.")
            bot.edit_message_text("Este pedido ya no es válido.", chat_id, status_message_id, reply_markup=None)
            return

        bot.answer_callback_query(call.id, f"Descargando {tipo.upper()}…")
        # MODIFICADO: El mensaje de los botones se reemplaza por el de "Procesando..."
        bot.edit_message_text("Procesando tu descarga… ⏳", chat_id, status_message_id, reply_markup=None)

        output_template = os.path.join(RUTA_DESCARGA, f'{pedido_id}.%(ext)s')

        if tipo == 'mp3':
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
                'ffmpeg_location': FFMPEG_PATH,
                'outtmpl': output_template,
                'noplaylist': True,
            }
        else:  # mp4
            ydl_opts = {
                'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'ffmpeg_location': FFMPEG_PATH,
                'outtmpl': output_template,
                'noplaylist': True,
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(enlace, download=True)
            filename = info.get('requested_downloads')[0].get('filepath')

        if not filename or not os.path.exists(filename):
            # MODIFICADO: Editamos el mensaje de estado con el error
            bot.edit_message_text("❌ No pude encontrar el archivo descargado después del proceso.", chat_id, status_message_id)
            return

        file_size_mb = os.path.getsize(filename) / (1024 * 1024)
        if file_size_mb > TELEGRAM_MAX_SIZE_MB:
            error_msg = (
                f"❌ ¡El archivo es demasiado grande! Pesa {file_size_mb:.2f} MB.\n"
                f"Telegram solo me permite enviar archivos de hasta {TELEGRAM_MAX_SIZE_MB} MB."
            )
            # MODIFICADO: Editamos el mensaje de estado con el error
            bot.edit_message_text(error_msg, chat_id, status_message_id)
            return 

        # MODIFICADO: El mensaje de "Procesando" se reemplaza por "Subiendo..."
        bot.edit_message_text("Subiendo archivo...", chat_id, status_message_id)
        
        with open(filename, 'rb') as f:
            if tipo == 'mp3':
                bot.send_audio(chat_id, f, title=info.get('title'))
            else: # mp4
                bot.send_video(
                    chat_id,
                    f,
                    caption=f"{info.get('title')}",
                    supports_streaming=True
                )
        
        # NUEVO: En lugar de editar a "Listo!", borramos el mensaje de estado.
        # Esto deja el chat limpio con solo el archivo final.
        bot.delete_message(chat_id, status_message_id)

    except Exception as e:
        # MODIFICADO: En caso de cualquier otro error, se edita el mensaje de estado
        # en lugar de enviar uno nuevo.
        error_message = "⚠️ Ocurrió un error inesperado al procesar tu solicitud."
        try:
            bot.edit_message_text(error_message, chat_id, status_message_id)
        except Exception as api_e:
            # Si editar falla (p.ej. el mensaje es muy viejo), se envía uno nuevo como fallback
            bot.send_message(chat_id, error_message)
            print(f"Error al editar mensaje, se envió uno nuevo. API Error: {api_e}")

        print("--- INICIO DEL ERROR ---")
        traceback.print_exc()
        print("--- FIN DEL ERROR ---")

    finally:
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except OSError as e:
                print(f"Error al eliminar el archivo {filename}: {e}")

# Inicio del bot
if __name__ == '__main__':
    if not os.path.exists(RUTA_DESCARGA):
        os.makedirs(RUTA_DESCARGA)
        
    print("🎶 Bot descargador de YouTube iniciado.")
    bot.infinity_polling(skip_pending=True)