from __future__ import annotations

import csv
import cgi
import io
import json
import mimetypes
import os
import re
import sys
from datetime import date
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Any
from urllib.parse import unquote
import webbrowser
import urllib.error
import urllib.request

import pandas as pd


BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

APP_VERSION = "0.1.0"
GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/guevaraj1985/returns-shipment-builder/releases/latest"

OUTPUT_FIELDS = [
    ("order_number", "Order Number"),
    ("tracking_number", "Tracking Number"),
    ("customer_name", "Customer Name"),
    ("sku", "SKU"),
    ("qty", "Qty"),
]

PLATFORM_FIELDS = [
    "Shipment # *",
    "Date Sent Out *",
    "Receiving Date *",
    "Shipment Type",
    "Inbound Pallets",
    "Product Variant SKU *",
    "Lot #",
    "Cases *",
    "Units per Case *",
    "Tracking Info",
    "Notes",
]

HAVN_ORDER_IMPORT_FIELDS = [
    "Order Number",
    "Order Date",
    "Requested Service",
    "Item SKU",
    "Item Unit Price",
    "Item Quantity",
    "HS Code",
    "Country Of Origin",
    "Company Name",
    "First Name",
    "Last Name",
    "Address Line 1",
    "Address Line 2",
    "City",
    "State/Province",
    "Zip/Postal Code",
    "Country",
    "Email",
    "Phone",
    "Notes",
    "Signature Required",
    "Package SKU",
    "Package Type",
    "Package Length",
    "Package Width",
    "Package Height",
    "Declared Value",
    "Package #",
    "Origin Address Line 1",
    "Origin Address Line 2",
    "Origin City",
    "Origin State/Province",
    "Origin Zip/Postal Code",
    "Origin Country",
    "Origin Company",
    "Origin Contact Name",
    "Origin Phone",
    "Origin Email",
]

SOAPBOX_ORDER_IMPORT_FIELDS = [
    "Order Number",
    "Order Date",
    "Requested Service",
    "Item SKU",
    "Item Unit Price",
    "Item Quantity",
    "HS Code",
    "Country Of Origin",
    "Company Name",
    "First Name",
    "Last Name",
    "Address Line 1",
    "Address Line 2",
    "City",
    "State/Province",
    "Zip/Postal Code",
    "Country",
    "Email",
    "Phone",
    "Notes",
    "Signature Required",
    "Package SKU",
    "Package Type",
    "Package Length",
    "Package Width",
    "Package Height",
    "Declared Value",
    "Package #",
]

ALIASES = {
    "order_number": [
        "order number",
        "order #",
        "order no",
        "ordernumber",
        "order id",
        "po number",
        "purchase order",
        "customer order",
    ],
    "tracking_number": [
        "tracking number",
        "tracking #",
        "tracking no",
        "tracking",
        "shipment tracking",
        "carrier tracking",
        "pro number",
    ],
    "customer_name": [
        "customer name",
        "customer",
        "recipient",
        "ship to name",
        "ship-to name",
        "consignee",
        "buyer name",
    ],
    "sku": [
        "sku",
        "item sku",
        "product sku",
        "item number",
        "item #",
        "part number",
        "style",
        "upc",
    ],
    "qty": [
        "qty",
        "quantity",
        "ordered qty",
        "ship qty",
        "shipped qty",
        "units",
        "unit quantity",
    ],
}

KEY_FIELDS = ["order_number", "sku", "tracking_number", "customer_name"]


@dataclass
class SheetPayload:
    file_id: str
    filename: str
    columns: list[str]
    rows: list[dict[str, Any]]
    preview: list[dict[str, Any]]
    detected: dict[str, str]


