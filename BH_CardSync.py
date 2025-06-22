import socket
import hashlib
import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import time
from datetime import datetime
import sys
import argparse
import queue

# Очередь для задач UI, чтобы интерфейс не висел, как говно в проруби.
ui_queue = queue.Queue()

SERVER_ADDRESS = ('ip', port)

if hasattr(sys, 'frozen') and hasattr(sys, '_MEIPASS'):
    script_dir = os.path.dirname(sys.executable)
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(script_dir, 'settings.json')


SYNC_COLORS = {
    "server_newer": "#cb94ff",
    "local_newer": "#ADD8E6",
    "local_only": "#90EE90",
    "server_only": "#D3D3D3"
}

ICONS = {
    'app': '🔥', 'update': '🔄', 'settings': '⚙️', 'help': '❔', 'disk': '💻',
    'server': '☁️', 'upload': '🔼', 'download': '🔽', 'upload_all': '⏫',
    'download_all': '⏬', 'sync': '✨', 'cards': '🃏', 'mods': '🧩'
}

# --- ОСНОВНЫЕ ФУНКЦИИ ---

def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as file:
            settings = json.load(file)
        return settings.get('card_folder'), settings.get('mod_folder')
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None

def save_settings(card_folder, mod_folder):
    settings = {'card_folder': card_folder, 'mod_folder': mod_folder}
    with open(SETTINGS_FILE, 'w') as file:
        json.dump(settings, file, indent=4)

CARD_FOLDER, MOD_FOLDER = load_settings()
action_buttons = []

def set_buttons_state(new_state):
    for btn in action_buttons:
        ui_queue.put(lambda b=btn, s=new_state: b.config(state=s))

def show_color_legend():
    # Код этой функции не изменился, он идеален
    legend_window = tk.Toplevel(window)
    legend_window.title("Справка по цветам")
    legend_window.transient(window)
    legend_window.grab_set()
    legend_window.resizable(False, False)
    text_widget = tk.Text(legend_window, wrap=tk.WORD, height=15, width=60, font=("Segoe UI", 10), relief=tk.FLAT, background=legend_window.cget('bg'))
    text_widget.pack(padx=15, pady=15)
    text_widget.tag_configure("h1", font=("Segoe UI", 12, "bold"))
    text_widget.tag_configure("purple", background=SYNC_COLORS['server_newer'])
    text_widget.tag_configure("blue", background=SYNC_COLORS['local_newer'])
    text_widget.tag_configure("green", background=SYNC_COLORS['local_only'])
    text_widget.tag_configure("gray", background=SYNC_COLORS['server_only'])
    text_widget.insert(tk.END, f"{ICONS['disk']} Статус локальных файлов:\n", "h1")
    text_widget.insert(tk.END, "Обычный: Файл синхронизирован.\n")
    text_widget.insert(tk.END, "Фиолетовый", "purple"); text_widget.insert(tk.END, ": На сервере версия новее. Нужно СКАЧАТЬ.\n")
    text_widget.insert(tk.END, "Голубой", "blue"); text_widget.insert(tk.END, ": Ваша версия новее. Нужно ВЫГРУЗИТЬ.\n")
    text_widget.insert(tk.END, "Зеленый", "green"); text_widget.insert(tk.END, ": Файл есть только у вас. Нужно ВЫГРУЗИТЬ.\n\n")
    text_widget.insert(tk.END, f"{ICONS['server']} Статус файлов на сервере:\n", "h1")
    text_widget.insert(tk.END, "Обычный: Файл синхронизирован.\n")
    text_widget.insert(tk.END, "Серый", "gray"); text_widget.insert(tk.END, ": Файла нет у вас. Нужно СКАЧАТЬ.\n")
    text_widget.config(state=tk.DISABLED)

def _hash_file_in_chunks(filepath):
    md5_hash = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    except IOError:
        return None

def create_connection():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(15)
        sock.connect(SERVER_ADDRESS)
        return sock
    except (socket.error, socket.timeout) as e:
        ui_queue.put(lambda err=e: status_label.config(text=f"Ошибка подключения: {err}"))
        return None

def _recv_line(sock):
    buffer = b''
    while True:
        byte = sock.recv(1)
        if not byte or byte == b'\n':
            return buffer.decode().strip()
        buffer += byte

def _recv_json_message(sock):
    buffer = b''
    open_braces = 0
    in_string = False
    
    while True:
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("Соединение закрыто сервером во время ожидания JSON.")
        
        buffer += byte
        if byte == b'"' and (len(buffer) < 2 or buffer[-2:-1] != b'\\'):
            in_string = not in_string
        elif byte == b'{' and not in_string:
            open_braces += 1
        elif byte == b'}' and not in_string:
            open_braces -= 1
        
        if open_braces == 0 and buffer.strip().startswith(b'{'):
            try:
                return json.loads(buffer.decode('utf-8'))
            except json.JSONDecodeError:
                continue

