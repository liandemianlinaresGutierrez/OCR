import os
import re
from typing import List, Tuple
from PIL import Image
import pytesseract

# ========== CONFIGURACIÓN ==========
pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
IMAGE_DIR = "images"  # Carpeta con facturas (png, jpg, jpeg)


# ========== OCR & LIMPIEZA ==========
def extract_text(image_path: str) -> str:
    """Extrae texto usando OCR de Tesseract"""
    img = Image.open(image_path)
    # Probar español + inglés para facturas mixtas
    text = pytesseract.image_to_string(img, lang="spa+eng")
    return text


def normalize_text(text: str) -> str:
    """Corrige errores comunes de OCR"""
    replacements = {
        "precioneto": "precio neto",
        "valorneto": "valor neto",
        "imporie": "importe",
        "imporle": "importe",
        "cantldad": "cantidad",
        "totai": "total",
    }
    t = text.lower()
    for wrong, right in replacements.items():
        t = t.replace(wrong, right)
    return t


# ========== HELPERS ==========
def parse_number(num: str) -> float:
    num = num.strip()

    # Caso con coma y punto -> formato europeo
    if "," in num and "." in num:
        num = num.replace(".", "").replace(",", ".")
    elif "," in num:
        # solo coma decimal
        num = num.replace(",", ".")
    elif "." in num:
        # hay punto pero no coma -> probablemente separador de miles
        if re.match(r"^\d{1,3}(\.\d{3})+$", num):  # ej: 1.451 o 12.345
            num = num.replace(".", "")
        # si es decimal normal (ej: 1234.56), lo dejamos como está
    # eliminar símbolos de euro, espacios y signos +
    num = re.sub(r"[€\s+]", "", num)

    return float(num)



def find_total(text: str) -> float:
    """
    Busca el total reportado en la factura (última coincidencia).
    Maneja formatos europeos (1.234,56) y estándar (1234.56).
    """
    matches = re.findall(r"total[s]?[^\d]*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))", text.lower())
    if matches:
        raw_total = matches[-1]
        return parse_number(raw_total)
    return None


# ========== PROCESADORES ==========
def process_invoice_any(text: str):
    """Método universal: intenta detectar patrones de cantidad-precio-importe"""
    lines = text.splitlines()
    calculated_total = 0.0

    for raw in lines:
        line = raw.strip().lower()
        if not line:
            continue

        # Ignorar metadatos y fechas
        if any(x in line for x in [
            "fecha", "nit", "ci", "cliente", "vendedor", "firma", "sello",
            "condiciones", "observaciones", "iban", "n°", "factura"
        ]):
            continue

        # ⚠️ ignorar formatos de fecha dd/mm/yyyy o similares
        if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", line):
            continue

        # Capturar números
        nums = re.findall(r"\d+(?:[.,]\d+)?", line)
        if len(nums) < 2:
            continue

        # Intentar mapear a qty, price, total
        try:
            if len(nums) >= 3:
                qty = parse_number(nums[-3])
                price = parse_number(nums[-2])
                total = parse_number(nums[-1])

                # ⚠️ Filtros adicionales para evitar falsos positivos
                if total > 1000 and (qty < 10 and price < 100):
                    continue

                calc = qty * price
                calculated_total += total
                print(f"Linea: {qty} x {price} = {calc:.2f} | OCR Importe: {total:.2f} | "
                      f"{'✔️' if abs(calc-total)<0.5 else '❌'}")
        except Exception:
            continue

    # Comparar con total reportado
    reported = find_total(text)
    if reported is not None:
        print(f"\nTOTAL OCR: {reported:.2f} | Calculado: {calculated_total:.2f} | "
              f"{'✔️' if abs(reported-calculated_total)<1 else '❌'}")
    else:
        print(f"\nTOTAL CALCULADO: {calculated_total:.2f}")


def process_invoice_simple(text: str):
    """Factura con columnas Cantidad / Precio / Importe"""
    calculated_total = 0.0
    pattern = re.compile(r"(\d+)\s+[A-Za-zÁÉÍÓÚÑa-z]+\s+(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)")

    for line in text.splitlines():
        m = pattern.search(line)
        if m:
            qty = int(m.group(1))
            price = parse_number(m.group(2))
            total = parse_number(m.group(3))
            calc = qty * price
            calculated_total += total
            print(f"Linea: {qty} x {price} = {calc:.2f} | OCR Importe: {total:.2f} | "
                  f"{'✔️' if abs(calc-total)<0.5 else '❌'}")

    print(f"\nTOTAL CALCULADO: {calculated_total:.2f}")


def process_invoice_valor(text: str):
    """Factura con Precio Neto / Valor Neto / Valor Total"""
    calculated_total = 0.0
    calculated_iva = 0.0
    pattern = re.compile(
        r"(\d+(?:[.,]\d+)?)\s+\w*\s*(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)\s+\d+%?\s+(\d+(?:[.,]\d+)?)"
    )

    for line in text.splitlines():
        m = pattern.search(line)
        if m:
            qty = parse_number(m.group(1))
            precio_neto = parse_number(m.group(2))
            valor_neto = parse_number(m.group(3))
            valor_total = parse_number(m.group(4))
            calc_valor_neto = qty * precio_neto
            iva_linea = valor_total - valor_neto
            calculated_total += valor_total
            calculated_iva += iva_linea

            print(f"Linea: {qty} x {precio_neto} = {calc_valor_neto:.2f} | "
                  f"OCR Valor Neto: {valor_neto:.2f} | IVA: {iva_linea:.2f} | "
                  f"Valor Total: {valor_total:.2f}")

    print(f"\nTOTAL CALCULADO: {calculated_total:.2f} | IVA CALCULADO: {calculated_iva:.2f}")