def clean_header(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalized(value: Any) -> str:
    text = str(value or "").lower().strip()
    return re.sub(r"[^a-z0-9]+", "", text)


def cell_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_upload(storage) -> SheetPayload:
    file_id = uuid.uuid4().hex
    safe_name = Path(storage.filename or f"upload-{file_id}").name
    suffix = Path(safe_name).suffix.lower()
    saved_path = UPLOAD_DIR / f"{file_id}{suffix or '.xlsx'}"
    storage.save(saved_path)

    if suffix == ".csv":
        df = pd.read_csv(saved_path, dtype=object)
    elif suffix in {".xlsx", ".xlsm", ".xls"}:
        df = pd.read_excel(saved_path, dtype=object)
    else:
        raise ValueError(f"{safe_name} is not a supported spreadsheet type.")

    df = df.dropna(how="all")
    df.columns = make_unique_headers([clean_header(c) for c in df.columns])
    df = df.fillna("")
    rows = [
        {column: cell_text(value) for column, value in row.items()}
        for row in df.to_dict(orient="records")
    ]

    columns = list(df.columns)
    return SheetPayload(
        file_id=file_id,
        filename=safe_name,
        columns=columns,
        rows=rows,
        preview=rows[:5],
        detected=detect_columns(columns),
    )


def save_upload(storage) -> tuple[str, str]:
    file_id = uuid.uuid4().hex
    safe_name = Path(storage.filename or f"upload-{file_id}").name
    suffix = Path(safe_name).suffix.lower()
    saved_path = UPLOAD_DIR / f"{file_id}{suffix or '.xlsx'}"
    storage.save(saved_path)
    return file_id, safe_name


def make_unique_headers(headers: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    result: list[str] = []
    for index, header in enumerate(headers, start=1):
        base = header or f"Column {index}"
        counts[base] = counts.get(base, 0) + 1
        result.append(base if counts[base] == 1 else f"{base} ({counts[base]})")
    return result


def detect_columns(columns: list[str]) -> dict[str, str]:
    by_norm = {normalized(column): column for column in columns}
    detected: dict[str, str] = {}

    for field, aliases in ALIASES.items():
        winner = ""
        for alias in aliases:
            alias_norm = normalized(alias)
            if alias_norm in by_norm:
                winner = by_norm[alias_norm]
                break
        if not winner:
            for column in columns:
                column_norm = normalized(column)
                if any(normalized(alias) in column_norm for alias in aliases):
                    winner = column
                    break
        detected[field] = winner

    return detected


def load_file_rows(file_id: str) -> list[dict[str, Any]]:
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    if not matches:
        raise ValueError(f"Uploaded file {file_id} was not found.")
    path = matches[0]
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=object)
    else:
        df = pd.read_excel(path, dtype=object)
    df = df.dropna(how="all")
    df.columns = make_unique_headers([clean_header(c) for c in df.columns])
    df = df.fillna("")
    return [
        {column: cell_text(value) for column, value in row.items()}
        for row in df.to_dict(orient="records")
    ]


def dataframe_to_rows(df: pd.DataFrame) -> list[dict[str, str]]:
    df = df.dropna(how="all")
    df.columns = make_unique_headers([clean_header(c) for c in df.columns])
    df = df.fillna("")
    return [
        {column: cell_text(value) for column, value in row.items()}
        for row in df.to_dict(orient="records")
    ]


def load_workbook_sheet_rows(file_id: str, sheet_name: str) -> list[dict[str, str]]:
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    if not matches:
        raise ValueError(f"Uploaded workbook {file_id} was not found.")
    df = pd.read_excel(matches[0], sheet_name=sheet_name, dtype=object)
    return dataframe_to_rows(df)


def find_column(row: dict[str, Any], candidates: list[str]) -> str:
    by_norm = {normalized(key): key for key in row.keys()}
    for candidate in candidates:
        key = by_norm.get(normalized(candidate))
        if key:
            return key
    for key in row.keys():
        key_norm = normalized(key)
        if any(normalized(candidate) in key_norm for candidate in candidates):
            return key
    return ""


def row_value(row: dict[str, Any], candidates: list[str]) -> str:
    column = find_column(row, candidates)
    return value_from(row, column)


def digits_only(value: str) -> str:
    return re.sub(r"\D+", "", cell_text(value))


def normalize_order_number(order: str) -> str:
    order = cell_text(order)
    digits = digits_only(order)
    if digits and len(digits) < 10:
        return digits.zfill(10)
    return order


def display_order_number(order: str) -> str:
    order = normalize_order_number(order)
    digits = digits_only(order)
    if digits:
        return str(int(digits))
    return order


def title_case_name(name: str) -> str:
    name = cell_text(name)
    if not name:
        return ""
    parts = []
    for part in re.split(r"(\s+|-)", name.lower()):
        if part in {" ", "-", ""} or part.isspace():
            parts.append(part)
        else:
            parts.append(part[:1].upper() + part[1:])
    return "".join(parts)


def normalize_tracking_number(carrier: str, tracking: str) -> str:
    tracking = cell_text(tracking)
    carrier_norm = normalized(carrier)
    if not tracking:
        return ""
    digits = digits_only(tracking)
    if "fedex" in carrier_norm:
        return digits[-12:] if len(digits) > 12 else digits or tracking
    if "usps" in carrier_norm:
        return digits[-22:] if len(digits) > 22 else digits or tracking
    return tracking


def clean_tracking_for_lookup(carrier: str, tracking: str) -> str:
    return normalize_tracking_number(carrier, tracking)


def tracking_lookup_candidates(tracking: str, carrier: str = "") -> list[str]:
    tracking = cell_text(tracking)
    digits = digits_only(tracking)
    candidates = [tracking, normalize_tracking_number(carrier, tracking)]
    if digits:
        candidates.extend([digits, digits[-22:], digits[-12:]])
    result: list[str] = []
    for candidate in candidates:
        candidate = cell_text(candidate)
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def is_resolved_return_row(row: dict[str, str]) -> bool:
    return bool(row.get("order_number") and row.get("tracking_number") and row.get("sku"))


def process_tabbed_workbook(file_id: str) -> tuple[list[dict[str, str]], list[str]]:
    google = load_workbook_sheet_rows(file_id, "Google")
    export = load_workbook_sheet_rows(file_id, "Export")
    nord = load_workbook_sheet_rows(file_id, "NORD")
    aftership = load_workbook_sheet_rows(file_id, "AFTERSHIP")
    bloom_rows: list[dict[str, str]] = []
    try:
        matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
        sheet_names = pd.ExcelFile(matches[0]).sheet_names if matches else []
        bloom_sheet = next((name for name in sheet_names if "bloom" in normalized(name)), "")
        if bloom_sheet:
            bloom_rows = load_workbook_sheet_rows(file_id, bloom_sheet)
    except Exception:
        bloom_rows = []

    tracking_to_lines: dict[str, list[dict[str, str]]] = {}
    search_sources = ["AFTERSHIP", "NORD"] + (["Bloomingdales"] if bloom_rows else [])

    def add_tracking_line(
        source_code: str,
        tracking: str,
        order: str,
        sku: str,
        qty: str,
        customer: str = "",
    ) -> None:
        if not tracking or not order:
            return
        line = {
            "source_code": source_code,
            "order_number": normalize_order_number(order),
            "tracking_number": tracking,
            "customer_name": customer,
            "sku": sku,
            "qty": choose_quantity("", qty or "1"),
        }
        for candidate in tracking_lookup_candidates(tracking):
            bucket = tracking_to_lines.setdefault(normalized(candidate), [])
            if line not in bucket:
                bucket.append(line)

    for row in nord:
        tracking = row_value(row, ["Tracking number", "Tracking No", "Tracking"])
        order = normalize_order_number(row_value(row, ["SB Order Number", "SB Order #"]))
        sku = row_value(row, ["Offer SKU", "SKU", "Product SKU"])
        qty = row_value(row, ["Quantity", "Qty"])
        add_tracking_line("NDS", tracking, order, sku, qty)
    for row in aftership:
        tracking = row_value(row, ["Return Tracking number", "Tracking number", "Tracking"])
        order = normalize_order_number(row_value(row, ["SB Order Number", "SB Order #"]))
        sku = row_value(row, ["Return product SKU", "SKU", "Product SKU"])
        qty = row_value(row, ["SKU return quantity", "RMA return quantity", "Quantity", "Qty"])
        customer = row_value(row, ["Customer Name", "Customer"])
        add_tracking_line("WEB", tracking, order, sku, qty, customer)
    for row in bloom_rows:
        tracking = row_value(row, ["Tracking number", "Tracking No", "Tracking", "Return Tracking number"])
        order = normalize_order_number(row_value(row, ["SB Order Number", "SB Order #", "Order Number", "Order #"]))
        sku = row_value(row, ["SKU", "Offer SKU", "Return product SKU", "Product SKU"])
        qty = row_value(row, ["Quantity", "Qty", "SKU return quantity"])
        customer = row_value(row, ["Customer Name", "Customer"])
        add_tracking_line("BLM", tracking, order, sku, qty, customer)

    export_by_order: dict[str, dict[str, str]] = {}
    for row in export:
        external_order = row_value(row, ["External Order ID", "Order ID", "SB Order Number"])
        if external_order:
            order_key = normalized(external_order)
            export_by_order.setdefault(
                order_key,
                {
                    "customer_name": row_value(row, ["Customer Name", "Customer"]),
                    "sku": row_value(row, ["SKU", "Item SKU", "Product SKU"]),
                },
            )

    output_rows: list[dict[str, str]] = []
    warnings: list[str] = []

    for index, row in enumerate(google, start=2):
        carrier = row_value(row, ["CARRIER", "Carrier"])
        tracking = row_value(row, ["TRACKING NO", "Tracking Number", "Tracking"])
        qty = row_value(row, ["QTY", "Quantity"])
        if not tracking and not qty:
            continue

        lookup_candidates = tracking_lookup_candidates(tracking, carrier)
        cleaned_tracking = normalize_tracking_number(carrier, tracking)
        matched_lines: list[dict[str, str]] = []
        for candidate in lookup_candidates:
            if candidate:
                matched_lines = tracking_to_lines.get(normalized(candidate), [])
                if matched_lines:
                    for preferred_source in ["WEB", "NDS", "BLM"]:
                        preferred = [line for line in matched_lines if line.get("source_code") == preferred_source]
                        if preferred:
                            matched_lines = preferred
                            break
                    break

        if not matched_lines:
            matched_lines = [
                {
                    "source_code": "",
                    "order_number": "",
                    "tracking_number": tracking,
                    "customer_name": "",
                    "sku": "",
                    "qty": choose_quantity("", qty or "1"),
                }
            ]

        for line in matched_lines:
            order = line["order_number"]
            customer = line["customer_name"]
            sku = line["sku"]
            if order:
                order_norm = normalized(order)
                export_row = export_by_order.get(order_norm)
                if export_row:
                    if not customer:
                        customer = export_row["customer_name"]
                    if not sku:
                        sku = export_row["sku"]

            result = {
                "order_number": normalize_order_number(order),
                "tracking_number": cleaned_tracking or tracking,
                "customer_name": customer,
                "sku": sku,
                "qty": choose_quantity("", line["qty"] or qty or "1"),
                "source_code": line.get("source_code", ""),
            }
            output_rows.append(result)

            missing = [label for field, label in OUTPUT_FIELDS if not result.get(field)]
            if missing:
                source_text = ", ".join(search_sources)
                warnings.append(
                    f"Google row {index}: unable to parse tracking {tracking}. It was not found in {source_text}. "
                    "This return may be available in a later batch, or the customer may not have been marked as returning it yet."
                )

    output_rows = aggregate_detail_rows(output_rows)
    return output_rows, warnings[:100]


def numeric_quantity(value: str) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def add_quantities(left: str, right: str) -> str:
    left_num = numeric_quantity(left)
    right_num = numeric_quantity(right)
    if left_num is None or right_num is None:
        return left or right
    total = left_num + right_num
    return str(int(total)) if total.is_integer() else str(total)


def last4(value: str) -> str:
    digits = digits_only(value)
    return digits[-4:] if len(digits) >= 4 else digits


def shipment_number_for_row(row: dict[str, str]) -> str:
    order = display_order_number(row.get("order_number", ""))
    tracking_tail = last4(row.get("tracking_number", ""))
    source = row.get("source_code", "") or "UNK"
    if not order:
        return ""
    if tracking_tail:
        return f"RTS {source} {order} ({tracking_tail})"
    return f"RTS {source} {order}"


def aggregate_detail_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, str, str], dict[str, str]] = {}
    passthrough: list[dict[str, str]] = []
    for row in rows:
        key = (
            row.get("order_number", ""),
            row.get("tracking_number", ""),
            row.get("customer_name", ""),
            row.get("sku", ""),
        )
        if not row.get("order_number") or not row.get("sku"):
            passthrough.append(row)
            continue
        if key not in grouped:
            grouped[key] = dict(row)
        else:
            grouped[key]["qty"] = add_quantities(grouped[key].get("qty", ""), row.get("qty", ""))
    return list(grouped.values()) + passthrough


