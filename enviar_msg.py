import os
import asyncio
import subprocess
import shutil
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeAudio
from telethon.utils import encode_waveform


# ============================================================
# CONFIGURACIÓN
# ============================================================

API_ID = 23778764 
API_HASH = "6d4041b9eea446e532c739f44bec7118" 

CANAL = "@EvelynHotOficial"

SESSION_NAME = "telegram_session"

# Texto opcional que aparece encima de la nota de voz ("" = sin texto)
CAPTION = ""


# ============================================================
# BUSCAR FFMPEG Y FFPROBE
# ============================================================

def encontrar_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    rutas_posibles = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    ]
    for ruta in rutas_posibles:
        if os.path.isfile(ruta):
            return ruta

    print("\n⚠️ No se encontró FFmpeg automáticamente.")
    print(r"Ejemplo: C:\ffmpeg\bin\ffmpeg.exe")
    ruta = input("\n📍 Ruta de ffmpeg.exe: ").strip().strip('"').strip("'")

    if os.path.isfile(ruta):
        return ruta

    print("\n❌ No se encontró ffmpeg.exe en esa ubicación.")
    return None


def encontrar_ffprobe(ffmpeg_path):
    ffprobe_path = str(Path(ffmpeg_path).with_name("ffprobe.exe"))
    if os.path.isfile(ffprobe_path):
        return ffprobe_path
    return shutil.which("ffprobe")