def process_invoice_en(text: str):
    """Factura en inglés con Qty / Net Price / Net Worth / VAT / Gross Worth"""
    qty = None
    net_price = None
    net_worth = None
    vat_percent = None
    gross = None

    lines = text.splitlines()
    for i, line in enumerate(lines):
        line_clean = line.strip().lower()

        # Qty → buscar después de "qty"
        if "qty" in line_clean:
            nums = re.findall(r"\d+(?:[.,]\d+)?", line + " " + (lines[i+1] if i+1 < len(lines) else ""))
            if nums:
                qty = parse_number(nums[0])

        # Net price
        if "net price" in line_clean:
            nums = re.findall(r"\d+(?:[.,]\d+)?", line + " " + (lines[i+1] if i+1 < len(lines) else ""))
            if nums:
                net_price = parse_number(nums[0])

        # Net worth
        if "net worth" in line_clean:
            nums = re.findall(r"\d+(?:[.,]\d+)?", line + " " + (lines[i+1] if i+1 < len(lines) else ""))
            if nums:
                net_worth = parse_number(nums[0])

        # VAT %
        if "vat" in line_clean and "%" in line_clean:
            m_vat = re.search(r"(\d+(?:[.,]\d+)?)\s*%", line)
            if m_vat:
                vat_percent = float(m_vat.group(1))

        # Gross worth
        if "gross worth" in line_clean or "gross" in line_clean:
            nums = re.findall(r"\d+(?:[.,]\d+)?", line + " " + (lines[i+1] if i+1 < len(lines) else ""))
            if nums:
                gross = parse_number(nums[-1])

    # Calcular valores
    calc_net = net_worth if net_worth else (qty * net_price if qty and net_price else 0)
    calc_vat = calc_net * vat_percent / 100 if vat_percent and calc_net else (gross - calc_net if gross and calc_net else 0)
    calc_total = calc_net + calc_vat

    print("\n--- FACTURA EN (English) ---")
    print(f"Qty: {qty}")
    print(f"Net price: {net_price}")
    print(f"Net worth: {net_worth}")
    print(f"VAT (%): {vat_percent} → {calc_vat:.2f}")
    print(f"Gross (OCR): {gross}")
    print(f"TOTAL CALCULADO: {calc_total:.2f} | "
          f"{'✔️' if gross and abs(calc_total - gross) < 1 else '❌'}")



def process_invoice_with_taxes(text: str):
    """
    Procesa facturas que incluyen BASE IMPONIBLE, IVA, IRPF y TOTAL.
    Verifica que TOTAL = BASE + IVA + IRPF.
    """
    base = iva = irpf = reported_total = None

    # Buscar base imponible
    m_base = re.search(r"base imponible[:\s]+([\d.,-]+)", text, re.IGNORECASE)
    if m_base:
        base = parse_number(m_base.group(1))

    # Buscar IVA
    m_iva = re.search(r"iva.*?:\s*([-]?\d+[.,]?\d*)", text, re.IGNORECASE)
    if m_iva:
        iva = parse_number(m_iva.group(1))

    # Buscar IRPF
    m_irpf = re.search(r"irpf.*?:\s*([-]?\d+[.,]?\d*)", text, re.IGNORECASE)
    if m_irpf:
        irpf = parse_number(m_irpf.group(1))

    # Buscar TOTAL
    m_total = re.findall(r"total[s]?[^\d]*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))", text.lower())
    if m_total:
        reported_total = parse_number(m_total[-1])

    print("\n--- FACTURA CON IMPUESTOS ---")
    print(f"Base imponible: {base}")
    print(f"IVA: {iva}")
    print(f"IRPF: {irpf}")
    print(f"TOTAL OCR: {reported_total}")

    if base is not None:
        calc_total = base
        if iva is not None:
            calc_total += iva
        if irpf is not None:
            calc_total += irpf

        print(f"TOTAL CALCULADO (Base+IVA+IRPF): {calc_total:.2f} | "
              f"{'✔️' if reported_total and abs(calc_total - reported_total) < 1 else '❌'}")


# ========== MAIN ==========
def main():
    for file in os.listdir(IMAGE_DIR):
        if not file.lower().endswith((".png", ".jpg", ".jpeg")):
            continue

        path = os.path.join(IMAGE_DIR, file)
        print(f"\n=== Procesando {file} ===")
        raw_text = extract_text(path)
        norm_text = normalize_text(raw_text)
        print("--- TEXTO OCR NORMALIZADO ---")
        print(norm_text)

        if "base imponible" in norm_text and "iva" in norm_text:
            process_invoice_with_taxes(norm_text)
        elif "precio neto" in norm_text and "valor neto" in norm_text:
            print("\n--- FACTURA (Precio Neto / Valor Neto) ---")
            process_invoice_valor(norm_text)
        elif "cantidad" in norm_text and "precio" in norm_text and "importe" in norm_text:
            print("\n--- FACTURA SIMPLE ---")
            process_invoice_simple(norm_text)
        elif "qty" in norm_text or "net price" in norm_text:
            print("\n--- FACTURA EN (English) ---")
            process_invoice_en(norm_text)
        else:
            print("\n--- FACTURA UNIVERSAL (Fallback) ---")
            process_invoice_any(norm_text)


if __name__ == "__main__":
    main()
