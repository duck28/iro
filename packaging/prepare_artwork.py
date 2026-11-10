"""Format the generated logo for the stock WiX wizard (requires Pillow)."""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
logo = Image.open(root / "branding" / "iro-logo-original.png").convert("RGBA")
banner = Image.new("RGBA", (493, 58), "#fbfaf7")
banner.alpha_composite(logo.resize((52, 52), Image.Resampling.LANCZOS), (434, 3))
banner.convert("RGB").save(root / "packaging" / "banner.bmp")
dialog = Image.new("RGBA", (493, 312), "#fbfaf7")
dialog.alpha_composite(logo.resize((145, 145), Image.Resampling.LANCZOS), (10, 65))
dialog.convert("RGB").save(root / "packaging" / "dialog.bmp")