def update_file_lists():
    if not CARD_FOLDER or not MOD_FOLDER:
        messagebox.showerror("Ошибка", "Пути к папкам не настроены. Укажите их в настройках.")
        return
    set_buttons_state(tk.DISABLED)
    threading.Thread(target=_update_file_lists_thread, daemon=True).start()

def _update_file_lists_thread():
    sock = create_connection()
    if not sock:
        set_buttons_state(tk.NORMAL)
        return
        
    try:
        sock.sendall(json.dumps({'command': 'list_files', 'folder': 'cards'}).encode())
        server_cards = _recv_json_message(sock)
        if 'error' in server_cards:
            raise Exception(server_cards['error'])
        local_cards = _get_local_file_data(CARD_FOLDER)

        sock.sendall(json.dumps({'command': 'list_files', 'folder': 'mods'}).encode())
        server_mods = _recv_json_message(sock)
        if 'error' in server_mods:
            raise Exception(server_mods['error'])
        local_mods = _get_local_file_data(MOD_FOLDER)

        ui_queue.put(lambda: _populate_treeview(local_card_treeview, local_cards))
        ui_queue.put(lambda: _populate_treeview(server_card_treeview, server_cards))
        ui_queue.put(lambda: _populate_treeview(local_mod_treeview, local_mods))
        ui_queue.put(lambda: _populate_treeview(server_mod_treeview, server_mods))
        
        ui_queue.put(lambda: highlight_files_sync_status(local_card_treeview, server_card_treeview))
        ui_queue.put(lambda: highlight_files_sync_status(local_mod_treeview, server_mod_treeview))
        ui_queue.put(lambda: status_label.config(text="Списки обновлены."))

    except Exception as error:
        ui_queue.put(lambda: status_label.config(text=f"Ошибка обновления: {error}"))
    finally:
        if sock:
            sock.close()
        set_buttons_state(tk.NORMAL)

def _get_local_file_data(folder_path):
    local_files = {}
    if not os.path.exists(folder_path):
        return {}
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if os.path.isfile(file_path):
            file_hash = _hash_file_in_chunks(file_path)
            if file_hash:
                local_files[filename] = {
                    'size': os.path.getsize(file_path),
                    'mtime': os.path.getmtime(file_path),
                    'hash': file_hash
                }
    return local_files

def _populate_treeview(treeview, files_data):
    treeview.delete(*treeview.get_children())
    for filename, data in sorted(files_data.items()):
        modified_time_str = datetime.fromtimestamp(data['mtime']).strftime('%Y-%m-%d %H:%M:%S')
        size_mb = round(data['size'] / (1024 * 1024), 2)
        treeview.insert("", tk.END, values=(filename, size_mb, modified_time_str, data['hash'], data['size'], data['mtime']), iid=filename)

def highlight_files_sync_status(local_tree, server_tree):

    local_items = {local_tree.item(iid)['values'][0]: {'hash': local_tree.item(iid)['values'][3], 'mtime': float(local_tree.item(iid)['values'][5])} for iid in local_tree.get_children()}
    server_items = {server_tree.item(iid)['values'][0]: {'hash': server_tree.item(iid)['values'][3], 'mtime': float(server_tree.item(iid)['values'][5])} for iid in server_tree.get_children()}
    
    all_filenames = set(local_items.keys()) | set(server_items.keys())

    for filename in all_filenames:
        local_id = filename if filename in local_items else None
        server_id = filename if filename in server_items else None

        if local_id:
            local_tree.item(local_id, tags=())
        if server_id:
            server_tree.item(server_id, tags=())

        tag = None
        if local_id and not server_id:
            tag = 'local_only'
        elif not local_id and server_id:
            tag = 'server_only'
        elif local_id and server_id:
            local_hash = local_items[filename]['hash']
            server_hash = server_items[filename]['hash']
            if local_hash != server_hash:
                local_mtime = local_items[filename]['mtime']
                server_mtime = server_items[filename]['mtime']
                tag = 'local_newer' if local_mtime > server_mtime else 'server_newer'
        
        if tag:
            if local_id:
                local_tree.item(local_id, tags=(tag,))
            if server_id:
                server_tree.item(server_id, tags=(tag,))

