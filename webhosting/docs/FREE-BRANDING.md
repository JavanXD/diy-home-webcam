# Free-plan branding — HTML landing only (chosen)

**Decision:** Brand on the public **landing page** with an HTML/CSS chip (logo + link to dasbollenhuthaus.de).  
The livestream **JPEG itself is not watermarked** (clean hotlink / timelapse / embed).

## Why this over pipeline PNG / CF Images

| Approach | Free? | Brands the `.jpg`? | Notes |
|----------|-------|--------------------|-------|
| **HTML overlay (chosen)** | Yes | No — only `/` | Zero transform cost; best for timelapse cleanliness |
| Pipeline PNG burn-in | Yes | Yes | Use if you need hotlinked JPG branded |
| CF Images edge draw | Free 5k unique/mo | Yes | Burns quota fast on live frames — avoid |

## Files

- Landing: `site/index.html` (`.brand` chip → https://dasbollenhuthaus.de/)
- Logo asset: `site/branding/bollenhut-watermark.png`
- Sync: `python3 scripts/sync-bollenhut-watermark.py`
- Public variants: `watermark.enabled: false` in `cameras/<id>/variants/*-public.yaml`
