import http.server
import socketserver
import argparse
import sys
import json
import subprocess
import os
import threading
import time
import uuid
import re
import urllib.parse
import shutil
import ctypes
from PIL import Image
import pystray

# --- CONFIGURACIÓN DE RUTAS ---
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    WEB_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WEB_DIR = BASE_DIR

DOWNLOADS_DIR = os.path.join(BASE_DIR, 'Downloads')
TEMP_DIR = os.path.join(BASE_DIR, 'Temp')
THUMBS_DIR = os.path.join(BASE_DIR, 'Thumbs') # Nueva carpeta para persistencia de metadatos
YT_DLP_PATH = os.path.join(BASE_DIR, 'Tools', 'yt-dlp.exe')

for d in [DOWNLOADS_DIR, TEMP_DIR, THUMBS_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# --- SYSTEM TRAY & CONSOLE UTILS ---
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
SW_HIDE = 0
SW_SHOW = 5

def get_console_window():
    return kernel32.GetConsoleWindow()

def hide_console(icon=None, item=None):
    win = get_console_window()
    if win:
        user32.ShowWindow(win, SW_HIDE)

def show_console(icon=None, item=None):
    win = get_console_window()
    if win:
        user32.ShowWindow(win, SW_SHOW)
        user32.SetForegroundWindow(win)

def on_exit(icon, item):
    icon.stop()
    manager.stop_event.set()
    os._exit(0)

# --- GESTOR DE ESTADO ---
class DownloadManager:
    def __init__(self):
        self.queue = []          
        self.current_task = None 
        self.current_process = None 
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def add_to_queue(self, url, title, thumbnail, format_type='video', quality='best'):
        with self.lock:
            task = {
                'id': str(uuid.uuid4()),
                'url': url,
                'title': title or url,
                'thumbnail': thumbnail,
                'format_type': format_type,
                'quality': quality,
                'status': 'pending',
                'added_at': time.time()
            }
            self.queue.append(task)
            return task

    def get_history_files(self):
        try:
            files = []
            if os.path.exists(DOWNLOADS_DIR):
                for f in os.listdir(DOWNLOADS_DIR):
                    full_path = os.path.join(DOWNLOADS_DIR, f)
                    if os.path.isfile(full_path) and f.lower().endswith(('.mp3', '.mp4', '.mkv', '.webm', '.m4a')):
                        # Buscar metadatos en Thumbs
                        # Convención: Si archivo es "Video.mp4", thumb es "Video.mp4.jpg" y json "Video.mp4.json"
                        thumb_name = f + ".jpg"
                        json_name = f + ".json"
                        thumb_path = os.path.join(THUMBS_DIR, thumb_name)
                        json_path = os.path.join(THUMBS_DIR, json_name)
                        
                        thumb_url = None
                        quality_str = None
                        
                        if os.path.exists(thumb_path):
                            thumb_url = f"/thumbs/{urllib.parse.quote(thumb_name)}"
                        
                        if os.path.exists(json_path):
                            try:
                                with open(json_path, 'r', encoding='utf-8') as jf:
                                    meta = json.load(jf)
                                    # Intentar extraer info de calidad relevante
                                    # Audio: abr (kbps). Video: height (p) o format_note
                                    if f.endswith('.mp3'):
                                        abr = meta.get('abr')
                                        if abr: quality_str = f"{int(abr)} kbps"
                                    else:
                                        height = meta.get('height')
                                        if height: quality_str = f"{height}p"
                                        elif meta.get('format_note'): quality_str = meta.get('format_note')
                            except: pass

                        files.append({
                            'filename': f,
                            'title': f,
                            'mtime': os.path.getmtime(full_path),
                            'status': 'completed',
                            'thumbnail': thumb_url, # Puede ser None
                            'quality_str': quality_str, 
                            'format_type': 'audio' if f.endswith('.mp3') else 'video'
                        })
            files.sort(key=lambda x: x['mtime'], reverse=True)
            return files
        except Exception as e:
            print(f"Error hist: {e}")
            return []

    def get_state(self):
        with self.lock:
            return {
                'current_task': self.current_task,
                'queue': self.queue,
                'history': self.get_history_files()
            }

    def cancel_current(self):
        with self.lock:
            if self.current_process:
                try: self.current_process.terminate() 
                except: pass
                return True
        return False

    def remove_from_queue(self, task_id):
        with self.lock:
            initial_len = len(self.queue)
            self.queue = [t for t in self.queue if t['id'] != task_id]
            return len(self.queue) < initial_len

manager = DownloadManager()

# --- WORKER THREAD ---
def download_worker():
    while not manager.stop_event.is_set():
        task_to_process = None
        with manager.lock:
            if not manager.current_task and manager.queue:
                task_to_process = manager.queue.pop(0)
                task_to_process['status'] = 'downloading'
                task_to_process['progress'] = 0
                manager.current_task = task_to_process
        
        if task_to_process:
            print(f"Worker: Download {task_to_process['url']}")
            # OUTPUT TEMPLATE: Usamos %(title)s.%(ext)s PERO yt-dlp añade extensiones para thumb y json
            output_template = os.path.join(TEMP_DIR, '%(title)s.%(ext)s')
            
            command = [
                YT_DLP_PATH, 
                '--newline', 
                '--progress', 
                '--no-mtime', 
                '--restrict-filenames',
                '--write-thumbnail', 
                '--convert-thumbnails', 'jpg', 
                '--write-info-json',
                '--no-playlist', # FIX: Evitar que baje la lista entera y parezca colgado
                '--extractor-args', 'youtube:player_client=default' # FIX: Suprimir warning de JS
            ]
            
            ftype = task_to_process.get('format_type', 'video')
            qual = task_to_process.get('quality', 'best')

            if ftype == 'audio':
                command.extend(['-x', '--audio-format', 'mp3'])
                command.extend(['--audio-quality', qual if qual else '0'])
            else:
                if qual and qual != 'best':
                    f_str = f"bestvideo[height<={qual}]+bestaudio/best[height<={qual}]"
                    command.extend(['-f', f_str])
                else:
                    command.extend(['-f', 'bestvideo+bestaudio/best'])
                command.extend(['--merge-output-format', 'mkv'])

            command.extend(['-o', output_template, task_to_process['url']])

            try:
                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace'
                )
                with manager.lock: manager.current_process = process
                
                final_temp_video = None
                
                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None: break
                    if line:
                        match = re.search(r'(\d+\.\d+)%', line)
                        if match:
                            try:
                                percent = float(match.group(1))
                                with manager.lock:
                                    if manager.current_task: manager.current_task['progress'] = percent
                            except: pass
                        if '] Destination:' in line:
                             parts = line.split('] Destination:', 1)
                             if len(parts) > 1: final_temp_video = parts[1].strip()
                        elif '] Merging formats into' in line:
                             parts = line.split('] Merging formats into', 1)
                             if len(parts) > 1: final_temp_video = parts[1].strip().strip('"')

                rc = process.poll()
                with manager.lock:
                    manager.current_process = None
                    if rc == 0:
                        # EXITO
                        # Intentar fallback para encontrar video si no se parseó
                        if not final_temp_video:
                            # Buscar el archivo más nuevo en TEMP
                            try:
                                files = [os.path.join(TEMP_DIR, f) for f in os.listdir(TEMP_DIR)]
                                files = [f for f in files if os.path.isfile(f) and f.endswith(('.mp4','.mk4','.mkv','.webm','.mp3'))]
                                if files: final_temp_video = max(files, key=os.path.getmtime)
                            except: pass

                        if final_temp_video and os.path.exists(final_temp_video):
                             basename = os.path.basename(final_temp_video)
                             rootname = os.path.splitext(basename)[0] # Nombre sin extension
                             
                             # Mover VIDEO
                             dest_video = os.path.join(DOWNLOADS_DIR, basename)
                             if os.path.exists(dest_video): os.remove(dest_video)
                             shutil.move(final_temp_video, dest_video)
                             print(f"[OK] Video movido: {basename}")

                             # Buscar y Mover THUMBNAIL (.jpg)
                             # yt-dlp suele generar 'Nombre.jpg' o 'Nombre.mp3.jpg' a veces
                             # Buscaremos archivos en TEMP que empiecen por rootname y terminen en .jpg
                             # Pero cuidado con coincidencias parciales.
                             # Lo más seguro: buscar 'rootname.jpg' o 'rootname.webp' etc
                             
                             # Estrategia: Listar TEMP y buscar matches
                             try:
                                 for tfile in os.listdir(TEMP_DIR):
                                     tpath = os.path.join(TEMP_DIR, tfile)
                                     # Si es un archivo generado para este video (starts with rootname)
                                     # Y es .jpg o .info.json
                                     if tfile.startswith(rootname):
                                         if tfile.endswith('.jpg'):
                                             # Mover a Thumbs/BASENAME_ENTERO.jpg (ej: Video.mp4.jpg)
                                             dest_thumb = os.path.join(THUMBS_DIR, basename + ".jpg")
                                             if os.path.exists(dest_thumb): os.remove(dest_thumb)
                                             shutil.move(tpath, dest_thumb)
                                         
                                         elif tfile.endswith('.info.json'):
                                             # Mover a Thumbs/BASENAME_ENTERO.json
                                             dest_json = os.path.join(THUMBS_DIR, basename + ".json")
                                             if os.path.exists(dest_json): os.remove(dest_json)
                                             shutil.move(tpath, dest_json)
                             except Exception as e:
                                 print(f"Error moviendo meta: {e}")

                    else:
                        print(f"Error download code: {rc}")
                        if process.stderr: print(process.stderr.read())
                    
                    manager.current_task = None
            except Exception as e:
                print(f"Worker Exception: {e}")
                with manager.lock: manager.current_task = None
        else:
            time.sleep(1)

