"""Export queued originals without losing JPEG bytes or overwriting files."""
from pathlib import Path
import re
from shutil import copyfileobj


def export_all_images(items, folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError('Thư mục lưu ảnh không còn tồn tại.')
    paths = []
    for index, item in enumerate(items, 1):
        source = item.original_path or item.image_path
        # Match the stored format, including original imports converted to PNG.
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(item.name).stem).strip(' .')[:100] or 'Anh'
        target = folder / f'{index:03d}_{stem}{source.suffix.lower()}'
        suffix = 1
        while target.exists():
            target = folder / f'{index:03d}_{stem}_{suffix}{source.suffix.lower()}'
            suffix += 1
        # Exclusive creation also protects against a file appearing after exists().
        with source.open('rb') as reader, target.open('xb') as writer:
            copyfileobj(reader, writer)
        paths.append(target)
    return paths