def download_thread(folder_type, files_to_download, callback=None):
    set_buttons_state(tk.DISABLED)
    sock = create_connection()
    if not sock:
        if callback:
            ui_queue.put(callback)
        else:
            set_buttons_state(tk.NORMAL)
        return
        
    try:
        local_folder = CARD_FOLDER if folder_type == "cards" else MOD_FOLDER
        total_size = sum(f['size'] for f in files_to_download)
        bytes_done = 0
        ui_queue.put(lambda: progress_bar.config(maximum=total_size, value=0))

        for file_data in files_to_download:
            filename = file_data['name']
            server_mtime = file_data['mtime']
            temp_path = ""
            try:
                sock.sendall(json.dumps({'command': 'get_file', 'filename': filename, 'folder': folder_type}).encode())
                
                size_str = _recv_line(sock)
                file_size = int(size_str)
                if file_size == 0:
                    ui_queue.put(lambda fn=filename: status_label.config(text=f"Файл '{fn}' не найден на сервере."))
                    continue
                
                temp_path = os.path.join(local_folder, f"{filename}.{int(time.time())}.tmp")
                final_path = os.path.join(local_folder, filename)
                
                if not os.path.exists(local_folder):
                    os.makedirs(local_folder, exist_ok=True)
                
                with open(temp_path, 'wb') as f:
                    received = 0
                    while received < file_size:
                        chunk = sock.recv(min(8192, file_size - received))
                        if not chunk:
                            raise ConnectionError("Соединение разорвано")
                        f.write(chunk)
                        received += len(chunk)
                        bytes_done += len(chunk)
                        ui_queue.put(lambda v=bytes_done: progress_bar.config(value=v))

                os.utime(temp_path, (time.time(), server_mtime))
                os.replace(temp_path, final_path)

            except (ValueError, ConnectionError) as e:
                ui_queue.put(lambda fn=filename, err=e: messagebox.showerror("Ошибка загрузки", f"Не удалось загрузить '{fn}': {err}"))
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
                break
    finally:
        if sock:
            sock.close()
        if callback:
            ui_queue.put(callback)
        else:
            ui_queue.put(lambda: progress_bar.config(value=0))
            update_file_lists()

