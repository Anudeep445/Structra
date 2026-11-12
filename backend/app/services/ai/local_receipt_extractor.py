"""Conservative receipt-field extraction from local OCR text when cloud AI is offline."""

import re

from app.schemas.documents import ReceiptInvoiceExtraction, ReceiptInvoiceLineItem, TaxComponent
from app.services.ai.schemas import AIUnexpectedResponseError
from app.services.ocr.schemas import OCRResult


_MONEY = re.compile(
    r"(?<![\w.])(?:₹|rs\.?|inr\s*)?\s*"
    r"([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)"
    r"\s*(?:/-)?",
    re.IGNORECASE,
)
_NUMBER_TOKEN = re.compile(r"(?<![\w.])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)(?![\w.])")
_DATE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")


def _amounts(line: str) -> list[float]:
    values: list[float] = []
    for match in _MONEY.finditer(line):
        try:
            values.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return values


def _signed_last_amount(line: str) -> float | None:
    matches = list(_NUMBER_TOKEN.finditer(line))
    # A printed tax rate is a percentage, not a currency amount. In rows such
    # as "GST 18%" don't turn the 18 into an ₹18 tax; in "GST 18% 90.00"
    # continue to use the trailing currency amount.
    match = next(
        (
            candidate
            for candidate in reversed(matches)
            if not line[candidate.end() :].lstrip().startswith("%")
        ),
        None,
    )
    if match is None:
        return None
    value = float(match.group(1).replace(",", ""))
    prefix = line[: match.start()].rstrip()
    if prefix.endswith(("-", "−", "–")) or (prefix.endswith("(") and line[match.end() :].lstrip().startswith(")")):
        value = -value
    return value


def _parse_line_items(lines: list[str]) -> list[ReceiptInvoiceLineItem]:
    items: list[ReceiptInvoiceLineItem] = []
    for line in lines:
        # These rows can contain positive numbers but are not chargeable
        # products/services. Filter the complete OCR row before reading its
        # trailing numeric columns.
        if re.search(
            r"\b(?:total|subtotal|grand\s*total|net\s*(?:amount|payable)|taxable|payment|"
            r"amount|items?\s*:|round\s*off|balance|paid|due|gstin|invoice|bill\s*no|"
            r"kot\s*(?:no|number)?|order\s*(?:no|number|id)|reference|ref\s*(?:no|number)?|"
            r"date|time|address|layout|covers|table\s*no|serc|kkc|gst|cgst|sgst|igst|cess|vat|tax|"
            r"surcharge|levy|delivery\s*(?:fee|charge)|pack(?:ing|aging)\s*(?:fee|charge)|handling\s*(?:fee|charge)|"
            r"convenience\s*(?:fee|charge)|service\s*(?:fee|charge))\b|"
            r"^\s*(?:no\.?\s+\d|bengaluru\b)",
            line,
            re.IGNORECASE,
        ):
            continue
        matches = list(_NUMBER_TOKEN.finditer(line))
        if not matches:
            continue

        values = [float(match.group(1).replace(",", "")) for match in matches]
        amount = values[-1]
        if amount <= 0:
            continue

        # Handle item rows with only an amount, rate+amount, or
        # qty+rate+amount. OCR commonly loses the quantity column, so a
        # mismatch must not discard an otherwise priced item.
        description_end = matches[-2].start() if len(matches) >= 2 else matches[-1].start()
        quantity, unit_price = 1.0, amount
        if len(values) >= 3:
            qty, rate, row_amount = values[-3:]
            if qty > 0 and rate > 0 and abs(qty * rate - row_amount) <= max(0.05, row_amount * 0.01):
                description_end = matches[-3].start()
                quantity, unit_price = qty, rate
            else:
                unit_price = values[-2]
                if unit_price > amount:
                    # OCR may merge the row number and quantity into the
                    # printed rate (for example, "1" + "280" -> "1280").
                    unit_price = amount
                if unit_price > 0:
                    inferred = amount / unit_price
                    if inferred >= 1 and abs(inferred - round(inferred)) < 0.01:
                        quantity = float(round(inferred))
        elif len(values) == 2:
            text_between_numbers = line[matches[-2].end() : matches[-1].start()]
            if not line[: matches[-2].start()].strip() and re.search(r"[A-Za-z]{2,}", text_between_numbers):
                # The first number is a printed row index and OCR omitted the
                # rate column; retain the named row using its positive amount.
                description_end = matches[-1].start()
                unit_price = amount
            else:
                unit_price = values[-2]
                if unit_price > 0:
                    inferred = amount / unit_price
                    if inferred >= 1 and abs(inferred - round(inferred)) < 0.01:
                        quantity = float(round(inferred))

        description = line[:description_end].strip(" :-|\t")
        description = re.sub(r"\bGST\s*@.*$", "", description, flags=re.IGNORECASE).strip()
        # Serial numbers are not part of an item's name.
        description = re.sub(r"^\s*\d{1,3}[.)]?\s+", "", description).strip()
        if not description or re.search(
            r"subtotal|grand\s*total|net\s*(?:amount|payable)|taxable|payment|"
            r"amount|items?\s*:|round\s*off|balance|paid|due|"
            r"\b(?:gst|cgst|sgst|igst|cess|vat|tax|breakup|service\s*charge)\b",
            description,
            re.IGNORECASE,
        ):
            continue
        items.append(
            ReceiptInvoiceLineItem(
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                line_total=amount,
            )
        )
    return items


