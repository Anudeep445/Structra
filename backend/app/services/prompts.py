"""Deterministic prompts for STRUCTRA document AI workflows."""

from dataclasses import dataclass
import json


DEFAULT_RECEIPT_INVOICE_FIELDS = (
    "vendor_company",
    "address",
    "date",
    "total",
    "line_items",
)

LINE_ITEM_FIELDS = ("description", "line_total")


@dataclass(frozen=True)
class ReceiptInvoicePromptConfig:
    """Configuration for extending the top-level extraction output later."""

    additional_top_level_fields: tuple[str, ...] = ()


def build_receipt_invoice_extraction_prompt(
    config: ReceiptInvoicePromptConfig | None = None,
) -> str:
    """Build the JSON-only prompt for receipt and invoice extraction."""
    config = config or ReceiptInvoicePromptConfig()
    output_schema: dict[str, object] = {
        "vendor_company": None,
        "address": None,
        "date": None,
        "invoice_number": None,
        "subtotal": None,
        "discount": None,
        "taxable_amount": None,
        "tax": None,
        "tax_components": [
            {
                "name": "e.g. CGST, SGST, IGST, VAT, Service Tax, Surcharge, Cess",
                "rate": None,
                "amount": None,
            }
        ],
        "additional_charges": [
            {
                "name": "e.g. Delivery Fee, Packing Charge, Convenience Fee",
                "rate": None,
                "amount": None,
            }
        ],
        "service_charge": None,
        "round_off": None,
        "total": None,
        "line_items": [
            {
                "description": None,
                "quantity": None,
                "unit_price": None,
                "line_total": None,
            }
        ],
    }
    output_schema.update(
        {field_name: None for field_name in config.additional_top_level_fields}
    )
    schema_json = json.dumps(output_schema, ensure_ascii=False, indent=2)

    return (
        "Analyze the provided receipt or invoice image carefully. Extract only information that is "
        "actually present in the document. Never invent, infer, or guess missing values. "
        "Preserve numbers accurately. Keep line items separate from document-level totals.\n"
        "Extract every printed tax as a separate tax_components row (GST components, VAT, service tax, surcharge, cess, and similar levies). Extract non-tax fees such as delivery, packing, handling, and convenience fees separately in additional_charges. Never relabel a non-GST tax or fee as GST.\n\n"
        "RULES FOR MULTIMODAL EXTRACTION:\n"
        "1. AUTHORITATIVE SOURCE: The visual image is the authoritative source. Extract ONLY information actually visible. Do not invent, infer, or guess missing values.\n"
        "2. VISUAL LAYOUT & TABLES: Use visual layout, table columns, alignment, printed digits, fonts, and spatial relationships to extract table data.\n"
        "3. IDENTIFIERS & DATES: Preserve exact vendor names, addresses, dates, and invoice/receipt numbers (e.g. preserve 'RCPT-2025-08-09-0015' exactly).\n"
        "4. LINE ITEMS & QUANTITIES: A line_item is one purchased product/service only. Extract each visible priced product/service row with its printed description, quantity, unit_price (item rate), and line_total (item amount). Read rate and amount from their aligned printed columns. Copy line_total exactly as printed; never calculate or replace it with quantity × rate. Use quantity 1 only when quantity is absent and the printed rate equals the printed amount. GST is never a line item: put GST/CGST/SGST/IGST/VAT amounts only in tax_components and do not add tax to an item's unit_price or line_total. Never include invoice numbers, KOT/order references, extra fees, discounts, payments, subtotal, or total rows as items.\n"
        "5. NUMERICS & DECIMALS: Preserve exact numbers and decimal values. Keep line item totals distinct from document subtotal, taxes, and final total.\n"
        "6. TAXES & ADDITIONAL CHARGES: Extract every printed tax component separately in tax_components with its printed name, rate, and amount, including CGST, SGST, IGST, UTGST, GST cess, VAT, service tax, surcharge, and other named levies. Extract non-tax add-ons (delivery, packing, handling, convenience, etc.) in additional_charges; put an explicitly labeled service charge in service_charge and signed rounding in round_off. The top-level 'tax' must equal the sum of all tax_components. Do not omit a printed charge just because it is not GST.\n"
        "7. FINAL TOTAL / NET AMOUNT: Extract the exact printed final net payable amount (often labeled 'NET AMOUNT', 'GRAND TOTAL', 'TOTAL AMOUNT', 'TOTAL PAYABLE', or 'AMOUNT PAID', e.g. 268.00). Do NOT recalculate or round up the final total; use the exact printed amount.\n"
        "8. TEXT SPACING: Preserve natural spacing in company names and item descriptions.\n"
        "9. OUTPUT FORMAT: Return only one valid JSON object conforming to the required schema shape with no explanatory text or markdown wrappers. Use null for a scalar field that cannot be confidently extracted, and use [] when no line items can be confidently extracted.\n\n"
        "Required JSON Output Shape:\n"
        f"{schema_json}"
    )


def build_multimodal_receipt_extraction_prompt(
    config: ReceiptInvoicePromptConfig | None = None,
) -> str:
    """Build prompt for Gemini Multimodal Vision extraction directly from receipt images."""
    return build_receipt_invoice_extraction_prompt(config)


def build_ocr_receipt_extraction_prompt(
    ocr_text_content: str,
    config: ReceiptInvoicePromptConfig | None = None,
) -> str:
    """Build the JSON extraction prompt for OCR-derived receipt/invoice text & layout input."""
    base_instructions = build_receipt_invoice_extraction_prompt(config)
    return (
        "You are an expert document understanding AI. The text below was recognized from a receipt/invoice "
        "by a local OCR engine, organized row by row.\n\n"
        "RULES FOR EXTRACTION:\n"
        "1. TEXT SPACING: Restore natural spaces in vendor_company, address, and line item descriptions if OCR merged words together (e.g. convert 'ABCMART' to 'ABC MART', '123Green Street' to '123 Green Street'). Do NOT insert spaces into invoice/receipt numbers or codes (e.g. preserve 'RCPT-2025-08-09-0015' exactly).\n"
        "2. LINE ITEMS & QUANTITY: Extract ALL line items in the receipt table. For every line item, extract description, quantity, unit_price, and line_total as independent fields. If a line item lists unit_price equal to line_total and quantity is not printed as a separate number, extract quantity as 1.0 (do NOT leave quantity as null for valid line items).\n"
        "3. ITEM CODES: Preserve printed HSN/SKU/product codes in the beginning of the corresponding description; never discard codes from a line item. Keep the item wording as printed and do not guess corrections.\n"
        "4. NUMERICS & DATES: Preserve exact numeric values, decimal amounts, dates, and invoice numbers.\n"
        "5. TAXES & ADDITIONAL CHARGES: Extract every printed tax (GST variants, VAT, service tax, surcharge, cess, and other named levies) as a separate tax_components row. Put non-tax fees such as delivery, packing, handling, and convenience fees in additional_charges. Keep service_charge and round_off in their own fields. The top-level tax equals the sum of tax_components.\n"
        "6. FINAL TOTAL: Extract the exact printed NET AMOUNT / GRAND TOTAL as total.\n"
        "7. OUTPUT: Return ONLY one valid JSON object following the required output shape with no Markdown tags or extra prose.\n\n"
        f"--- RECOGNIZED OCR DOCUMENT TEXT ---\n{ocr_text_content}\n--- END OCR TEXT ---\n\n"
        f"{base_instructions}"
    )
