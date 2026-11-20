import win32com.client
import os
from PIL import Image

shell = win32com.client.Dispatch('WScript.Shell')
shortcut_path = os.path.join(os.getcwd(), 'AI Hub.lnk')
shortcut = shell.CreateShortcut(shortcut_path)

print('Current target:', shortcut.TargetPath)
print('Current icon location:', shortcut.IconLocation)

# Set the new icon - use the JPEG image as icon
# We need to convert the JPEG to an icon or use it somehow
# First, let's see what the image path is
image_path = os.path.join(os.getcwd(), 'WhatsApp Image 2026-11-20 at 08.18.21.jpeg')
print('Image path:', image_path)

# Check if PIL can open the image
try:
    img = Image.open(image_path)
    print(f'Image size: {img.size}, mode: {img.mode}')
except Exception as e:
    print(f'PIL error: {e}')

# JPEG files cannot directly be used as Windows icons.
# We need to convert the JPEG to an .ico file.
# Let's save a 256x256 icon from the image
icon_path = os.path.join(os.getcwd(), 'WhatsApp_Icon.ico')
try:
    # Resize and save as ICO
    img_resized = img.resize((256, 256), Image.LANCZOS)
    img_resized.save(icon_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print(f'Icon saved to: {icon_path}')
    
    # Now update the shortcut to use this icon
    shortcut.IconLocation = icon_path
    shortcut.save()
    print('Shortcut icon updated successfully!')
except Exception as e:
    print(f'Error creating icon: {e}')