def extract_receipt_from_ocr(ocr_result: OCRResult) -> ReceiptInvoiceExtraction:
    """Extract basic fields from OCR text without sending document data to a cloud API.

    This is a fallback for local/demo environments. The result should be reviewed
    because text patterns cannot interpret every receipt layout reliably.
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in ocr_result.full_text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise AIUnexpectedResponseError("Local OCR found no readable receipt text.")

    vendor = next(
        (
            line
            for line in lines[:8]
            if re.search(r"[A-Za-z]{3,}", line)
            and not re.search(
                r"tax invoice|invoice|receipt|phone|address|date|gstin|fssai|bill\s*(?:no|number)",
                line,
                re.IGNORECASE,
            )
        ),
        None,
    )

    receipt_date = next((match.group(1) for line in lines if (match := _DATE.search(line))), None)
    invoice_number = None
    for line in lines:
        match = re.search(
            r"\b(?:invoice|inv(?!oice)|bill|vou(?:cher)?|receipt)"
            r"[.\s]*(?:no\.?|number|#)?[.\s:]*([A-Z0-9][A-Z0-9/-]{3,})",
            line,
            re.IGNORECASE,
        )
        if match:
            invoice_number = match.group(1).rstrip(".,")
            break

    items = _parse_line_items(lines)
    total_candidates: list[tuple[int, float]] = []
    total_patterns = (
        (0, r"grand\s*total|net\s*(?:payable|amount)|amount\s*(?:paid|received|due)"),
        (1, r"total\s*(?:amount|payable|due)?\b"),
        (2, r"(?:up[yi1]|card|cash)\s+payment|payment\s+(?:received|amount)"),
    )
    for line in lines:
        lower_line = line.lower()
        if re.search(r"sub\s*total|taxable|items?\s*:", lower_line):
            continue
        for priority, pattern in total_patterns:
            if re.search(pattern, lower_line):
                values = _amounts(line)
                if values:
                    total_candidates.append((priority, values[-1]))
                break

    total = min(total_candidates, key=lambda item: item[0])[1] if total_candidates else None
    subtotal = None
    for line in lines:
        if re.search(r"\bsub\s*total\b", line, re.IGNORECASE):
            values = _amounts(line)
            if values:
                subtotal = values[-1]
                break
    has_explicit_final_total = any(
        re.search(r"grand\s*total|net\s*(?:amount|payable)", line, re.IGNORECASE)
        for line in lines
    )
    if subtotal is None and has_explicit_final_total:
        for line in lines:
            if re.search(r"\btotal\s*amount\b", line, re.IGNORECASE):
                values = _amounts(line)
                if values:
                    subtotal = values[-1]
                    break
        if subtotal is None:
            for line in lines:
                if re.search(r"^\s*total\b(?!\s*(?:tax|items?))", line, re.IGNORECASE):
                    values = _amounts(line)
                    if values:
                        subtotal = values[-1]
                        break

    tax_components: list[TaxComponent] = []
    additional_charges: list[TaxComponent] = []
    tax_total = 0.0
    printed_tax_total = None
    service_charge = None
    round_off = None
    for line in lines:
        lower_line = line.lower()
        if re.search(r"\b(?:tax\s+invoice|taxable|gstin)\b", lower_line):
            continue
        if re.search(r"round\s*off", lower_line):
            round_off = _signed_last_amount(line)
            continue
        if re.search(r"\b(?:total\s+tax|tax\s+total)\b", lower_line):
            printed_tax_total = _signed_last_amount(line)
            continue
        if re.search(r"\b(?:serc|service\s*charge)\b", lower_line):
            service_charge = _signed_last_amount(line)
            continue
        if re.search(
            r"\b(?:gst|cgst|sgst|igst|utgst|vat|tax|surcharge|cess|levy)\b|"
            r"service\s+tax|\bsb\s*cess\b|\bkkc\b",
            lower_line,
        ):
            rate_match = re.search(r"(?:@\s*|\b)(\d+(?:\.\d+)?)\s*%", line)
            amount = _signed_last_amount(line)
            if amount is None and rate_match is None:
                continue
            label = re.sub(r"[\d@%.,:₹]+", " ", line).strip()
            label = re.sub(r"\s+", " ", label)
            if not label:
                label = "GST"
            tax_components.append(
                TaxComponent(name=label, rate=float(rate_match.group(1)) if rate_match else None, amount=amount)
            )
            if amount is not None:
                tax_total += amount
            continue
        if re.search(
            r"\b(?:delivery|pack(?:ing|aging)|handling|convenience|freight|service|tips?)\b.*\b(?:fee|charge)\b|"
            r"\b(?:fee|charge)\b.*\b(?:delivery|pack(?:ing|aging)|handling|convenience|freight|service)\b",
            lower_line,
        ):
            amount = _signed_last_amount(line)
            if amount is not None:
                label = re.sub(r"[\d@%.,:â‚¹]+", " ", line).strip()
                additional_charges.append(TaxComponent(name=re.sub(r"\s+", " ", label), amount=amount))

    if not tax_components and printed_tax_total is not None:
        tax_total = printed_tax_total
    extraction = ReceiptInvoiceExtraction(
        vendor_company=vendor,
        date=receipt_date,
        invoice_number=invoice_number,
        subtotal=subtotal,
        tax=round(tax_total, 2) if tax_components else printed_tax_total,
        tax_components=tax_components,
        additional_charges=additional_charges,
        service_charge=service_charge,
        round_off=round_off,
        total=total,
        line_items=items,
    )
    if extraction.total is None and not extraction.line_items:
        raise AIUnexpectedResponseError(
            "Local OCR could not confidently identify a receipt total or line items."
        )
    return extraction
