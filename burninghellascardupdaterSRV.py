import socket
import threading
import hashlib
import os
import json
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

HOST = '0.0.0.0'
PORT = 1337
CARD_FOLDER = r'C:\\KKS\\UserData\\chara\\female\\burning_hellas'
MOD_FOLDER = r'C:\\KKS\\mods'
UPDATE_FOLDER = 'KKCSupdates'
SERVER_VERSION = "0.6.26"
BUFFER_SIZE = 4096


def get_file_info(file_path):
    """Получает информацию о файле: размер, хеш и время изменения."""
    try:
        with open(file_path, 'rb') as file:
            file_hash = hashlib.md5(file.read()).hexdigest()
        return {'size': os.path.getsize(file_path), 'hash': file_hash, 'mtime': os.path.getmtime(file_path)}
    except Exception as error:
        logging.error(f"Ошибка при получении информации о файле {file_path}: {error}")
        return None


def send_file(connection, file_path):
    """Отправляет файл клиенту."""
    try:
        file_size = os.path.getsize(file_path)
        connection.sendall(str(file_size).encode() + b'\n')  # Отправляем размер в байтах
        logging.info(f"Отправка файла {file_path} размером {file_size} байт")

        with open(file_path, 'rb') as file:
            while True:
                data = file.read(BUFFER_SIZE)
                if not data:
                    break
                connection.sendall(data)

        logging.info(f"Файл {file_path} отправлен успешно")
    except Exception as error:
        logging.error(f"Ошибка при отправке файла {file_path}: {error}")



def receive_file(connection, file_path, file_size, modified_time):
    """Получает файл от клиента."""
    try:
        logging.info(f"Получение файла {file_path} размером {file_size} байт")
        with open(file_path, 'wb') as file:
            received_bytes = 0

            while received_bytes < file_size:
                data = connection.recv(BUFFER_SIZE)

                if not data:
                    logging.error("Ошибка: соединение разорвано.")
                    raise ConnectionResetError("Connection reset by peer")

                file.write(data)
                received_bytes += len(data)

        os.utime(file_path, (modified_time, modified_time))
        logging.info(f"Файл {file_path} получен успешно. Время модификации: {modified_time}")

    except Exception as error:
        logging.error(f"Ошибка при получении файла {file_path}: {error}")
        if isinstance(error, ConnectionResetError):
            raise  # Перевыбрасываем исключение, чтобы прервать обработку клиента



def handle_client(connection, address):
    """Обрабатывает запросы клиента."""
    logging.info(f'Подключен клиент: {address}')
    try:
        while True:
            try:
                data = connection.recv(BUFFER_SIZE)
                if not data:
                    break

                try:
                    request = json.loads(data.decode("utf-8", errors="ignore"))
                    command = request.get('command')
                    folder = request.get('folder')


                    if not command:
                        logging.warning("Некорректный запрос: отсутствует 'command'.")
                        continue

                    logging.info(f"Получена команда '{command}' {'для папки ' + folder if folder else ''}")


                    if command == 'check_update':
                        connection.sendall(SERVER_VERSION.encode())


                    elif command == 'get_update':
                        update_file_path = os.path.join(UPDATE_FOLDER, f"BH_CardSync_v{SERVER_VERSION}.exe")
                        if os.path.exists(update_file_path):
                            send_file(connection, update_file_path)
                        else:
                            logging.error(f"Файл обновления {update_file_path} не найден.")
                            connection.sendall(b"0\n")  # Отправляем 0, если файл не найден


                    elif command in ('list_files', 'get_file', 'upload_file'):
                        target_folder = {'cards': CARD_FOLDER, 'mods': MOD_FOLDER}.get(folder)

                        if not target_folder:
                            logging.warning("Некорректный запрос: неверная папка.")
                            connection.sendall(json.dumps({'error': 'Invalid folder specified'}).encode())
                            continue

                        if command == 'list_files':
                            files = {}
                            for filename in os.listdir(target_folder):
                                file_path = os.path.join(target_folder, filename)
                                if os.path.isfile(file_path):
                                    file_info = get_file_info(file_path)
                                    if file_info:
                                        files[filename] = file_info

                            connection.sendall(json.dumps(files, ensure_ascii=False).encode("utf-8"))

                        elif command == 'get_file':
                            filename = request.get('filename')
                            if filename:
                                file_path = os.path.join(target_folder, filename)

                                if os.path.isfile(file_path):
                                    send_file(connection, file_path)
                                else:
                                    logging.warning(f"Запрошенный файл '{filename}' не найден.")
                                    connection.sendall(b"0\n") # Отправляем 0, если файл не найден

                            else:
                                logging.warning("Некорректный запрос 'get_file': нет имени файла.")


                        elif command == 'upload_file':
                            filename = request.get('filename')
                            file_size = int(request.get('size', 0))
                            modified_time = float(request.get('mtime', 0)) # получаем время модификации

                            if filename and file_size > 0:
                                file_path = os.path.join(target_folder, filename)
                                try:
                                    receive_file(connection, file_path, file_size, modified_time) # передаем время модификации
                                except ConnectionResetError:
                                    logging.warning("Клиент разорвал соединение во время загрузки.")

                                    break # Выходим из цикла обработки клиента



                    else:
                        logging.warning(f"Неизвестная команда: '{command}'.")



                except json.JSONDecodeError as error:
                    logging.error(f"Ошибка декодирования JSON: {error}")


            except ConnectionResetError:
                logging.warning("Соединение сброшено клиентом.")
                break # Выходим из цикла обработки клиента

    except Exception as error:
        logging.exception(f"Необработанная ошибка: {error}")

    finally:
        connection.close()
        logging.info(f'Клиент отключен: {address}')


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    logging.info(f'Сервер запущен на порту {PORT}')

    while True:
        client_connection, client_address = server_socket.accept()
        client_thread = threading.Thread(target=handle_client, args=(client_connection, client_address))
        client_thread.start()