def upload_thread(folder_type, files_to_upload, callback=None):
    set_buttons_state(tk.DISABLED)
    sock = create_connection()
    if not sock:
        if callback:
            ui_queue.put(callback)
        else:
            set_buttons_state(tk.NORMAL)
        return
        
    try:
        local_folder = CARD_FOLDER if folder_type == "cards" else MOD_FOLDER
        total_size = sum(os.path.getsize(os.path.join(local_folder, f)) for f in files_to_upload)
        bytes_done = 0
        ui_queue.put(lambda: progress_bar.config(maximum=total_size, value=0))

        for filename in files_to_upload:
            file_path = os.path.join(local_folder, filename)
            if not os.path.isfile(file_path):
                continue
            
            try:
                file_size = os.path.getsize(file_path)
                mtime = os.path.getmtime(file_path)
                
                sock.sendall(json.dumps({
                    'command': 'upload_file', 'filename': filename, 'size': file_size, 
                    'folder': folder_type, 'mtime': mtime
                }).encode())
                
                with open(file_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sock.sendall(chunk)
                        bytes_done += len(chunk)
                        ui_queue.put(lambda v=bytes_done: progress_bar.config(value=v))
            except Exception as e:
                ui_queue.put(lambda fn=filename, err=e: messagebox.showerror("Ошибка выгрузки", f"Не удалось выгрузить '{fn}': {err}"))
                break
    finally:
        if sock:
            sock.close()
        if callback:
            ui_queue.put(callback)
        else:
            ui_queue.put(lambda: progress_bar.config(value=0))
            update_file_lists()

def smart_sync_thread(folder_type):
    ui_queue.put(lambda: status_label.config(text=f"Анализ для синхронизации '{folder_type}'..."))
    local_tree = local_card_treeview if folder_type == "cards" else local_mod_treeview
    server_tree = server_card_treeview if folder_type == "cards" else server_mod_treeview
    
    files_to_download_data = [{'name': server_tree.item(iid)['values'][0], 'size': int(server_tree.item(iid)['values'][4]), 'mtime': float(server_tree.item(iid)['values'][5])} for iid in server_tree.get_children() if 'server_newer' in server_tree.item(iid, 'tags') or 'server_only' in server_tree.item(iid, 'tags')]
    files_to_upload_data = [ local_tree.item(iid)['values'][0] for iid in local_tree.get_children() if 'local_newer' in local_tree.item(iid, 'tags') or 'local_only' in local_tree.item(iid, 'tags')]

    if not files_to_download_data and not files_to_upload_data:
        ui_queue.put(lambda: messagebox.showinfo("Синхронизация", "Все файлы уже синхронизированы!"))
        return

    def final_update():
        ui_queue.put(lambda: status_label.config(text="Синхронизация завершена. Обновляю списки..."))
        update_file_lists()

    def run_uploads():
        if files_to_upload_data:
            ui_queue.put(lambda: status_label.config(text=f"Выгрузка {len(files_to_upload_data)} файлов..."))
            threading.Thread(target=upload_thread, args=(folder_type, files_to_upload_data, final_update), daemon=True).start()
        else:
            final_update()
    
    if files_to_download_data:
        ui_queue.put(lambda: status_label.config(text=f"Загрузка {len(files_to_download_data)} файлов..."))
        threading.Thread(target=download_thread, args=(folder_type, files_to_download_data, run_uploads), daemon=True).start()
    else:
        run_uploads()

def download_selected(folder_type, update_all=False):
    server_tree = server_card_treeview if folder_type == "cards" else server_mod_treeview
    iids = server_tree.get_children() if update_all else server_tree.selection()
    if not iids:
        messagebox.showinfo("Инфа", "Файлы для загрузки не выбраны.")
        return
        
    files_data = [{'name': server_tree.item(iid)['values'][0], 'size': int(server_tree.item(iid)['values'][4]), 'mtime': float(server_tree.item(iid)['values'][5])} for iid in iids]
    threading.Thread(target=download_thread, args=(folder_type, files_data, None), daemon=True).start()

def upload_selected(folder_type, update_all=False):
    local_tree = local_card_treeview if folder_type == "cards" else local_mod_treeview
    iids = local_tree.get_children() if update_all else local_tree.selection()
    if not iids:
        messagebox.showinfo("Инфа", "Файлы для выгрузки не выбраны.")
        return
    files_data = [local_tree.item(iid)['values'][0] for iid in iids]
    threading.Thread(target=upload_thread, args=(folder_type, files_data, None), daemon=True).start()

def start_smart_sync(folder_type):
    if messagebox.askokcancel("Умная синхронизация", f"Начать умную синхронизацию для '{folder_type}'?"):
        threading.Thread(target=smart_sync_thread, args=(folder_type,), daemon=True).start()

def change_folders():
    global CARD_FOLDER, MOD_FOLDER
    new_card_folder = filedialog.askdirectory(title="Выберите папку для КАРТОЧЕК", initialdir=CARD_FOLDER)
    if new_card_folder:
        new_mod_folder = filedialog.askdirectory(title="Выберите папку для МОДОВ", initialdir=MOD_FOLDER)
        if new_mod_folder:
            CARD_FOLDER, MOD_FOLDER = os.path.abspath(new_card_folder), os.path.abspath(new_mod_folder)
            save_settings(CARD_FOLDER, MOD_FOLDER)
            ui_queue.put(lambda: status_label.config(text="Папки изменены. Обновление..."))
            update_file_lists()

def create_sync_tab(parent, title, folder_type):
    tab_frame = ttk.Frame(parent)
    parent.add(tab_frame, text=f"{ICONS.get(folder_type, '')} {title}")
    main_frame = ttk.Frame(tab_frame)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    local_tree_frame = ttk.Frame(main_frame)
    server_tree_frame = ttk.Frame(main_frame)
    local_tree_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 5))
    server_tree_frame.grid(row=1, column=1, sticky="nsew", padx=(5, 0))

    ttk.Label(main_frame, text=f"{ICONS.get('disk', '')} На диске:").grid(row=0, column=0, sticky=tk.W)
    ttk.Label(main_frame, text=f"{ICONS.get('server', '')} На сервере:").grid(row=0, column=1, sticky=tk.W, padx=5)

    local_tree = ttk.Treeview(local_tree_frame, columns=("Name", "Size (MB)", "Modified", "Hash", "Bytes", "Mtime_ts"), show="headings")
    local_scroll = ttk.Scrollbar(local_tree_frame, orient="vertical", command=local_tree.yview)
    local_tree.configure(yscrollcommand=local_scroll.set)
    local_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    local_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    
    server_tree = ttk.Treeview(server_tree_frame, columns=("Name", "Size (MB)", "Modified", "Hash", "Bytes", "Mtime_ts"), show="headings")
    server_scroll = ttk.Scrollbar(server_tree_frame, orient="vertical", command=server_tree.yview)
    server_tree.configure(yscrollcommand=server_scroll.set)
    server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    server_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    for tree in [local_tree, server_tree]:
        tree.heading("Name", text="Имя файла")
        tree.heading("Size (MB)", text="Размер(МБ)")
        tree.heading("Modified", text="Дата")
        tree.column("Name", width=250)
        tree.column("Size (MB)", width=80, anchor=tk.E)
        tree.column("Modified", width=140, anchor=tk.CENTER)
        tree.column("Hash", width=0, stretch=tk.NO)
        tree.column("Bytes", width=0, stretch=tk.NO)
        tree.column("Mtime_ts", width=0, stretch=tk.NO)

    upload_btn = ttk.Button(main_frame, text=f"{ICONS.get('upload', '')} Выгрузить", command=lambda: upload_selected(folder_type))
    upload_btn.grid(row=2, column=0, pady=(5,0), sticky=tk.EW, padx=(0,5))
    upload_all_btn = ttk.Button(main_frame, text=f"{ICONS.get('upload_all', '')} Выгрузить ВСЁ", command=lambda: upload_selected(folder_type, update_all=True))
    upload_all_btn.grid(row=3, column=0, pady=(5,0), sticky=tk.EW, padx=(0,5))
    
    download_btn = ttk.Button(main_frame, text=f"{ICONS.get('download', '')} Загрузить", command=lambda: download_selected(folder_type))
    download_btn.grid(row=2, column=1, pady=(5,0), sticky=tk.EW, padx=(5,0))
    download_all_btn = ttk.Button(main_frame, text=f"{ICONS.get('download_all', '')} Загрузить ВСЁ", command=lambda: download_selected(folder_type, update_all=True))
    download_all_btn.grid(row=3, column=1, pady=(5,0), sticky=tk.EW, padx=(5,0))
    
    sync_btn = ttk.Button(main_frame, text=f"{ICONS.get('sync', '')} УМНАЯ СИНХРОНИЗАЦИЯ", command=lambda: start_smart_sync(folder_type))
    sync_btn.grid(row=4, column=0, columnspan=2, pady=(10,0), sticky=tk.EW)

    main_frame.columnconfigure(0, weight=1)
    main_frame.columnconfigure(1, weight=1)
    main_frame.rowconfigure(1, weight=1)
    action_buttons.extend([upload_btn, upload_all_btn, download_btn, download_all_btn, sync_btn])
    return local_tree, server_tree

