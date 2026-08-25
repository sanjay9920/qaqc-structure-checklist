from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import qrcode

from .config import settings


def structure_url(structure_id, base_url=None):
    root = (base_url or settings.app_base_url or "http://localhost:5000").rstrip("/")
    return f"{root}/structure/{structure_id}"


def generate_qr_bytes(structure_id, base_url=None):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(structure_url(structure_id, base_url))
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def generate_qr_zip(structure_ids, base_url=None):
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for structure_id in structure_ids:
            png = generate_qr_bytes(structure_id, base_url)
            zip_file.writestr(f"{structure_id}.png", png.getvalue())
    archive.seek(0)
    return archive


def save_qr_file(structure_id, output_dir, base_url=None):
    output_path = Path(output_dir) / f"{structure_id}.png"
    png = generate_qr_bytes(structure_id, base_url)
    output_path.write_bytes(png.getvalue())
    return output_path
