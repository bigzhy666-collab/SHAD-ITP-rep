"""Preserve the supplied artwork while filling the Windows icon canvas."""
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main():
    source = Image.open(ROOT / 'desktop/icon-source.png').convert('RGBA')
    # The supplied screenshot includes a white desktop fringe and cuts off the
    # lower corners. Restore the same rounded panel edge, retaining inner artwork.
    scale = 4
    outline = Image.new('RGBA', (source.width * scale, source.height * scale))
    ImageDraw.Draw(outline).rounded_rectangle((scale, 0, 80 * scale, 77 * scale), radius=11 * scale, fill=(44, 46, 53, 255))
    interior = Image.new('L', outline.size)
    ImageDraw.Draw(interior).rounded_rectangle((3 * scale, 2 * scale, 78 * scale, 75 * scale), radius=9 * scale, fill=255)
    outline.paste(source.resize(outline.size, Image.Resampling.LANCZOS), (0, 0), interior)
    source = outline
    artwork = source.crop(source.getbbox())
    # Image.thumbnail never enlarges small artwork. ImageOps.contain does.
    artwork = ImageOps.contain(artwork, (256, 256), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (256, 256))
    canvas.alpha_composite(artwork, ((256 - artwork.width) // 2, (256 - artwork.height) // 2))
    canvas.save(ROOT / 'desktop/icon.png')
    canvas.save(ROOT / 'desktop/icon.ico', sizes=[(size, size) for size in SIZES])
    print('Generated full-size PNG and seven Windows ICO resolutions.')


if __name__ == '__main__':
    main()