if __name__ == '__main__':
    window = tk.Tk()
    window.title(f"{ICONS.get('app', '')} Hellish Sync App")
    window.geometry("1200x700")
    if not CARD_FOLDER or not MOD_FOLDER:
        messagebox.showinfo("Первый запуск", "Похоже, это первый запуск. Пожалуйста, укажите пути к папкам с картами и модами.")
        change_folders()

    top_frame = ttk.Frame(window)
    top_frame.pack(fill=tk.X, padx=5, pady=5)
    update_button = ttk.Button(top_frame, text=f"{ICONS.get('update', '')} Обновить", command=update_file_lists)
    update_button.pack(side=tk.LEFT, padx=(0, 5))
    action_buttons.append(update_button)
    change_folder_button = ttk.Button(top_frame, text=f"{ICONS.get('settings', '')} Папки", command=change_folders)
    change_folder_button.pack(side=tk.LEFT, padx=(0, 5))
    action_buttons.append(change_folder_button)
    help_button = ttk.Button(top_frame, text=f"{ICONS.get('help', '')} Справка", command=show_color_legend)
    help_button.pack(side=tk.LEFT, padx=(0, 10))
    status_label = ttk.Label(top_frame, text="Готов к работе", anchor=tk.W)
    status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    progress_bar = ttk.Progressbar(window, mode='determinate')
    progress_bar.pack(fill=tk.X, padx=5, pady=(0, 5))
    notebook = ttk.Notebook(window)
    notebook.pack(pady=5, fill=tk.BOTH, expand=True, padx=5)
    
    local_card_treeview, server_card_treeview = create_sync_tab(notebook, "Карточки", "cards")
    local_mod_treeview, server_mod_treeview = create_sync_tab(notebook, "Моды", "mods")

    for tree in [local_card_treeview, server_card_treeview, local_mod_treeview, server_mod_treeview]:
        for tag, color in SYNC_COLORS.items():
            tree.tag_configure(tag, background=color)

    if CARD_FOLDER and MOD_FOLDER:
        update_file_lists()
    
    window.protocol("WM_DELETE_WINDOW", window.destroy)

    def process_ui_queue():
        try:
            while True:
                task = ui_queue.get_nowait()
                task()
        except queue.Empty:
            pass
        window.after(50, process_ui_queue)

    window.after(50, process_ui_queue)
    window.mainloop()