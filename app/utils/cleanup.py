import os

def cleanup_upload_folder(file_paths):
    """
    Удаляет все указанные файлы, если они существуют.
    """
    for path in file_paths:
        abs_path = os.path.abspath(os.path.join(os.getcwd(), path.lstrip("/")))
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
                print(f"🧹 Удалён файл: {abs_path}")
            except Exception as e:
                print(f"❗ Ошибка при удалении {abs_path}: {e}")