def ejecutar(comando, binario=False):
    """Ejecuta un comando y decodifica la salida en UTF-8 sin fallar por acentos."""
    if binario:
        return subprocess.run(comando, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    return subprocess.run(comando, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,
                          encoding="utf-8", errors="replace")


# ============================================================
# COMPROBAR SI EL VIDEO TIENE AUDIO
# ============================================================

def tiene_audio(ffmpeg_path, video_path):
    ffprobe_path = encontrar_ffprobe(ffmpeg_path)
    if not ffprobe_path:
        return True  # no se puede comprobar; se intenta igual

    comando = [
        ffprobe_path, "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_name",
        "-of", "csv=p=0",
        video_path
    ]
    try:
        r = ejecutar(comando)
        return bool(r.stdout.strip())
    except Exception:
        return True


# ============================================================
# OBTENER DURACIÓN DEL AUDIO
# ============================================================

def obtener_duracion(ffmpeg_path, audio_path):
    ffprobe_path = encontrar_ffprobe(ffmpeg_path)
    if not ffprobe_path:
        print("⚠️ No se encontró ffprobe. Se usará duración 0.")
        return 0

    comando = [
        ffprobe_path, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    try:
        r = ejecutar(comando)
        if r.returncode == 0:
            return int(round(float(r.stdout.strip())))
    except Exception:
        pass
    return 0


# ============================================================
# EXTRAER AUDIO DEL VIDEO -> OGG OPUS (formato de nota de voz)
# ============================================================

def extraer_audio(ffmpeg_path, video_path, audio_path):
    print("\n🎬 Extrayendo audio...")
    print(f"📹 Video: {Path(video_path).name}")

    if not tiene_audio(ffmpeg_path, video_path):
        print("\n❌ El video no tiene pista de audio.")
        print("   Vuelve a grabar con el micrófono o el audio del sistema activado.")
        return False

    comando = [
        ffmpeg_path, "-y", "-hide_banner",
        "-i", video_path,
        "-vn",                 # sin video
        "-map_metadata", "-1", # quitar metadatos (título, etc.)
        "-c:a", "libopus",     # códec de las notas de voz de Telegram
        "-b:a", "64k",
        "-ac", "1",            # mono
        "-ar", "48000",
        "-application", "voip",
        audio_path
    ]

    try:
        r = ejecutar(comando)
    except FileNotFoundError:
        print("\n❌ Windows no pudo ejecutar FFmpeg.")
        print(f"Ruta utilizada: {ffmpeg_path}")
        return False

    if r.returncode != 0:
        print(f"\n❌ FFmpeg encontró un error (código {r.returncode}):\n")
        print(r.stderr or r.stdout or "(FFmpeg no devolvió ningún mensaje)")
        if "libopus" in (r.stderr or ""):
            print("\n💡 Tu FFmpeg no incluye libopus. Descarga una versión 'full' "
                  "desde gyan.dev o BtbN (GitHub).")
        return False

    if not os.path.isfile(audio_path):
        print("\n❌ FFmpeg terminó, pero no creó el archivo de audio.")
        return False

    print("✅ Audio extraído correctamente.")
    return True


# ============================================================
# GENERAR LA ONDA (WAVEFORM) QUE MUESTRA TELEGRAM
# ============================================================

def generar_waveform(ffmpeg_path, audio_path, barras=100):
    comando = [
        ffmpeg_path, "-v", "error",
        "-i", audio_path,
        "-f", "s16le", "-ac", "1", "-ar", "8000",
        "-"
    ]
    try:
        r = ejecutar(comando, binario=True)
        datos = r.stdout
    except Exception:
        return None

    n = len(datos) // 2
    if n == 0:
        return None

    muestras = memoryview(datos[:n * 2]).cast("h")
    tam = max(1, n // barras)

    picos = []
    for i in range(barras):
        trozo = muestras[i * tam:(i + 1) * tam]
        picos.append(max((abs(x) for x in trozo), default=0))

    maximo = max(picos) or 1
    valores = bytes(min(31, int(p * 31 / maximo)) for p in picos)  # 0..31 (5 bits)

    return encode_waveform(valores)


# ============================================================
# ENVIAR NOTA DE VOZ A TELEGRAM
# ============================================================

async def enviar_audio(client, audio_path, duracion, waveform):
    print("\n📤 Enviando nota de voz a Telegram...")

    try:
        await client.send_file(
            CANAL,
            audio_path,
            caption=CAPTION,
            voice_note=True,
            attributes=[
                DocumentAttributeAudio(
                    duration=duracion,
                    voice=True,
                    waveform=waveform
                )
            ]
        )
        print("✅ Nota de voz enviada correctamente al canal.")
        return True

    except Exception as e:
        print("\n❌ Error enviando el audio:")
        print(e)
        return False


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

async def main():
    print("=" * 60)
    print("🎬 VIDEO → NOTA DE VOZ → TELEGRAM")
    print("=" * 60)

    if not API_ID:
        print("\n❌ Debes colocar tu API_ID.")
        return
    if API_HASH in ("", "PON_AQUI_TU_API_HASH"):
        print("\n❌ Debes colocar tu API_HASH.")
        return

    ffmpeg_path = encontrar_ffmpeg()
    if not ffmpeg_path:
        print("\n❌ No se puede continuar sin FFmpeg.")
        return
    print(f"\n✅ FFmpeg encontrado:\n{ffmpeg_path}")

    video_path = input("\n📁 Introduce la ruta del video: ").strip().strip('"').strip("'")
    if not os.path.isfile(video_path):
        print(f"\n❌ No se encontró el archivo.\nRuta indicada:\n{video_path}")
        return

    video = Path(video_path)
    audio_path = video.parent / f"{video.stem}_voz.ogg"

    if not extraer_audio(ffmpeg_path, str(video), str(audio_path)):
        return

    print("\n⏱️ Calculando duración del audio...")
    duracion = obtener_duracion(ffmpeg_path, str(audio_path))
    print(f"⏱️ Duración: {duracion} segundos")

    print("〰️ Generando forma de onda...")
    waveform = generar_waveform(ffmpeg_path, str(audio_path))

    print("\n🔐 Conectando con tu cuenta de Telegram...")
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    try:
        await client.start()
        print("✅ Sesión de Telegram iniciada.")

        enviado = await enviar_audio(client, str(audio_path), duracion, waveform)

        if enviado:
            try:
                os.remove(audio_path)
                print("🗑️ Audio temporal eliminado.")
            except Exception as e:
                print(f"\n⚠️ No se pudo eliminar el archivo: {e}")
    finally:
        await client.disconnect()

    print("\n" + "=" * 60)
    print("🏁 PROCESO TERMINADO")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())