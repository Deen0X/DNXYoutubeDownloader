from PIL import Image
import os

img_path = 'DNXYoutubeDownloaderWeb.png'
ico_path = 'DNXYoutubeDownloaderWeb.ico'

if os.path.exists(img_path):
    img = Image.open(img_path)
    # Windows icons usually include these sizes
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(ico_path, sizes=icon_sizes)
    print(f"Icono generado exitosamente: {ico_path} con tamaños {icon_sizes}")
else:
    print(f"No se encontró {img_path}")