# --- HANDLER HTTP ---
class APIServer(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        # Evitar crash si args[0] no es string (ej: HTTPStatus)
        if args and isinstance(args[0], str) and "GET /api/state" in args[0]:
            return
        # super().log_message(format, *args)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        
        if parsed.path == '/api/state':
            self._send_json(manager.get_state())
            return
            
        if parsed.path.startswith('/downloads/'):
            filename = urllib.parse.unquote(parsed.path[len('/downloads/'):])
            file_path = os.path.join(DOWNLOADS_DIR, filename)
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(os.path.getsize(file_path)))
                self.end_headers()
                with open(file_path, 'rb') as f: shutil.copyfileobj(f, self.wfile)
                return
            else:
                self.send_error(404)
                return

        if parsed.path.startswith('/thumbs/'):
            filename = urllib.parse.unquote(parsed.path[len('/thumbs/'):])
            file_path = os.path.join(THUMBS_DIR, filename)
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg") # Asumimos JPG por el --convert-thumbnails
                self.send_header("Content-Length", str(os.path.getsize(file_path)))
                self.end_headers()
                with open(file_path, 'rb') as f: shutil.copyfileobj(f, self.wfile)
                return
            else:
                self.send_error(404)
                return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/queue':
            data = self._read_json()
            if data:
                task = manager.add_to_queue(data.get('url'), data.get('title'), data.get('thumbnail'), data.get('format_type'), data.get('quality'))
                self._send_json({'message': 'OK', 'task': task})
            return
        if parsed.path == '/api/cancel':
            manager.cancel_current()
            self._send_json({'message': 'OK'})
            return
        self.send_error(404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith('/api/queue/'):
            manager.remove_from_queue(parsed.path.split('/')[-1])
            self._send_json({'message': 'OK'})
            return
        self.send_error(404)

    def _read_json(self):
        try:
            return json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        except: return None

    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

# --- MAIN ---
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5900)
    args = parser.parse_args()

    # Clean Temp on start? Maybe safer to leave manual cleanup
    if os.path.exists(TEMP_DIR):
        try: shutil.rmtree(TEMP_DIR); os.makedirs(TEMP_DIR)
        except: pass

    def run_server():
        print(f"Server corriendo en port {args.port}...")
        with socketserver.TCPServer(("", args.port), APIServer) as httpd:
            httpd.timeout = 1 
            while not manager.stop_event.is_set():
                httpd.handle_request()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    worker_thread = threading.Thread(target=download_worker, daemon=True)
    worker_thread.start()

    print("Iniciando System Tray (v5 - Thumbs)...")
    try:
        icon_path = os.path.join(WEB_DIR, 'assets', 'app_icon.png')
        if not os.path.exists(icon_path):
             icon_path = os.path.join(BASE_DIR, 'assets', 'app_icon.png')
        
        image = Image.open(icon_path)
        
        menu = pystray.Menu(
            pystray.MenuItem("DNX Youtuber Downloader", lambda: None, enabled=False),
            pystray.MenuItem("Abrir Web", lambda: subprocess.Popen(f"start http://localhost:{args.port}", shell=True)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Ocultar Consola", hide_console),
            pystray.MenuItem("Mostrar Consola", show_console),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", on_exit)
        )

        icon = pystray.Icon("DNXDownloader", image, "DNX Youtuber Downloader", menu)
        icon.run()

    except Exception as e:
        print(f"Error Tray: {e}")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
