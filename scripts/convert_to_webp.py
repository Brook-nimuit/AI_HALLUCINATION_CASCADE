# Excessive png snapshots? use this
from pathlib import Path
from PIL import Image

DATA_DIR = Path("data/local")


def convert_pngs_to_webp(root_dir: Path) -> None:
    png_files = list(root_dir.rglob("*.png"))
    total = len(png_files)
    print(f"Found {total} PNG files to convert...")

    bytes_saved = 0

    for index, png_path in enumerate(png_files, start=1):
        webp_path = png_path.with_suffix(".webp")

        try:
            old_size = png_path.stat().st_size

            with Image.open(png_path) as img:
                # quality=82 keeps text and board lines sharp at ~10-15% of PNG size
                img.save(webp_path, format="WEBP", quality=82, method=4)

            if webp_path.exists() and webp_path.stat().st_size > 0:
                new_size = webp_path.stat().st_size
                bytes_saved += (old_size - new_size)
                png_path.unlink()  # Delete original PNG after safe write

            if index % 200 == 0 or index == total:
                mb_saved = bytes_saved / (1024 * 1024)
                print(f"[{index}/{total}] Converted... ({mb_saved:.1f} MB saved so far)")

        except Exception as err:
            print(f"Skipped {png_path}: {err}")


def update_json_and_csv_links(root_dir: Path) -> None:
    text_files = list(root_dir.rglob("*.json")) + list(root_dir.rglob("*.csv"))
    updated_count = 0

    for file_path in text_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            if ".png" in content:
                new_content = content.replace(".png", ".webp")
                file_path.write_text(new_content, encoding="utf-8")
                updated_count += 1
        except Exception as err:
            print(f"Could not update text file {file_path}: {err}")

    print(f"Updated .png -> .webp references in {updated_count} JSON/CSV files.")


if __name__ == "__main__":
    convert_pngs_to_webp(DATA_DIR)
    update_json_and_csv_links(DATA_DIR)
    print("Done!")