def platform_row(row: dict[str, str]) -> dict[str, str]:
    today = date.today().isoformat()
    return {
        "Shipment # *": shipment_number_for_row(row) or normalize_order_number(row.get("order_number", "")),
        "Date Sent Out *": today,
        "Receiving Date *": today,
        "Shipment Type": "",
        "Inbound Pallets": "",
        "Product Variant SKU *": row.get("sku", ""),
        "Lot #": "",
        "Cases *": "1",
        "Units per Case *": row.get("qty", "") or "1",
        "Tracking Info": row.get("tracking_number", ""),
        "Notes": title_case_name(row.get("customer_name", "")),
    }


def to_platform_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [platform_row(row) for row in rows if is_resolved_return_row(row)]


def report_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    report: list[dict[str, str]] = []
    for row in rows:
        missing = [label for field, label in OUTPUT_FIELDS if not row.get(field)]
        report.append(
            {
                "Order Number": normalize_order_number(row.get("order_number", "")),
                "Tracking Number": row.get("tracking_number", ""),
                "Customer Name": title_case_name(row.get("customer_name", "")),
                "SKU": row.get("sku", ""),
                "Qty": row.get("qty", ""),
                "Status": "Missing " + ", ".join(missing) if missing else "Ready",
            }
        )
    return report


def write_report(rows: list[dict[str, str]], warnings: list[str]) -> Path:
    output_path = OUTPUT_DIR / f"inbound_shipment_report_{uuid.uuid4().hex[:8]}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Order Number", "Tracking Number", "Customer Name", "SKU", "Qty", "Status"])
        for row in report_rows(rows):
            writer.writerow([row["Order Number"], row["Tracking Number"], row["Customer Name"], row["SKU"], row["Qty"], row["Status"]])
        if warnings:
            writer.writerow([])
            writer.writerow(["Warnings"])
            for warning in warnings:
                writer.writerow([warning])
    return output_path


def write_platform_csv(rows: list[dict[str, str]]) -> Path:
    output_path = OUTPUT_DIR / f"bulk_inbound_shipment_upload_{uuid.uuid4().hex[:8]}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLATFORM_FIELDS)
        writer.writeheader()
        writer.writerows(to_platform_rows(rows))
    return output_path


def error_report_rows(rows: list[dict[str, str]], warnings: list[str]) -> list[dict[str, str]]:
    unresolved = [row for row in rows if not is_resolved_return_row(row)]
    report: list[dict[str, str]] = []
    for index, row in enumerate(unresolved):
        warning = warnings[index] if index < len(warnings) else ""
        report.append(
            {
                "Tracking Number": row.get("tracking_number", ""),
                "Order Number": row.get("order_number", ""),
                "SKU": row.get("sku", ""),
                "Qty": row.get("qty", ""),
                "Issue": warning or "Unable to parse this return from the available source tabs.",
            }
        )
    return report


def write_error_report(rows: list[dict[str, str]], warnings: list[str]) -> Path | None:
    report = error_report_rows(rows, warnings)
    if not report:
        return None
    output_path = OUTPUT_DIR / f"inbound_unresolved_returns_{uuid.uuid4().hex[:8]}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Tracking Number", "Order Number", "SKU", "Qty", "Issue"])
        writer.writeheader()
        writer.writerows(report)
    return output_path


def parse_havn_email(text: str) -> dict[str, Any]:
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    order_match = re.search(r"Order\s*#?\s*:\s*([A-Za-z0-9-]+)", normalized_text, re.IGNORECASE)
    if not order_match:
        subject_match = re.search(r"Return Label Request:\s*([A-Za-z0-9-]+)", normalized_text, re.IGNORECASE)
        order = subject_match.group(1).strip() if subject_match else ""
    else:
        order = order_match.group(1).strip()

    sku_block = ""
    block_match = re.search(
        r"Item\(s\)\s*for\s*Return\s*:\s*(.*?)(?:\n\s*(?:Let me know|Thanks|Regards|Best|Mark from HAVN)\b|$)",
        normalized_text,
        re.IGNORECASE | re.DOTALL,
    )
    if block_match:
        sku_block = block_match.group(1)

    sku_candidates = re.findall(r"\b[A-Z0-9][A-Z0-9-]{2,}\b", sku_block)
    ignored = {"ORDER", "ITEM", "ITEMS", "RETURN", "THANKS", "HAVN", "TEAM"}
    skus = [sku for sku in sku_candidates if sku.upper() not in ignored and not sku.isdigit()]

    if not skus:
        skus = re.findall(r"\b[A-Z]{2,}[A-Z0-9-]{3,}\b", normalized_text)
        skus = [sku for sku in skus if sku.upper() not in ignored and not sku.isdigit()]

    deduped: list[str] = []
    for sku in skus:
        if sku not in deduped:
            deduped.append(sku)

    return {"order_number": order, "skus": deduped, "raw": text}


