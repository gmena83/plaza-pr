"""Extract product offers from image-only PDF shoppers using a local VL model.

Pipeline: PDF -> page images (pdftoppm) -> Qwen3-VL via OpenAI-compatible
server (vLLM) -> strict JSON rows -> validated offer dicts.

The VL model is served separately (see serve_vl.sh / run_weekly.py). This module
only talks to the OpenAI-compatible endpoint.
"""
import base64
import json
import logging
import re
import subprocess
from pathlib import Path

from openai import OpenAI

from .common import ROOT, load_config, parse_price, parse_size_unit

log = logging.getLogger("pr-shopper.vl")

PROMPT = (
    "Eres un extractor de datos de shoppers (circulares de ofertas) de supermercados "
    "de Puerto Rico. Analiza esta imagen de una página de shopper y extrae TODOS los "
    "productos con precio que veas. Responde ÚNICAMENTE con un array JSON válido, sin "
    "markdown, sin texto extra. Cada elemento: "
    '{"product": nombre completo del producto, "brand": marca o null, "size": tamaño/ '
    'unidad tal como aparece (ej "12 oz", "1 lb", "caja 24 un") o null, "price_sale": '
    'precio de oferta como número (ej 2.99), "price_regular": precio regular como número '
    'o null, "promo": texto de promoción si hay (ej "2x1", "2/$5", "limite 4") o null, '
    '"category": categoría si es evidente o null}. '
    "Si el precio dice '2/$5' pon price_sale=2.50 y promo='2/$5'. Si no hay precio claro, "
    "omite el producto. No inventes productos."
)


def _img_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def pdf_to_images(pdf_path: Path, dpi: int, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / "page"
    # clean stale
    for f in out_dir.glob("page-*.png"):
        f.unlink()
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
        check=True, capture_output=True)
    imgs = sorted(out_dir.glob("page-*.png"))
    log.info("rendered %d pages from %s at %d dpi", len(imgs), pdf_path.name, dpi)
    return imgs


def _parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    # strip markdown fences if the model disobeys
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError as e:
        log.warning("json parse failed: %s", e)
        return []


def _norm(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "")).strip().lower()
    t = re.sub(r"[^a-z0-9\u00f1\u00e1\u00e9\u00ed\u00f3\u00fa ]", "", t)
    return t


def _maybe_downscale(img_path: Path, max_edge: int = 1568) -> Path:
    """Qwen3-VL encodes ~1 token per 28x28 patch; a 1568px long edge keeps a
    full shopper page well under an 8192-token context. Downscale in place to a
    derived file if larger."""
    from PIL import Image
    im = Image.open(img_path)
    w, h = im.size
    needs_rgb = im.mode not in ("RGB", "L")
    if max(w, h) <= max_edge and not needs_rgb:
        return img_path          # already small + RGB: use as-is
    if needs_rgb:
        im = im.convert("RGB")
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    out = img_path.with_name(img_path.stem + "_ds.png")
    im.save(out)
    return out


def extract_page(client: OpenAI, model: str, img_path: Path, cfg: dict) -> list[dict]:
    img_path = _maybe_downscale(img_path)
    b64 = _img_b64(img_path)
    resp = client.chat.completions.create(
        model=model,
        temperature=cfg.get("temperature", 0.0),
        max_tokens=cfg.get("max_tokens", 4096),
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
    )
    content = resp.choices[0].message.content or ""
    return _parse_json_array(content)


def _rows_to_offers(rows: list[dict], chain_slug: str, page_no: int) -> list[dict]:
    out = []
    for r in rows:
        product = (r.get("product") or "").strip()
        price_sale = r.get("price_sale")
        if isinstance(price_sale, str):
            price_sale = parse_price(price_sale)
        if not product or price_sale is None:
            continue
        size_text = r.get("size")
        _, unit_basis = parse_size_unit(" ".join(
            [str(size_text or ""), str(r.get("price_sale") or ""), str(r.get("promo") or "")]))
        out.append({
            "chain_slug": chain_slug,
            "product_raw": product,
            "product_norm": _norm(product),
            "brand": r.get("brand"),
            "size_text": size_text,
            "price_sale": price_sale,
            "price_regular": r.get("price_regular"),
            "unit_basis": unit_basis,
            "promo": r.get("promo"),
            "category": r.get("category"),
            "page": page_no,
            "source_url": None,
        })
    return out


def extract_images(image_paths: list[Path], chain_slug: str, cfg: dict) -> list[dict]:
    """Extract offers from a list of local page images (Wix/hosted shoppers)."""
    from openai import OpenAI
    vl = cfg["vl"]
    client = OpenAI(base_url=vl["serve_url"], api_key="EMPTY")
    offers: list[dict] = []
    for i, img in enumerate(image_paths, start=1):
        try:
            rows = extract_page(client, vl["model"], img, vl)
        except Exception as e:  # noqa: BLE001
            log.error("%s image %d extraction failed: %s", chain_slug, i, e)
            continue
        log.info("%s image %d: %d raw rows", chain_slug, i, len(rows))
        offers.extend(_rows_to_offers(rows, chain_slug, i))
    return offers


def extract_pdf(pdf_path: Path, chain_slug: str, cfg: dict) -> list[dict]:
    vl = cfg["vl"]
    chain_cfg = cfg.get("chains", {}).get(chain_slug, {})
    dpi = int(chain_cfg.get("dpi", vl.get("dpi", 200)))
    model = vl["model"]
    client = OpenAI(base_url=vl["serve_url"], api_key="EMPTY")

    img_dir = ROOT / "data" / "pages" / chain_slug
    images = pdf_to_images(pdf_path, dpi, img_dir)

    offers: list[dict] = []
    for i, img in enumerate(images, start=1):
        try:
            rows = extract_page(client, model, img, vl)
        except Exception as e:  # noqa: BLE001
            log.error("page %d extraction failed: %s", i, e)
            continue
        log.info("%s page %d: %d raw rows", chain_slug, i, len(rows))
        offers.extend(_rows_to_offers(rows, chain_slug, i))
    return offers