def havn_request_rows(requests: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for request_item in requests:
        order = cell_text(request_item.get("order_number", ""))
        for item in request_item.get("items", []):
            sku = cell_text(item.get("sku", ""))
            qty = choose_quantity("", cell_text(item.get("qty", "1")) or "1")
            status_parts = []
            if not order:
                status_parts.append("Order Number")
            if not sku:
                status_parts.append("SKU")
            status = "Missing " + ", ".join(status_parts) if status_parts else "Ready for inbound shipment upload"
            rows.append(
                {
                    "Order Number": f"{order} RET" if order and not order.endswith(" RET") else order,
                    "Source Order": order,
                    "SKU": sku,
                    "Qty": qty,
                    "Status": status,
                }
            )
    return rows


def write_havn_request_report(requests: list[dict[str, Any]]) -> Path:
    output_path = OUTPUT_DIR / f"havn_return_requests_{uuid.uuid4().hex[:8]}.csv"
    rows = havn_request_rows(requests)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Order Number", "Source Order", "SKU", "Qty", "Status"])
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def parse_shopify_rows(csv_text: str) -> list[dict[str, str]]:
    if not csv_text.strip():
        return []
    reader = csv.DictReader(io.StringIO(csv_text))
    return [{key: cell_text(value) for key, value in row.items()} for row in reader]


def shopify_by_order(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in rows:
        order = row_value(row, ["Shopify Order#", "Order Number", "Order #"])
        if order:
            lookup[normalized(order)] = row
    return lookup


def package_for_sku(sku: str, qty: str = "1") -> dict[str, str]:
    sku_norm = normalized(sku)
    qty_num = numeric_quantity(qty) or 1
    if "blkt" in sku_norm or qty_num > 1:
        if qty_num >= 4:
            return {"Package Type": "Box", "Package Length": "20", "Package Width": "20", "Package Height": "20"}
        return {"Package Type": "Box", "Package Length": "16", "Package Width": "12", "Package Height": "8"}
    return {"Package Type": "Mailer", "Package Length": "10", "Package Width": "13", "Package Height": "0"}


def havn_validation_rows(requests: list[dict[str, Any]], shopify_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_order = shopify_by_order(shopify_rows)
    validation: list[dict[str, str]] = []
    for row in havn_request_rows(requests):
        source_order = row["Source Order"]
        shopify = by_order.get(normalized(source_order))
        shopify_skus = split_skus(row_value(shopify or {}, ["SKUs", "SKU", "Item SKU"]))
        status = "Matched"
        if not shopify:
            status = "Order not found in Shopify CSV"
        elif row["SKU"] not in shopify_skus:
            status = "SKU not found on Shopify order"
        validation.append(
            {
                "Order Number": row["Order Number"],
                "SKU": row["SKU"],
                "Shopify SKUs": ", ".join(shopify_skus),
                "Status": status,
            }
        )
    return validation


def write_havn_validation_report(requests: list[dict[str, Any]], shopify_rows: list[dict[str, str]]) -> Path:
    output_path = OUTPUT_DIR / f"havn_sku_validation_{uuid.uuid4().hex[:8]}.csv"
    rows = havn_validation_rows(requests, shopify_rows)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Order Number", "SKU", "Shopify SKUs", "Status"])
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def write_havn_order_import(requests: list[dict[str, Any]], shopify_rows: list[dict[str, str]]) -> Path:
    output_path = OUTPUT_DIR / f"HAVN_RET_IMPORT_{uuid.uuid4().hex[:8]}.csv"
    by_order = shopify_by_order(shopify_rows)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=HAVN_ORDER_IMPORT_FIELDS)
        writer.writeheader()
        for row in havn_request_rows(requests):
            shopify = by_order.get(normalized(row["Source Order"]), {})
            full_name = title_case_name(row_value(shopify, ["Full Name", "Name", "Customer"]))
            package = package_for_sku(row["SKU"], row["Qty"])
            writer.writerow(
                {
                    "Order Number": row["Order Number"],
                    "Order Date": "",
                    "Requested Service": "",
                    "Item SKU": row["SKU"],
                    "Item Unit Price": "",
                    "Item Quantity": row["Qty"],
                    "HS Code": "",
                    "Country Of Origin": "",
                    "Company Name": "Basic 3PL RMA",
                    "First Name": "HAVN",
                    "Last Name": "RETURN",
                    "Address Line 1": "7050 New Buffington Road",
                    "Address Line 2": "#50872546",
                    "City": "Florence",
                    "State/Province": "KY",
                    "Zip/Postal Code": "41042",
                    "Country": "US",
                    "Email": "hello@havnwear.com",
                    "Phone": "14088285055",
                    "Notes": "",
                    "Signature Required": "",
                    "Package SKU": "",
                    "Package Type": package["Package Type"],
                    "Package Length": package["Package Length"],
                    "Package Width": package["Package Width"],
                    "Package Height": package["Package Height"],
                    "Declared Value": "",
                    "Package #": "",
                    "Origin Address Line 1": row_value(shopify, ["Address Line 1"]),
                    "Origin Address Line 2": row_value(shopify, ["Address Line 2"]),
                    "Origin City": row_value(shopify, ["City"]),
                    "Origin State/Province": row_value(shopify, ["State", "State/Province"]),
                    "Origin Zip/Postal Code": row_value(shopify, ["Zipcode", "Zip/Postal Code", "Zip"]),
                    "Origin Country": row_value(shopify, ["Country Code", "Country"]) or "US",
                    "Origin Company": "Basic_3PL_RMA",
                    "Origin Contact Name": full_name,
                    "Origin Phone": "14088285055",
                    "Origin Email": "hello@havnwear.com",
                }
            )
    return output_path


def write_havn_inbound_upload(requests: list[dict[str, Any]]) -> Path:
    output_path = OUTPUT_DIR / f"havn_inbound_shipment_upload_{uuid.uuid4().hex[:8]}.csv"
    today = date.today().isoformat()
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLATFORM_FIELDS)
        writer.writeheader()
        for row in havn_request_rows(requests):
            writer.writerow(
                {
                    "Shipment # *": row["Order Number"],
                    "Date Sent Out *": today,
                    "Receiving Date *": today,
                    "Shipment Type": "",
                    "Inbound Pallets": "",
                    "Product Variant SKU *": row["SKU"],
                    "Lot #": "",
                    "Cases *": row["Qty"],
                    "Units per Case *": "1",
                    "Tracking Info": "",
                    "Notes": "",
                }
            )
    return output_path


def havn_inbound_preview(requests: list[dict[str, Any]]) -> list[dict[str, str]]:
    today = date.today().isoformat()
    preview: list[dict[str, str]] = []
    for row in havn_request_rows(requests):
        preview.append(
            {
                "Shipment # *": row["Order Number"],
                "Date Sent Out *": today,
                "Receiving Date *": today,
                "Shipment Type": "",
                "Inbound Pallets": "",
                "Product Variant SKU *": row["SKU"],
                "Lot #": "",
                "Cases *": row["Qty"],
                "Units per Case *": "1",
                "Tracking Info": "",
                "Notes": "",
            }
        )
    return preview


def split_name(full_name: str) -> tuple[str, str]:
    name = title_case_name(full_name)
    parts = [part for part in name.split(" ") if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def split_skus(value: str) -> list[str]:
    pieces = re.split(r"[,;\n]+", cell_text(value))
    return [piece.strip() for piece in pieces if piece.strip()]


def read_csv_dicts(file_id: str) -> list[dict[str, str]]:
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    if not matches:
        raise ValueError(f"Uploaded file {file_id} was not found.")
    with matches[0].open(newline="", encoding="utf-8-sig") as handle:
        return [{key: cell_text(value) for key, value in row.items()} for row in csv.DictReader(handle)]


def outbound_order_rows(file_id: str) -> list[dict[str, str]]:
    source_rows = read_csv_dicts(file_id)
    output: list[dict[str, str]] = []
    for source in source_rows:
        order = row_value(source, ["Shopify Order#", "Order Number", "Order #"])
        first_name, last_name = split_name(row_value(source, ["Full Name", "Name", "Customer"]))
        skus = split_skus(row_value(source, ["SKUs", "SKU", "Item SKU"]))
        if not skus:
            skus = [""]
        for sku in skus:
            output.append(
                {
                    "Order Number": order,
                    "Order Date": "",
                    "Requested Service": "",
                    "Item SKU": sku,
                    "Item Unit Price": "",
                    "Item Quantity": "1",
                    "HS Code": "",
                    "Country Of Origin": "",
                    "Company Name": "",
                    "First Name": first_name,
                    "Last Name": last_name,
                    "Address Line 1": row_value(source, ["Address Line 1"]),
                    "Address Line 2": row_value(source, ["Address Line 2"]),
                    "City": row_value(source, ["City"]),
                    "State/Province": row_value(source, ["State", "State/Province"]),
                    "Zip/Postal Code": row_value(source, ["Zipcode", "Zip/Postal Code", "Zip"]),
                    "Country": row_value(source, ["Country Code", "Country"]),
                    "Email": "",
                    "Phone": "",
                    "Notes": "",
                    "Signature Required": "",
                    "Package SKU": "",
                    "Package Type": "",
                    "Package Length": "",
                    "Package Width": "",
                    "Package Height": "",
                    "Declared Value": "",
                    "Package #": "",
                }
            )
    return output


def write_outbound_order_import(rows: list[dict[str, str]]) -> Path:
    output_path = OUTPUT_DIR / f"Soapbox_Import_Order_{uuid.uuid4().hex[:8]}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOAPBOX_ORDER_IMPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def outbound_report_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    report: list[dict[str, str]] = []
    for row in rows:
        missing = []
        for field in ["Order Number", "First Name", "Last Name", "Address Line 1", "City", "State/Province", "Zip/Postal Code", "Country", "Item SKU"]:
            if not row.get(field):
                missing.append(field)
        report.append(
            {
                "Order Number": row.get("Order Number", ""),
                "Name": f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip(),
                "SKU": row.get("Item SKU", ""),
                "Address": ", ".join([part for part in [row.get("Address Line 1", ""), row.get("Address Line 2", ""), row.get("City", ""), row.get("State/Province", ""), row.get("Zip/Postal Code", "")] if part]),
                "Status": "Missing " + ", ".join(missing) if missing else "Ready",
            }
        )
    return report


def version_tuple(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lower().lstrip("v")
    parts = []
    for part in re.split(r"[^0-9]+", cleaned):
        if part:
            parts.append(int(part))
    return tuple(parts or [0])


def check_for_update() -> dict[str, Any]:
    try:
        request = urllib.request.Request(
            GITHUB_LATEST_RELEASE_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "ReturnsShipmentBuilder",
            },
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "ok": True,
                "current_version": APP_VERSION,
                "latest_version": APP_VERSION,
                "update_available": False,
                "release_url": "",
                "download_url": "",
                "message": "No published updates yet.",
            }
        return {
            "ok": False,
            "current_version": APP_VERSION,
            "message": f"Could not check for updates: {exc}",
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "current_version": APP_VERSION,
            "message": f"Could not check for updates: {exc}",
        }

    latest = cell_text(payload.get("tag_name", ""))
    latest_url = cell_text(payload.get("html_url", ""))
    assets = payload.get("assets") or []
    zip_asset = next(
        (
            asset
            for asset in assets
            if str(asset.get("name", "")).lower().endswith(".zip")
        ),
        None,
    )
    download_url = cell_text((zip_asset or {}).get("browser_download_url", "")) or latest_url
    has_update = bool(latest and version_tuple(latest) > version_tuple(APP_VERSION))
    return {
        "ok": True,
        "current_version": APP_VERSION,
        "latest_version": latest,
        "update_available": has_update,
        "release_url": latest_url,
        "download_url": download_url,
        "message": "Update available." if has_update else "You are running the latest version.",
    }


def value_from(row: dict[str, Any], column: str) -> str:
    if not column:
        return ""
    return cell_text(row.get(column, ""))


def build_merge_key(mapped: dict[str, str], row: dict[str, Any], fallback: str) -> str:
    order = value_from(row, mapped.get("order_number", ""))
    sku = value_from(row, mapped.get("sku", ""))
    tracking = value_from(row, mapped.get("tracking_number", ""))
    customer = value_from(row, mapped.get("customer_name", ""))

    if order and sku:
        return f"order-sku::{normalized(order)}::{normalized(sku)}"
    if order:
        return f"order::{normalized(order)}"
    if tracking:
        return f"tracking::{normalized(tracking)}"
    if sku and customer:
        return f"sku-customer::{normalized(sku)}::{normalized(customer)}"
    return fallback


def merge_rows(files: list[dict[str, Any]], mappings: dict[str, dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    entries: list[dict[str, Any]] = []
    order_lookup: dict[str, dict[str, str]] = {}
    warnings: list[str] = []

    for file_info in files:
        file_id = file_info["file_id"]
        filename = file_info["filename"]
        mapped = mappings.get(file_id, {})
        rows = load_file_rows(file_id)

        if not any(mapped.get(field) for field, _label in OUTPUT_FIELDS):
            warnings.append(f"{filename}: no mapped output columns were selected.")
            continue

        for row_index, row in enumerate(rows, start=2):
            values = {
                field: value_from(row, mapped.get(field, ""))
                for field, _label in OUTPUT_FIELDS
            }
            if not any(values.values()):
                continue

            entry = {
                "file_id": file_id,
                "filename": filename,
                "row_index": row_index,
                "values": values,
                "fallback_key": f"{file_id}:{row_index}",
            }
            entries.append(entry)

            order_key = normalized(values.get("order_number", ""))
            if order_key:
                order_lookup.setdefault(order_key, {field: "" for field, _label in OUTPUT_FIELDS})
                for field, value in values.items():
                    if value and not order_lookup[order_key][field]:
                        order_lookup[order_key][field] = value

    line_entries = [
        entry for entry in entries
        if entry["values"].get("sku") or entry["values"].get("qty")
    ]
    if not line_entries:
        line_entries = entries

    grouped: dict[str, dict[str, str]] = {}
    for entry in line_entries:
        values = entry["values"]
        order = values.get("order_number", "")
        sku = values.get("sku", "")
        tracking = values.get("tracking_number", "")
        customer = values.get("customer_name", "")
        if order and sku:
            key = f"order-sku::{normalized(order)}::{normalized(sku)}"
        elif order:
            key = f"order::{normalized(order)}"
        elif tracking:
            key = f"tracking::{normalized(tracking)}"
        elif sku and customer:
            key = f"sku-customer::{normalized(sku)}::{normalized(customer)}"
        else:
            key = entry["fallback_key"]

        if key not in grouped:
            grouped[key] = {field: "" for field, _label in OUTPUT_FIELDS}

        for field, value in values.items():
            if not value:
                continue
            if field == "qty":
                grouped[key][field] = add_quantities(grouped[key][field], choose_quantity("", value))
            elif not grouped[key][field]:
                grouped[key][field] = value

    for row in grouped.values():
        order_key = normalized(row.get("order_number", ""))
        if not order_key or order_key not in order_lookup:
            continue
        for field, value in order_lookup[order_key].items():
            if value and not row[field]:
                row[field] = value

    output_rows = list(grouped.values())
    output_rows = [row for row in output_rows if row.get("order_number") or row.get("sku")]
    output_rows.sort(key=lambda row: (row.get("order_number", ""), row.get("sku", "")))

    for row in output_rows:
        missing = [label for field, label in OUTPUT_FIELDS if not row.get(field)]
        if missing:
            descriptor = row.get("order_number") or row.get("sku") or "row"
            warnings.append(f"{descriptor}: missing {', '.join(missing)}.")

    return output_rows, warnings[:100]


def choose_quantity(current: str, incoming: str) -> str:
    if current:
        return current
    cleaned = incoming.replace(",", "").strip()
    try:
        number = float(cleaned)
    except ValueError:
        return incoming
    if number.is_integer():
        return str(int(number))
    return str(number)


def write_csv(rows: list[dict[str, str]]) -> Path:
    output_path = OUTPUT_DIR / f"inbound_shipment_{uuid.uuid4().hex[:8]}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=[field for field, _label in OUTPUT_FIELDS])
        writer.writeheader()
        writer.writerows(rows)
    return output_path


class UploadStorage:
    def __init__(self, filename: str, fileobj: Any):
        self.filename = filename
        self.file = fileobj

    def save(self, path: Path) -> None:
        self.file.seek(0)
        path.write_bytes(self.file.read())


class ShipmentHandler(BaseHTTPRequestHandler):
    server_version = "ShipmentCSV/1.0"

    def do_GET(self) -> None:
        if self.path == "/":
            self.send_bytes(HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path == "/api/update-check":
            self.send_json(check_for_update())
            return
        if self.path.startswith("/download/"):
            filename = Path(unquote(self.path.split("/download/", 1)[1])).name
            path = OUTPUT_DIR / filename
            if not path.exists():
                self.send_json({"error": "Download not found."}, HTTPStatus.NOT_FOUND)
                return
            mime = mimetypes.guess_type(path.name)[0] or "text/csv"
            headers = {"Content-Disposition": f'attachment; filename="{path.name}"'}
            self.send_bytes(path.read_bytes(), mime, headers)
            return
        self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/shutdown":
            self.send_json({"ok": True, "message": "Application is closing."})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path == "/api/analyze":
            self.handle_analyze()
            return
        if self.path == "/api/export":
            self.handle_export()
            return
        if self.path == "/api/havn/parse":
            self.handle_havn_parse()
            return
        if self.path == "/api/havn/export":
            self.handle_havn_export()
            return
        if self.path == "/api/outbound/generate":
            self.handle_outbound_generate()
            return
        self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def handle_analyze(self) -> None:
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                },
            )
            fields = form["files"] if "files" in form else []
            if not isinstance(fields, list):
                fields = [fields]
            uploads = [
                UploadStorage(field.filename or "upload.xlsx", field.file)
                for field in fields
                if getattr(field, "filename", None)
            ]
            if len(uploads) not in {1, 3}:
                self.send_json({"error": "Upload one tabbed workbook or exactly three spreadsheet files."}, HTTPStatus.BAD_REQUEST)
                return

            if len(uploads) == 1:
                file_id, filename = save_upload(uploads[0])
                matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
                if not matches or matches[0].suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
                    self.send_json({"error": "Tabbed mode requires an Excel workbook."}, HTTPStatus.BAD_REQUEST)
                    return
                sheet_names = pd.ExcelFile(matches[0]).sheet_names
                required = {"Google", "Export", "NORD", "AFTERSHIP"}
                missing = sorted(required - set(sheet_names))
                if missing:
                    self.send_json(
                        {"error": f"Tabbed workbook is missing required sheet(s): {', '.join(missing)}."},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                self.send_json(
                    {
                        "mode": "tabbed_workbook",
                        "workbook": {"file_id": file_id, "filename": filename, "sheets": sheet_names},
                    }
                )
                return

            payloads = [read_upload(upload) for upload in uploads]
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self.send_json({"mode": "three_files", "files": [payload.__dict__ for payload in payloads], "fields": OUTPUT_FIELDS})

    def handle_export(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if payload.get("mode") == "tabbed_workbook":
                rows, warnings = process_tabbed_workbook(payload["workbook"]["file_id"])
            else:
                rows, warnings = merge_rows(payload["files"], payload["mappings"])
            if not rows:
                self.send_json(
                    {"error": "No shipment rows could be created from the selected mappings."},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            output_path = write_platform_csv(rows)
            report_path = write_report(rows, warnings)
            error_path = write_error_report(rows, warnings)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        response = {
            "download_url": f"/download/{output_path.name}",
            "report_url": f"/download/{report_path.name}",
            "error_url": f"/download/{error_path.name}" if error_path else "",
            "row_count": len(rows),
            "upload_row_count": len(to_platform_rows(rows)),
            "error_count": len(error_report_rows(rows, warnings)),
            "warnings": warnings,
            "preview": to_platform_rows(rows)[:25],
            "report_preview": report_rows(rows)[:100],
            "error_preview": error_report_rows(rows, warnings)[:100],
        }
        self.send_json(response)

    def handle_havn_parse(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            parsed = parse_havn_email(payload.get("text", ""))
            if not parsed["order_number"] or not parsed["skus"]:
                self.send_json(
                    {
                        "error": "Could not find both an order number and at least one SKU in that pasted email.",
                        "parsed": parsed,
                    },
                    HTTPStatus.BAD_REQUEST,
                )
                return
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(parsed)

    def handle_havn_export(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            requests = payload.get("requests", [])
            if not requests:
                self.send_json({"error": "Add at least one Havn return email first."}, HTTPStatus.BAD_REQUEST)
                return
            report_path = write_havn_request_report(requests)
            upload_path = write_havn_inbound_upload(requests)
            rows = havn_request_rows(requests)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(
            {
                "report_url": f"/download/{report_path.name}",
                "upload_url": f"/download/{upload_path.name}",
                "row_count": len(rows),
                "preview": rows[:100],
                "upload_preview": havn_inbound_preview(requests)[:25],
            }
        )

    def handle_outbound_generate(self) -> None:
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                },
            )
            field = form["file"] if "file" in form else None
            if field is None or not getattr(field, "filename", None):
                self.send_json({"error": "Upload shopify_orders_shipping_skus.csv first."}, HTTPStatus.BAD_REQUEST)
                return
            file_id, _filename = save_upload(UploadStorage(field.filename, field.file))
            rows = outbound_order_rows(file_id)
            if not rows:
                self.send_json({"error": "No outbound order rows could be created."}, HTTPStatus.BAD_REQUEST)
                return
            output_path = write_outbound_order_import(rows)
            report = outbound_report_rows(rows)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(
            {
                "download_url": f"/download/{output_path.name}",
                "row_count": len(rows),
                "preview": rows[:50],
                "report_preview": report[:100],
            }
        )

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_bytes(
            json.dumps(payload).encode("utf-8"),
            "application/json; charset=utf-8",
            status=status,
        )

    def send_bytes(
        self,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")


HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Inbound Shipment CSV Builder</title>
  <style>
    :root {
      --bg: #f7f8fb;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #687386;
      --line: #dbe1ea;
      --accent: #f59231;
      --accent-dark: #d97814;
      --warn: #9a3412;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 "Segoe UI", system-ui, -apple-system, sans-serif;
    }
    header {
      padding: 24px 32px 16px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }
    .header-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .subtle { color: var(--muted); }
    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 24px auto 48px;
      display: grid;
      gap: 18px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    h2 {
      margin: 0 0 14px;
      font-size: 16px;
      letter-spacing: 0;
    }
    input[type=file], textarea {
      display: block;
      width: 100%;
      padding: 18px;
      border: 1px dashed #9aa7b7;
      border-radius: 8px;
      background: #fbfcfe;
      font: inherit;
    }
    textarea {
      min-height: 180px;
      resize: vertical;
      border-style: solid;
      padding: 12px;
    }
    button, .download {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      padding: 0 14px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      font-weight: 650;
      text-decoration: none;
      cursor: pointer;
    }
    button:hover, .download:hover { background: var(--accent-dark); }
    button.secondary {
      background: #e8eef5;
      color: #243244;
    }
    button.secondary:hover { background: #cbd5e1; }
    button:disabled {
      opacity: .45;
      cursor: not-allowed;
    }
    .row {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 14px;
    }
    .tabs {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .tab {
      background: #e8eef5;
      color: #243244;
    }
    .tab.active {
      background: var(--accent);
      color: #fff;
    }
    .files {
      display: grid;
      gap: 16px;
    }
    .file {
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .file-title {
      padding: 12px 14px;
      background: #eef4f7;
      font-weight: 700;
      display: flex;
      justify-content: space-between;
      gap: 12px;
    }
    .mapping {
      display: grid;
      grid-template-columns: repeat(5, minmax(130px, 1fr));
      gap: 10px;
      padding: 14px;
    }
    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    select {
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 8px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }
    .preview {
      overflow: auto;
      border-top: 1px solid var(--line);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }
    th, td {
      border-bottom: 1px solid #edf1f5;
      padding: 8px 10px;
      text-align: left;
      white-space: nowrap;
      max-width: 240px;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    th {
      color: #344255;
      background: #fbfcfe;
      font-size: 12px;
    }
    .notice {
      padding: 12px 14px;
      border-radius: 8px;
      background: #fff7ed;
      color: var(--warn);
      border: 1px solid #fed7aa;
    }
    .success {
      padding: 14px;
      border: 1px solid #b7e4d5;
      background: #f0fdf9;
      border-radius: 8px;
    }
    .update-banner {
      display: none;
      padding: 12px 32px;
      border-bottom: 1px solid var(--line);
      background: #fff7ed;
      color: #7c2d12;
    }
    .update-banner a {
      color: #0f766e;
      font-weight: 700;
    }
    tr.problem td {
      background: #fff7ed;
    }
    .hidden { display: none; }
    @media (max-width: 860px) {
      header { padding-inline: 18px; }
      .mapping { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div id="updateBanner" class="update-banner"></div>
  <header>
    <div class="header-top">
      <div>
        <h1>Inbound Shipment CSV Builder</h1>
        <div class="subtle">Upload one tabbed workbook or three spreadsheets, confirm the columns when needed, then export the platform-ready CSV.</div>
      </div>
      <button class="secondary" id="closeApp" type="button">Close App</button>
    </div>
  </header>
  <main>
    <div class="tabs">
      <button class="tab active" id="christyTab">Christy / Spreadsheet Upload</button>
      <button class="tab" id="havnTab">Havn Email Paste</button>
      <button class="tab" id="outboundTab">Outbound Replacement</button>
    </div>

    <div id="christyApp">
    <section>
      <h2>Upload</h2>
      <input id="files" type="file" multiple accept=".xlsx,.xls,.xlsm,.csv">
      <div class="row">
        <button id="analyze">Analyze spreadsheets</button>
        <span id="status" class="subtle"></span>
      </div>
    </section>

    <section id="mappingSection" class="hidden">
      <h2>Column Mapping</h2>
      <div id="fileList" class="files"></div>
      <div class="row">
        <button id="export">Create CSV</button>
      </div>
    </section>

    <section id="resultSection" class="hidden">
      <h2>Result</h2>
      <div id="result"></div>
    </section>
    </div>

    <div id="havnApp" class="hidden">
      <section>
        <h2>Havn Return Email</h2>
        <textarea id="havnEmail" placeholder="Paste one Havn return label request email here..."></textarea>
        <div class="row">
          <button id="havnAdd">Add Email to List</button>
          <button id="havnClear" class="tab">Clear List</button>
          <span id="havnStatus" class="subtle"></span>
        </div>
      </section>

      <section>
        <h2>Havn Return List</h2>
        <div id="havnList" class="subtle">No Havn emails added yet.</div>
        <div class="row">
          <button id="havnExport">Generate Havn Files</button>
        </div>
      </section>

      <section id="havnResultSection" class="hidden">
        <h2>Havn Result</h2>
        <div id="havnResult"></div>
      </section>
    </div>

    <div id="outboundApp" class="hidden">
      <section>
        <h2>Outbound Replacement Order</h2>
        <input id="outboundFile" type="file" accept=".csv">
        <div class="row">
          <button id="outboundGenerate">Generate Soapbox Import Order CSV</button>
          <span id="outboundStatus" class="subtle"></span>
        </div>
      </section>
      <section id="outboundResultSection" class="hidden">
        <h2>Outbound Result</h2>
        <div id="outboundResult"></div>
      </section>
    </div>
  </main>

  <script>
    const fields = [
      ["order_number", "Order Number"],
      ["tracking_number", "Tracking Number"],
      ["customer_name", "Customer Name"],
      ["sku", "SKU"],
      ["qty", "Qty"],
    ];
    let analyzedFiles = [];
    let analyzedWorkbook = null;
    let currentMode = "";
    let havnRequests = [];

    const statusEl = document.querySelector("#status");
    const filesEl = document.querySelector("#files");
    const fileListEl = document.querySelector("#fileList");
    const mappingSection = document.querySelector("#mappingSection");
    const resultSection = document.querySelector("#resultSection");
    const resultEl = document.querySelector("#result");
    const havnStatusEl = document.querySelector("#havnStatus");
    const havnListEl = document.querySelector("#havnList");
    const havnResultSection = document.querySelector("#havnResultSection");
    const havnResultEl = document.querySelector("#havnResult");
    const outboundStatusEl = document.querySelector("#outboundStatus");
    const outboundResultSection = document.querySelector("#outboundResultSection");
    const outboundResultEl = document.querySelector("#outboundResult");
    const updateBannerEl = document.querySelector("#updateBanner");

    checkForUpdates();

    document.querySelector("#christyTab").addEventListener("click", () => setAppTab("christy"));
    document.querySelector("#havnTab").addEventListener("click", () => setAppTab("havn"));
    document.querySelector("#outboundTab").addEventListener("click", () => setAppTab("outbound"));
    document.querySelector("#closeApp").addEventListener("click", async () => {
      try {
        await fetch("/api/shutdown", { method: "POST" });
        document.body.innerHTML = '<main><section><h2>Returns Shipment Builder is closed.</h2><div class="subtle">You can close this browser tab.</div></section></main>';
      } catch (error) {
        alert("Could not close the app from the browser. You can close it from Task Manager.");
      }
    });

    function setAppTab(tabName) {
      document.querySelector("#christyApp").classList.toggle("hidden", tabName !== "christy");
      document.querySelector("#havnApp").classList.toggle("hidden", tabName !== "havn");
      document.querySelector("#outboundApp").classList.toggle("hidden", tabName !== "outbound");
      document.querySelector("#christyTab").classList.toggle("active", tabName === "christy");
      document.querySelector("#havnTab").classList.toggle("active", tabName === "havn");
      document.querySelector("#outboundTab").classList.toggle("active", tabName === "outbound");
    }

    async function checkForUpdates() {
      try {
        const response = await fetch("/api/update-check", { cache: "no-store" });
        const data = await response.json();
        if (data.update_available) {
          updateBannerEl.innerHTML = `A newer version is available: ${escapeHtml(data.latest_version)}. <a href="${escapeHtml(data.download_url || data.release_url)}" target="_blank" rel="noreferrer">Download update</a>`;
          updateBannerEl.style.display = "block";
        } else if (!data.ok) {
          updateBannerEl.textContent = data.message || "Could not check for updates.";
          updateBannerEl.style.display = "block";
        }
      } catch (error) {
        updateBannerEl.textContent = "Could not check for updates.";
        updateBannerEl.style.display = "block";
      }
    }

    document.querySelector("#analyze").addEventListener("click", async () => {
      const selected = [...filesEl.files];
      resultSection.classList.add("hidden");
      if (![1, 3].includes(selected.length)) {
        statusEl.textContent = "Choose one tabbed workbook or exactly three spreadsheet files.";
        return;
      }
      statusEl.textContent = "Reading spreadsheets...";
      document.querySelector("#analyze").disabled = true;
      const form = new FormData();
      selected.forEach(file => form.append("files", file));
      try {
        const response = await fetch("/api/analyze", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) {
          statusEl.textContent = data.error || "Could not analyze files.";
          return;
        }
        currentMode = data.mode;
        analyzedFiles = data.files || [];
        analyzedWorkbook = data.workbook || null;
        renderMappings();
        statusEl.textContent = currentMode === "tabbed_workbook"
          ? "Tabbed workbook detected. The app will consolidate Google, NORD, AFTERSHIP, and Export."
          : "Review the auto-detected mappings below.";
        mappingSection.classList.remove("hidden");
      } catch (error) {
        statusEl.textContent = "The server stopped responding while reading the spreadsheet. Refresh and try again.";
      } finally {
        document.querySelector("#analyze").disabled = false;
      }
    });

    document.querySelector("#export").addEventListener("click", async () => {
      statusEl.textContent = "Creating CSV...";
      document.querySelector("#export").disabled = true;
      const mappings = {};
      analyzedFiles.forEach(file => {
        mappings[file.file_id] = {};
        fields.forEach(([field]) => {
          mappings[file.file_id][field] = document.querySelector(`[data-file="${file.file_id}"][data-field="${field}"]`).value;
        });
      });
      try {
        const response = await fetch("/api/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: currentMode, workbook: analyzedWorkbook, files: analyzedFiles, mappings }),
        });
        const data = await response.json();
        if (!response.ok) {
          statusEl.textContent = data.error || "Could not create CSV.";
          return;
        }
        statusEl.textContent = "CSV and report are ready.";
        renderResult(data);
      } catch (error) {
        statusEl.textContent = "The server stopped responding while creating the CSV. Refresh and try again.";
      } finally {
        document.querySelector("#export").disabled = false;
      }
    });

    document.querySelector("#havnAdd").addEventListener("click", async () => {
      const text = document.querySelector("#havnEmail").value.trim();
      havnResultSection.classList.add("hidden");
      if (!text) {
        havnStatusEl.textContent = "Paste one Havn email first.";
        return;
      }
      havnStatusEl.textContent = "Reading email...";
      document.querySelector("#havnAdd").disabled = true;
      try {
        const response = await fetch("/api/havn/parse", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        const data = await response.json();
        if (!response.ok) {
          havnStatusEl.textContent = data.error || "Could not parse that email.";
          return;
        }
        const incomingPairs = data.skus.map(sku => `${data.order_number.trim().toUpperCase()}|${sku.trim().toUpperCase()}`);
        const existingPairs = new Set();
        havnRequests.forEach(request => {
          request.items.forEach(item => {
            existingPairs.add(`${request.order_number.trim().toUpperCase()}|${item.sku.trim().toUpperCase()}`);
          });
        });
        const duplicatePairs = incomingPairs.filter(pair => existingPairs.has(pair));
        if (duplicatePairs.length === incomingPairs.length) {
          havnStatusEl.textContent = `Already added: ${data.order_number} with the same SKU${data.skus.length === 1 ? "" : "s"}.`;
          return;
        }
        const newSkus = data.skus.filter((sku, index) => !existingPairs.has(incomingPairs[index]));
        if (duplicatePairs.length) {
          havnStatusEl.textContent = `Skipped ${duplicatePairs.length} duplicate SKU${duplicatePairs.length === 1 ? "" : "s"} for ${data.order_number}.`;
        }
        havnRequests.push({
          order_number: data.order_number,
          items: newSkus.map(sku => ({ sku, qty: "1" })),
        });
        document.querySelector("#havnEmail").value = "";
        if (!duplicatePairs.length) {
          havnStatusEl.textContent = `Added ${data.order_number} with ${newSkus.length} SKU${newSkus.length === 1 ? "" : "s"}.`;
        }
        renderHavnList();
      } catch (error) {
        havnStatusEl.textContent = "The server stopped responding while parsing the email.";
      } finally {
        document.querySelector("#havnAdd").disabled = false;
      }
    });

    document.querySelector("#havnClear").addEventListener("click", () => {
      havnRequests = [];
      havnResultSection.classList.add("hidden");
      havnStatusEl.textContent = "List cleared.";
      renderHavnList();
    });

    document.querySelector("#havnExport").addEventListener("click", async () => {
      if (!havnRequests.length) {
        havnStatusEl.textContent = "Add at least one Havn email first.";
        return;
      }
      havnStatusEl.textContent = "Generating Havn files...";
      document.querySelector("#havnExport").disabled = true;
      try {
        const response = await fetch("/api/havn/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ requests: havnRequests }),
        });
        const data = await response.json();
        if (!response.ok) {
          havnStatusEl.textContent = data.error || "Could not generate Havn files.";
          return;
        }
        havnStatusEl.textContent = "Havn inbound shipment CSV and report are ready.";
        renderHavnResult(data);
      } catch (error) {
        havnStatusEl.textContent = "The server stopped responding while generating Havn files.";
      } finally {
        document.querySelector("#havnExport").disabled = false;
      }
    });

    document.querySelector("#outboundGenerate").addEventListener("click", async () => {
      const file = document.querySelector("#outboundFile").files[0];
      outboundResultSection.classList.add("hidden");
      if (!file) {
        outboundStatusEl.textContent = "Upload shopify_orders_shipping_skus.csv first.";
        return;
      }
      outboundStatusEl.textContent = "Generating outbound replacement import...";
      document.querySelector("#outboundGenerate").disabled = true;
      const form = new FormData();
      form.append("file", file);
      try {
        const response = await fetch("/api/outbound/generate", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) {
          outboundStatusEl.textContent = data.error || "Could not generate outbound order import.";
          return;
        }
        outboundStatusEl.textContent = "Soapbox import order CSV is ready.";
        renderOutboundResult(data);
      } catch (error) {
        outboundStatusEl.textContent = "The server stopped responding while generating the outbound import.";
      } finally {
        document.querySelector("#outboundGenerate").disabled = false;
      }
    });

    function renderMappings() {
      fileListEl.innerHTML = "";
      if (currentMode === "tabbed_workbook") {
        fileListEl.innerHTML = `
          <article class="file">
            <div class="file-title">
              <span>${escapeHtml(analyzedWorkbook.filename)}</span>
              <span class="subtle">${analyzedWorkbook.sheets.length} tabs</span>
            </div>
            <div style="padding: 14px;" class="subtle">
              Google rows will be enriched by matching tracking numbers against NORD and AFTERSHIP, then matching the SB order number against Export for customer and SKU.
            </div>
          </article>
        `;
        return;
      }
      analyzedFiles.forEach(file => {
        const wrapper = document.createElement("article");
        wrapper.className = "file";
        const mappedCount = fields.filter(([field]) => file.detected[field]).length;
        wrapper.innerHTML = `
          <div class="file-title">
            <span>${escapeHtml(file.filename)}</span>
            <span class="subtle">${file.columns.length} columns, ${mappedCount} auto-mapped</span>
          </div>
          <div class="mapping">
            ${fields.map(([field, label]) => selectMarkup(file, field, label)).join("")}
          </div>
          <div class="preview">${previewTable(file)}</div>
        `;
        fileListEl.appendChild(wrapper);
      });
    }

    function renderHavnList() {
      if (!havnRequests.length) {
        havnListEl.className = "subtle";
        havnListEl.textContent = "No Havn emails added yet.";
        return;
      }
      const rows = [];
      havnRequests.forEach(request => {
        request.items.forEach(item => {
          rows.push({
            "Order Number": `${request.order_number} RET`,
            "SKU": item.sku,
            "Qty": item.qty || "1",
          });
        });
      });
      havnListEl.className = "preview";
      havnListEl.innerHTML = simpleTable(rows);
    }

    function renderHavnResult(data) {
      const preview = data.preview || [];
      const uploadPreview = data.upload_preview || [];
      havnResultEl.innerHTML = `
        <div class="success">
          <strong>${data.row_count} Havn return rows created.</strong>
          <div class="row">
            <a class="download" href="${data.report_url}">Download Havn Report</a>
            <a class="download" href="${data.upload_url}">Download Inbound Upload CSV</a>
          </div>
        </div>
        ${preview.length ? `
          <details style="margin-top: 18px;">
            <summary><strong>Report Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(preview)}
            </div>
          </details>
        ` : ""}
        ${uploadPreview.length ? `
          <details open style="margin-top: 18px;">
            <summary><strong>Inbound Upload Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(uploadPreview)}
            </div>
          </details>
        ` : ""}
        <div class="notice" style="margin-top: 12px;">
          This creates the inbound shipment from the pasted email order/SKU list. Tracking is blank until the return label tracking number is available.
        </div>
      `;
      havnResultSection.classList.remove("hidden");
    }

    function renderOutboundResult(data) {
      const reportPreview = data.report_preview || [];
      const preview = data.preview || [];
      outboundResultEl.innerHTML = `
        <div class="success">
          <strong>${data.row_count} outbound item rows created.</strong>
          <div class="row">
            <a class="download" href="${data.download_url}">Download Soapbox Import Order CSV</a>
          </div>
        </div>
        ${reportPreview.length ? `
          <details style="margin-top: 14px;">
            <summary><strong>Outbound Report Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(reportPreview)}
            </div>
          </details>
        ` : ""}
        ${preview.length ? `
          <details open style="margin-top: 14px;">
            <summary><strong>Soapbox CSV Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(preview)}
            </div>
          </details>
        ` : ""}
      `;
      outboundResultSection.classList.remove("hidden");
    }

    function simpleTable(rows) {
      if (!rows.length) return "";
      const columns = Object.keys(rows[0]);
      return `
        <table>
          <thead><tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.map(row => `<tr>${columns.map(column => `<td>${escapeHtml(row[column] || "")}</td>`).join("")}</tr>`).join("")}
          </tbody>
        </table>
      `;
    }

    function selectMarkup(file, field, label) {
      const options = [`<option value="">Not in this file</option>`].concat(
        file.columns.map(column => {
          const selected = file.detected[field] === column ? "selected" : "";
          return `<option ${selected} value="${escapeHtml(column)}">${escapeHtml(column)}</option>`;
        })
      ).join("");
      return `<label>${label}<select data-file="${file.file_id}" data-field="${field}">${options}</select></label>`;
    }

    function previewTable(file) {
      const columns = file.columns.slice(0, 8);
      return `
        <table>
          <thead><tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${file.preview.map(row => `<tr>${columns.map(column => `<td>${escapeHtml(row[column] || "")}</td>`).join("")}</tr>`).join("")}
          </tbody>
        </table>
      `;
    }

    function renderResult(data) {
      const warnings = data.warnings || [];
      const preview = data.preview || [];
      const reportPreview = data.report_preview || [];
      const errorPreview = data.error_preview || [];
      const columns = preview.length ? Object.keys(preview[0]) : [];
      const reportColumns = reportPreview.length ? Object.keys(reportPreview[0]) : [];
      const errorColumns = errorPreview.length ? Object.keys(errorPreview[0]) : [];
      resultEl.innerHTML = `
        <div class="success">
          <strong>${data.upload_row_count || data.row_count} upload rows created.</strong>
          <div class="row">
            <a class="download" href="${data.download_url}">Download Upload CSV</a>
            <a class="download" href="${data.report_url}">Download Report</a>
            ${data.error_url ? `<a class="download" href="${data.error_url}">Download Error Report</a>` : ""}
          </div>
        </div>
        ${errorPreview.length ? `
          <div class="notice" style="margin-top: 12px;">
            <strong>${data.error_count} unresolved return${data.error_count === 1 ? "" : "s"} were excluded from the upload CSV.</strong>
            Download the error report to review tracking numbers not found in the available source tabs.
          </div>
          <details style="margin-top: 18px;">
            <summary><strong>Error Report Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              <table>
                <thead><tr>${errorColumns.map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
                <tbody>
                  ${errorPreview.map(row => `<tr class="problem">${errorColumns.map(column => `<td>${escapeHtml(row[column] || "")}</td>`).join("")}</tr>`).join("")}
                </tbody>
              </table>
            </div>
          </details>
        ` : ""}
        ${reportPreview.length ? `
          <details style="margin-top: 18px;">
            <summary><strong>Report Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              <table>
                <thead><tr>${reportColumns.map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
                <tbody>
                  ${reportPreview.map(row => `<tr class="${row.Status === "Ready" ? "" : "problem"}">${reportColumns.map(column => `<td>${escapeHtml(row[column] || "")}</td>`).join("")}</tr>`).join("")}
                </tbody>
              </table>
            </div>
            ${data.row_count > reportPreview.length ? `<div class="subtle" style="margin-top: 8px;">Showing first ${reportPreview.length} report rows. Download the report for the full file.</div>` : ""}
          </details>
        ` : ""}
        ${preview.length ? `
          <details open style="margin-top: 18px;">
            <summary><strong>Upload CSV Preview</strong></summary>
            <div class="preview" style="margin-top: 12px; border: 1px solid var(--line); border-radius: 8px;">
              <table>
                <thead><tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
                <tbody>
                  ${preview.map(row => `<tr>${columns.map(column => `<td>${escapeHtml(row[column] || "")}</td>`).join("")}</tr>`).join("")}
                </tbody>
              </table>
            </div>
          </details>
        ` : ""}
      `;
      resultSection.classList.remove("hidden");
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      }[char]));
    }
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8776"))
    address = ("127.0.0.1", port)
    url = f"http://{address[0]}:{address[1]}/"
    print(f"Shipment CSV Builder running at {url}")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    ThreadingHTTPServer(address, ShipmentHandler).serve_forever()
