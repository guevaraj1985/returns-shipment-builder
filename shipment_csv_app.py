from __future__ import annotations

import csv
import cgi
import html
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

APP_VERSION = "1.8"
GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/guevaraj1985/returns-shipment-builder/releases/latest"

CODE128_PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
]

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

BULK_INBOUND_FIELD_LABELS = {
    "shipment_number": "Shipment # *",
    "date_sent_out": "Date Sent Out *",
    "receiving_date": "Receiving Date *",
    "shipment_type": "Shipment Type",
    "inbound_pallets": "Inbound Pallets",
    "sku": "Product Variant SKU *",
    "lot": "Lot #",
    "cases": "Cases *",
    "units_per_case": "Units per Case *",
    "tracking": "Tracking Info",
    "notes": "Notes",
}

BULK_INBOUND_ALIASES = {
    "shipment_number": [
        "shipment #",
        "shipment number",
        "shipment no",
        "shipment id",
        "po",
        "po #",
        "po number",
        "purchase order",
        "purchase order number",
        "bol",
        "bol #",
        "bol number",
        "bill of lading",
        "reference",
        "reference number",
        "ref #",
    ],
    "date_sent_out": [
        "date sent out",
        "ship date",
        "shipped date",
        "date shipped",
        "pickup date",
        "sent date",
        "departure date",
    ],
    "receiving_date": [
        "receiving date",
        "receive date",
        "arrival date",
        "delivery date",
        "eta",
        "expected date",
        "expected receipt",
    ],
    "shipment_type": ["shipment type", "type", "inbound type", "move type"],
    "inbound_pallets": [
        "inbound pallets",
        "pallets",
        "pallet count",
        "pallet qty",
        "plt",
        "plts",
        "number of pallets",
    ],
    "sku": [
        "product variant sku",
        "variant sku",
        "sku",
        "item sku",
        "product sku",
        "part number",
        "item number",
        "item #",
        "style",
        "upc",
        "asin",
    ],
    "lot": ["lot #", "lot", "lot number", "lot no", "batch", "batch number"],
    "cases": [
        "cases",
        "case",
        "case qty",
        "case count",
        "cartons",
        "carton",
        "carton qty",
        "ctn",
        "ctns",
        "boxes",
        "box qty",
        "qty cases",
    ],
    "units_per_case": [
        "units per case",
        "units/case",
        "units per carton",
        "units/carton",
        "pcs per case",
        "pcs/case",
        "each per case",
        "eaches per case",
        "case pack",
        "pack size",
        "inner pack",
    ],
    "tracking": [
        "tracking info",
        "tracking",
        "tracking number",
        "tracking #",
        "pro number",
        "pro #",
        "carrier pro",
        "seal",
        "seal number",
    ],
    "notes": ["notes", "memo", "comments", "description", "product name", "item description"],
}

LABEL_ALIASES = {
    "shipment_number": BULK_INBOUND_ALIASES["shipment_number"],
    "carton_number": [
        "carton number",
        "carton #",
        "carton no",
        "carton id",
        "box number",
        "box #",
        "box id",
        "case number",
        "case #",
        "package number",
        "package #",
        "lp",
        "lpn",
        "license plate",
    ],
    "sku": BULK_INBOUND_ALIASES["sku"],
    "product_name": [
        "product name",
        "item name",
        "description",
        "item description",
        "product description",
        "title",
        "name",
        "notes",
    ],
    "quantity": [
        "qty",
        "quantity",
        "unit qty",
        "units",
        "eaches",
        "pcs",
        "pieces",
        "item quantity",
    ],
    "cases": BULK_INBOUND_ALIASES["cases"],
    "units_per_case": BULK_INBOUND_ALIASES["units_per_case"],
    "lot": BULK_INBOUND_ALIASES["lot"],
    "tracking": BULK_INBOUND_ALIASES["tracking"],
    "po": ["po", "po #", "po number", "purchase order", "purchase order number"],
    "vendor": ["vendor", "supplier", "brand", "customer", "company"],
    "company_name": ["company name", "company name (from winit)", "customer name", "client name", "account name", "company", "customer", "vendor"],
    "company_id": ["company id", "company id (from winit)", "winit company id", "winit id", "customer id", "client id", "account id"],
}

PRODUCT_VARIANT_SKU_ALIASES = [
    "Variant SKU*",
    "Variant SKU",
    "Product Variant SKU",
    "SKU",
    "Item SKU",
]

PRODUCT_VARIANT_FIELDS = [
    "Product Name*",
    "Fulfillment SKU",
    "Product Material",
    "Customs Category",
    "Country of Origin",
    "Variant Name*",
    "Variant SKU*",
    "UPC",
    "Active? (Y/N)",
    "Ship in Product Packaging? (Y/N)",
    "Sync Inventory? (Y/N)",
    "Weight (oz)",
    "Length",
    "Width",
    "Height",
    "HS Code (numeric only)",
    "Country of Origin",
    "Warehouse Code*",
    "Warehouse Location",
    "Warehouse Qty",
    "Lot ID",
    "Vendor ID",
    "Received Date",
    "Production Date",
]

PRODUCT_LISTING_ALIASES = {
    "product_name": ["Product Name", "Item Name", "Description", "Product", "Title"],
    "fulfillment_sku": ["Fulfillment SKU", "Fulfillment Sku", "SKU", "Item SKU", "Product SKU"],
    "material": ["Product Material", "Material", "Fabric"],
    "customs_category": ["Customs Category", "Category", "Product Category"],
    "country": ["Country of Origin", "COO", "Origin Country", "Made In"],
    "variant_name": ["Variant Name", "Variant", "Option", "Size", "Color", "Description"],
    "variant_sku": ["Variant SKU", "SKU", "Item SKU", "Product SKU", "Part Number", "Style"],
    "upc": ["UPC", "Barcode", "GTIN", "EAN"],
    "active": ["Active", "Active? (Y/N)", "Enabled"],
    "packaging": ["Ship in Product Packaging", "SIPP", "Ships In Own Packaging"],
    "sync_inventory": ["Sync Inventory", "Inventory Sync"],
    "weight": ["Weight (oz)", "Weight", "Oz", "Ounces"],
    "length": ["Length", "L"],
    "width": ["Width", "W"],
    "height": ["Height", "H"],
    "hs_code": ["HS Code", "HTS Code", "Tariff Code", "Harmonized Code"],
    "warehouse_code": ["Warehouse Code", "Warehouse", "WH Code"],
    "warehouse_location": ["Warehouse Location", "Location", "Bin"],
    "warehouse_qty": ["Warehouse Qty", "On Hand", "Inventory", "Quantity", "Qty"],
    "lot": ["Lot ID", "Lot", "Batch"],
    "vendor": ["Vendor ID", "Vendor", "Supplier"],
    "received_date": ["Received Date", "Receipt Date"],
    "production_date": ["Production Date", "Manufactured Date", "MFG Date"],
}

PDF_TABLE_HEADER_WORDS = [
    "sku",
    "item",
    "part",
    "style",
    "upc",
    "cases",
    "cartons",
    "qty",
    "units",
    "case",
    "lot",
    "pallet",
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

OUTBOUND_ORDER_ALIASES = [
    "Shopify Order#",
    "Shopify Order #",
    "Shopify Order",
    "Shopify Order Number",
    "Shipment # *",
    "Shipment #",
    "Shipment Number",
    "Shipment",
    "Order Number",
    "Order #",
    "Customer Order Number",
    "Reference Order Number",
]

OUTBOUND_SKU_ALIASES = [
    "SKUs",
    "SKU",
    "Item SKU",
    "Product Variant SKU *",
    "Product Variant SKU",
    "Variant SKU",
]

OUTBOUND_QTY_ALIASES = [
    "Qty",
    "Quantity",
    "Item Quantity",
    "Units per Case *",
    "Units per Case",
    "Cases *",
    "Cases",
]

HAVN_DESTINATION_FIELDS = {
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
}

HAVN_ORIGIN_DEFAULTS = {
    "Origin Company": "Basic_3PL_RMA",
    "Origin Phone": "14088285055",
    "Origin Email": "hello@havnwear.com",
}

SKU_PACKAGE_DEFAULTS = {
    "FD-PCAP-BLK-1": ("Box", "24", "16", "12"),
    "FD-PJSET-HNVY-L": ("Box", "20", "14", "11"),
    "FD-PJSET-HNVY-M": ("Box", "24", "16", "12"),
    "FD-PJSET-HNVY-S": ("Box", "16", "12", "8"),
    "FD-UCAP-BLK-1": ("Box", "12", "8", "6"),
    "FD-UCAP-CSMR-1": ("Box", "12", "8", "6"),
    "FD-UCAP-HGRY-1": ("Box", "12", "8", "6"),
    "FD-UCAP-LIVY-1": ("Box", "24", "16", "12"),
    "FD-UCAP-NVY-1": ("Box", "12", "8", "6"),
    "FD-UCAP-PUR-1": ("Box", "16", "12", "8"),
    "FD-UJGR-BLK-M": ("Box", "24", "16", "12"),
    "FD-UJGR-NVY-M": ("Box", "24", "16", "12"),
    "FD-ULGHTBNE-BLK-1": ("Box", "8", "6", "4"),
    "FD-ULGHTBNE-GRY-1": ("Box", "8", "6", "4"),
    "FD-ULGHTBNE-WHT-1": ("Box", "12", "8", "6"),
    "FD2-BLKT-BEI": ("Box", "12", "8", "6"),
    "FD2-BLKT-BEI-LARG": ("Box", "16", "12", "9"),
    "FD2-BLKT-BORD-LARG": ("Box", "16", "12", "8"),
    "FD2-BLKT-GRY-LARG": ("Box", "20", "14", "11"),
    "FD2-MBRF-BLK-M": ("Mailer", "16", "15", "0"),
    "FD2-MBRF-BLK-S": ("Box", "12", "8", "6"),
    "FD2-MBRF-BLK-XXL": ("Mailer", "14", "12", "0"),
    "FD2-MTS-BLK-XL": ("Box", "12", "8", "6"),
    "FD2-MTS-BLK-XXL": ("Mailer", "15", "12", "0"),
    "FD2-MTS-ETH-M": ("Box", "24", "16", "12"),
    "FD2-MTS-SPAP-M": ("Box", "24", "16", "12"),
    "FD2-UBNE-BLK-1": ("Box", "12", "8", "6"),
    "FD2-UBNE-NAV-1": ("Box", "12", "8", "6"),
    "FD2-UBNE-WHT-1": ("Box", "14", "13", "3"),
    "FD2-WTS-BLK-XL": ("Box", "12", "8", "6"),
    "FD2-WTS-HNVY-L": ("Box", "12", "8", "6"),
    "FD2-WTS-HNVY-M": ("Box", "12", "8", "6"),
    "FD2-WTS-HNVY-XL": ("Box", "16", "12", "8"),
    "FD3-MTS-BLK-L": ("Mailer", "16", "12", "0"),
    "FD3-MTS-BLK-M": ("Box", "24", "16", "12"),
    "LMB22-WTS-FGRN-M": ("Box", "12", "8", "6"),
    "LMB22-WTS-FGRN-XXL": ("Box", "8", "6", "4"),
    "WSTP-LTPPD-BLK": ("Box", "20", "14", "11"),
}

LIGHTSOURCE_SB_IMPORT_FIELDS = [
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

LIGHTSOURCE_FEDEX_IMPORT_FIELDS = [
    "reference",
    "serviceType",
    "shipmentType",
    "senderContactName",
    "senderCompany",
    "senderContactNumber",
    "senderLine1",
    "senderLine2",
    "senderPostcode",
    "senderCity",
    "senderState",
    "senderCountry",
    "recipientCompany",
    "recipientContactName",
    "recipientLine1",
    "recipientLine2",
    "recipientCity",
    "recipientState",
    "recipientPostcode",
    "recipientCountry",
    "recipientEmail",
    "recipientContactNumber",
    "numberOfPackages",
    "packageWeight",
    "weightUnits",
    "length",
    "width",
    "height",
    "packageType",
    "currencyType",
    "paymentType",
    "payerAccountNumber",
    "taxPayerAccount",
    "taxPaymentType",
]

LIGHTSOURCE_FEDEX_DEFAULT_ROW = [
    "",
    "FEDEX_GROUND",
    "OUTBOUND",
    "Shipping Dept.",
    "Exfluential",
    "7145085990",
    "185 TECHNOLOGY DR",
    "STE 150",
    "926182421",
    "IRVINE",
    "CA",
    "US",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "US",
    "",
    "",
    "1",
    "",
    "LBS",
    "",
    "",
    "",
    "YOUR_PACKAGING",
    "USD",
    "THIRD_PARTY",
    "200790139",
    "200790139",
    "THIRD_PARTY",
]

LIGHTSOURCE_UPS_IMPORT_FIELDS = [
    "Contact Name",
    "Company or Name",
    "Country",
    "Address 1",
    "Address 2",
    "Address 3",
    "City",
    "State/Prov/Other",
    "Postal Code",
    "Telephone",
    "Ext",
    "Residential Ind",
    "Consignee Email",
    "Packaging Type",
    "Customs Value",
    "Weight",
    "Length",
    "Width",
    "Height",
    "Unit of Measure",
    "Description of Goods",
    "Documents of No Commercial Value",
    "GNIFC",
    "Pkg Decl Value",
    "Service",
    "Delivery Confirm",
    "Shipper Release",
    "Ret of Documents",
    "Saturday Deliver",
    "Carbon Neutral",
    "Large Package",
    "Addl handling",
    "Reference 1",
    "Reference 2",
    "Reference 3",
    "QV Notif 1-Addr",
    "QV Notif 1-Ship",
    "QV Notif 1-Excp",
    "QV Notif 1-Delv",
    "QV Notif 2-Addr",
    "QV Notif 2-Ship",
    "QV Notif 2-Excp",
    "QV Notif 2-Delv",
    "QV Notif 3-Addr",
    "QV Notif 3-Ship",
    "QV Notif 3-Excp",
    "QV Notif 3-Delv",
    "QV Notif 4-Addr",
    "QV Notif 4-Ship",
    "QV Notif 4-Excp",
    "QV Notif 4-Delv",
    "QV Notif 5-Addr",
    "QV Notif 5-Ship",
    "QV Notif 5-Excp",
    "QV Notif 5-Delv",
    "QV Notif Msg",
    "QV Failure Addr",
    "UPS Premium Care",
    "ADL Location ID",
    "ADL Media Type",
    "ADL Language",
    "ADL Notification Addr",
    "ADL Failure Addr",
    "ADL COD Value",
    "ADL Deliver to Addressee",
    "ADL Shipper Media Type",
    "ADL Shipper Language",
    "ADL Shipper Notification Addr",
    "ADL Direct Delivery Only",
    "Electronic Package Release Authentication",
    "Lithium Ion Alone",
    "Lithium Ion In Equipment",
    "Lithium Ion With_Equipment",
    "Lithium Metal Alone",
    "Lithium Metal In Equipment",
    "Lithium Metal With Equipment",
    "Weekend Commercial Delivery",
    "Dry Ice Weight",
    "Merchandise Description",
    "UPS Ground Saver Limited Quantity/Lithium Battery",
]

LIGHTSOURCE_UPS_DEFAULT_ROW = [""] * len(LIGHTSOURCE_UPS_IMPORT_FIELDS)
LIGHTSOURCE_UPS_DEFAULT_ROW[13] = "2"
LIGHTSOURCE_UPS_DEFAULT_ROW[24] = "03"

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


def dataframe_to_smart_rows(df: pd.DataFrame) -> tuple[list[dict[str, str]], dict[str, str]]:
    raw = df.dropna(how="all")
    if raw.empty:
        return [], {}

    raw = raw.fillna("")
    best_index = 0
    best_score = -1
    max_scan = min(len(raw), 25)
    alias_terms = [normalized(alias) for aliases in [*BULK_INBOUND_ALIASES.values(), LABEL_ALIASES["company_name"], LABEL_ALIASES["company_id"]] for alias in aliases]
    for position in range(max_scan):
        values = [cell_text(value) for value in raw.iloc[position].tolist()]
        score = 0
        for value in values:
            value_norm = normalized(value)
            if value_norm and any(alias == value_norm or alias in value_norm for alias in alias_terms):
                score += 1
        if score > best_score:
            best_score = score
            best_index = position

    if best_score > 0:
        headers = make_unique_headers([clean_header(value) for value in raw.iloc[best_index].tolist()])
        body = raw.iloc[best_index + 1 :].copy()
        body.columns = headers
    else:
        body = raw.copy()
        body.columns = make_unique_headers([clean_header(c) for c in body.columns])

    rows = dataframe_to_rows(body)
    columns = list(rows[0].keys()) if rows else list(body.columns)
    return rows, detect_bulk_inbound_columns(columns)


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


def detect_bulk_inbound_columns(columns: list[str]) -> dict[str, str]:
    by_norm = {normalized(column): column for column in columns}
    detected: dict[str, str] = {}
    for field, aliases in BULK_INBOUND_ALIASES.items():
        winner = ""
        for alias in aliases:
            alias_norm = normalized(alias)
            if alias_norm in by_norm:
                winner = by_norm[alias_norm]
                break
        if not winner:
            for column in columns:
                column_norm = normalized(column)
                if any(normalized(alias) and normalized(alias) in column_norm for alias in aliases):
                    winner = column
                    break
        detected[field] = winner
    return detected


def first_row_value(rows: list[dict[str, str]], aliases: list[str]) -> str:
    for row in rows:
        value = row_value(row, aliases)
        if value:
            return value
    return ""


def normalize_date_for_upload(value: str, fallback: str = "") -> str:
    text = cell_text(value)
    if not text:
        return fallback
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text
    return parsed.date().isoformat()


def clean_number_for_upload(value: str, default: str = "") -> str:
    text = cell_text(value).replace(",", "").strip()
    if not text:
        return default
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return text
    number = float(match.group(0))
    return str(int(number)) if number.is_integer() else str(number)


def load_product_variant_skus(file_id: str) -> set[str]:
    if not file_id:
        return set()
    rows = load_file_rows(file_id)
    skus: set[str] = set()
    for row in rows:
        sku = row_value(row, PRODUCT_VARIANT_SKU_ALIASES)
        if sku:
            skus.add(normalized(sku))
    return skus


def shipment_level_values(rows: list[dict[str, str]]) -> dict[str, str]:
    return {
        field: first_row_value(rows, aliases)
        for field, aliases in BULK_INBOUND_ALIASES.items()
        if field not in {"sku", "lot", "cases", "units_per_case", "notes"}
    }


def bulk_inbound_row_from_source(
    row: dict[str, str],
    mapping: dict[str, str],
    defaults: dict[str, str],
    product_skus: set[str],
) -> tuple[dict[str, str] | None, str]:
    today = date.today().isoformat()
    sku = value_from(row, mapping.get("sku", ""))
    cases = value_from(row, mapping.get("cases", ""))
    units_per_case = value_from(row, mapping.get("units_per_case", ""))
    lot = value_from(row, mapping.get("lot", ""))
    notes = value_from(row, mapping.get("notes", ""))

    if not sku and product_skus:
        for value in row.values():
            if normalized(value) in product_skus:
                sku = cell_text(value)
                break

    if not any([sku, cases, units_per_case, lot]):
        return None, ""

    shipment_number = value_from(row, mapping.get("shipment_number", "")) or defaults.get("shipment_number", "")
    date_sent = value_from(row, mapping.get("date_sent_out", "")) or defaults.get("date_sent_out", "")
    receiving_date = value_from(row, mapping.get("receiving_date", "")) or defaults.get("receiving_date", "")
    shipment_type = value_from(row, mapping.get("shipment_type", "")) or defaults.get("shipment_type", "")
    pallets = value_from(row, mapping.get("inbound_pallets", "")) or defaults.get("inbound_pallets", "")
    tracking = value_from(row, mapping.get("tracking", "")) or defaults.get("tracking", "")

    upload_row = {
        "Shipment # *": shipment_number,
        "Date Sent Out *": normalize_date_for_upload(date_sent, today),
        "Receiving Date *": normalize_date_for_upload(receiving_date, today),
        "Shipment Type": shipment_type,
        "Inbound Pallets": clean_number_for_upload(pallets),
        "Product Variant SKU *": sku,
        "Lot #": lot,
        "Cases *": clean_number_for_upload(cases, "1"),
        "Units per Case *": clean_number_for_upload(units_per_case, "1"),
        "Tracking Info": tracking,
        "Notes": notes,
    }

    missing = [field for field in ["Shipment # *", "Product Variant SKU *", "Cases *", "Units per Case *"] if not upload_row[field]]
    if product_skus and sku and normalized(sku) not in product_skus:
        missing.append("SKU not found in product variants")
    return upload_row, ", ".join(missing)


def write_bulk_inbound_upload(rows: list[dict[str, str]], prefix: str = "bulk_inbound_shipment_upload") -> Path:
    output_path = OUTPUT_DIR / f"{prefix}_{uuid.uuid4().hex[:8]}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLATFORM_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def write_bulk_inbound_report(report_rows_data: list[dict[str, str]]) -> Path:
    output_path = OUTPUT_DIR / f"bulk_inbound_review_{uuid.uuid4().hex[:8]}.csv"
    fieldnames = ["Source File", "Source Row", *PLATFORM_FIELDS, "Status"]
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows_data)
    return output_path


def load_product_variant_names(file_id: str) -> dict[str, str]:
    if not file_id:
        return {}
    rows = load_file_rows(file_id)
    names: dict[str, str] = {}
    for row in rows:
        sku = row_value(row, PRODUCT_VARIANT_SKU_ALIASES)
        name = row_value(row, ["Product Name*", "Product Name", "Variant Name*", "Variant Name", "Description", "Title"])
        if sku and name:
            names[normalized(sku)] = name
    return names


def positive_int(value: Any, default: int = 0) -> int:
    text = clean_number_for_upload(cell_text(value))
    if not text:
        return default
    try:
        parsed = int(float(text))
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def label_value(row: dict[str, str], field: str, mapping: dict[str, str] | None = None) -> str:
    if mapping and mapping.get(field):
        value = value_from(row, mapping[field])
        if value:
            return value
    return row_value(row, LABEL_ALIASES[field])


def code128_svg(value: str, height: int = 62) -> str:
    text = cell_text(value)[:80] or " "
    codes = [104]
    for char in text:
        ordinal = ord(char)
        codes.append((ordinal - 32) if 32 <= ordinal <= 126 else 0)
    checksum = codes[0]
    for index, code in enumerate(codes[1:], start=1):
        checksum += code * index
    codes.append(checksum % 103)
    codes.append(106)

    quiet_zone = 10
    module = 1
    x = quiet_zone
    rects = []
    for code in codes:
        pattern = CODE128_PATTERNS[code]
        for index, width_text in enumerate(pattern):
            width = int(width_text) * module
            if index % 2 == 0:
                rects.append(f'<rect x="{x}" y="0" width="{width}" height="{height}"/>')
            x += width
    svg_width = max(x + quiet_zone, 1)
    return (
        f'<svg class="barcode" viewBox="0 0 {svg_width} {height}" preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-label="Barcode {html.escape(text, quote=True)}">{"".join(rects)}</svg>'
    )


QR_L_DATA_CODEWORDS = {1: 19, 2: 34, 3: 55, 4: 80, 5: 108}
QR_L_ECC_CODEWORDS = {1: 7, 2: 10, 3: 15, 4: 20, 5: 26}
QR_TOTAL_CODEWORDS = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134}


def qr_gf_mul(x: int, y: int) -> int:
    result = 0
    while y:
        if y & 1:
            result ^= x
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
        y >>= 1
    return result


def qr_gf_pow(power: int) -> int:
    value = 1
    for _ in range(power):
        value = qr_gf_mul(value, 2)
    return value


def qr_generator_poly(degree: int) -> list[int]:
    result = [1]
    for i in range(degree):
        root = qr_gf_pow(i)
        result = [qr_gf_mul(coef, root) for coef in result] + [0]
        for j in range(len(result) - 1):
            result[j + 1] ^= result[j]
    return result


def qr_reed_solomon(data: list[int], degree: int) -> list[int]:
    generator = qr_generator_poly(degree)
    remainder = [0] * degree
    for byte in data:
        factor = byte ^ remainder.pop(0)
        remainder.append(0)
        for i, coef in enumerate(generator[1:]):
            remainder[i] ^= qr_gf_mul(coef, factor)
    return remainder


def qr_append_bits(bits: list[int], value: int, length: int) -> None:
    for i in range(length - 1, -1, -1):
        bits.append((value >> i) & 1)


def qr_data_codewords(text: str, version: int) -> list[int]:
    payload = text.encode("utf-8")[:QR_L_DATA_CODEWORDS[version] - 2]
    bits: list[int] = []
    qr_append_bits(bits, 0b0100, 4)
    qr_append_bits(bits, len(payload), 8)
    for byte in payload:
        qr_append_bits(bits, byte, 8)
    capacity_bits = QR_L_DATA_CODEWORDS[version] * 8
    qr_append_bits(bits, 0, min(4, capacity_bits - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    codewords = [
        int("".join(str(bit) for bit in bits[i : i + 8]), 2)
        for i in range(0, len(bits), 8)
    ]
    pad = 0xEC
    while len(codewords) < QR_L_DATA_CODEWORDS[version]:
        codewords.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC
    return codewords


def qr_draw_finder(matrix: list[list[int | None]], function: list[list[bool]], row: int, col: int) -> None:
    size = len(matrix)
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = row + r, col + c
            if not (0 <= rr < size and 0 <= cc < size):
                continue
            is_dark = 0 <= r <= 6 and 0 <= c <= 6 and (r in {0, 6} or c in {0, 6} or (2 <= r <= 4 and 2 <= c <= 4))
            matrix[rr][cc] = 1 if is_dark else 0
            function[rr][cc] = True


def qr_draw_alignment(matrix: list[list[int | None]], function: list[list[bool]], center: int) -> None:
    for r in range(-2, 3):
        for c in range(-2, 3):
            rr, cc = center + r, center + c
            is_dark = max(abs(r), abs(c)) in {0, 2}
            matrix[rr][cc] = 1 if is_dark else 0
            function[rr][cc] = True


def qr_format_bits(mask: int = 0) -> int:
    data = (0b01 << 3) | mask
    value = data << 10
    generator = 0x537
    for i in range(14, 9, -1):
        if (value >> i) & 1:
            value ^= generator << (i - 10)
    return ((data << 10) | value) ^ 0x5412


def qr_matrix(text: str) -> list[list[int]]:
    byte_len = len(text.encode("utf-8"))
    version = next((v for v, capacity in QR_L_DATA_CODEWORDS.items() if byte_len <= capacity - 2), 5)
    size = 21 + 4 * (version - 1)
    matrix: list[list[int | None]] = [[None for _ in range(size)] for _ in range(size)]
    function = [[False for _ in range(size)] for _ in range(size)]

    qr_draw_finder(matrix, function, 0, 0)
    qr_draw_finder(matrix, function, 0, size - 7)
    qr_draw_finder(matrix, function, size - 7, 0)

    for i in range(8, size - 8):
        bit = 1 if i % 2 == 0 else 0
        matrix[6][i] = bit
        matrix[i][6] = bit
        function[6][i] = True
        function[i][6] = True

    if version >= 2:
        qr_draw_alignment(matrix, function, size - 7)

    matrix[4 * version + 9][8] = 1
    function[4 * version + 9][8] = True

    data = qr_data_codewords(text, version)
    data.extend(qr_reed_solomon(data, QR_L_ECC_CODEWORDS[version]))
    bits = [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]
    bit_index = 0
    direction = -1
    row = size - 1
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        for _ in range(size):
            for offset in range(2):
                cc = col - offset
                if not function[row][cc]:
                    bit = bits[bit_index] if bit_index < len(bits) else 0
                    if (row + cc) % 2 == 0:
                        bit ^= 1
                    matrix[row][cc] = bit
                    bit_index += 1
            row += direction
            if row < 0 or row >= size:
                row -= direction
                direction *= -1
                break
        col -= 2

    fmt = qr_format_bits(0)
    for i in range(15):
        bit = (fmt >> i) & 1
        if i < 6:
            coords = [(8, i)]
        elif i == 6:
            coords = [(8, 7)]
        elif i == 7:
            coords = [(8, 8)]
        elif i == 8:
            coords = [(7, 8)]
        else:
            coords = [(14 - i, 8)]
        coords.append((size - 1 - i, 8) if i < 8 else (8, size - 15 + i))
        for rr, cc in coords:
            matrix[rr][cc] = bit
            function[rr][cc] = True

    return [[int(cell or 0) for cell in row_values] for row_values in matrix]


def qr_svg(value: str) -> str:
    text = cell_text(value) or " "
    matrix = qr_matrix(text)
    quiet = 4
    size = len(matrix)
    rects = []
    for r, row in enumerate(matrix):
        for c, bit in enumerate(row):
            if bit:
                rects.append(f'<rect x="{c + quiet}" y="{r + quiet}" width="1" height="1"/>')
    view = size + quiet * 2
    return (
        f'<svg class="qr-code" viewBox="0 0 {view} {view}" preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-label="QR {html.escape(text, quote=True)}">{"".join(rects)}</svg>'
    )


def label_item_from_row(row: dict[str, str], mapping: dict[str, str], product_names: dict[str, str]) -> dict[str, str] | None:
    sku = label_value(row, "sku", mapping).strip()
    if not sku:
        return None
    product_name = label_value(row, "product_name") or product_names.get(normalized(sku), "")
    quantity = label_value(row, "quantity")
    units_per_case = label_value(row, "units_per_case", mapping)
    qty = clean_number_for_upload(quantity) or clean_number_for_upload(units_per_case) or "1"
    return {
        "sku": sku,
        "product_name": product_name,
        "qty": qty,
        "lot": label_value(row, "lot", mapping),
    }


def build_inbound_label_groups(
    documents: list[UploadStorage],
    variant_upload: UploadStorage | None = None,
    allow_company_only: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    product_names: dict[str, str] = {}
    if variant_upload:
        product_file_id, _filename = save_upload(variant_upload)
        product_names = load_product_variant_names(product_file_id)

    groups: dict[str, dict[str, Any]] = {}
    auto_sequence = 0
    report: list[dict[str, str]] = []

    for document in documents:
        filename, rows, mapping = read_bulk_customer_document(document)
        defaults = shipment_level_values(rows)
        for row_index, row in enumerate(rows, start=1):
            item = label_item_from_row(row, mapping, product_names)
            source_row = row.get("_source_row", str(row_index))
            if not item and allow_company_only and (label_value(row, "company_name") or label_value(row, "company_id")):
                item = {"sku": "", "product_name": "", "qty": "", "lot": ""}
            if not item:
                report.append({"Source File": filename, "Source Row": source_row, "Carton": "", "SKU": "", "Qty": "", "Status": "Skipped: missing SKU"})
                continue

            shipment = label_value(row, "shipment_number", mapping) or defaults.get("shipment_number", "") or Path(filename).stem
            carton = label_value(row, "carton_number")
            tracking = label_value(row, "tracking", mapping) or defaults.get("tracking", "")
            po = label_value(row, "po") or shipment
            vendor = label_value(row, "vendor")
            company_name = label_value(row, "company_name") or vendor
            company_id = label_value(row, "company_id")
            cases = positive_int(label_value(row, "cases", mapping), 1)
            units_per_case = clean_number_for_upload(label_value(row, "units_per_case", mapping)) or item["qty"] or "1"

            if carton:
                key = f"{filename}|{shipment}|{carton}"
                group = groups.setdefault(
                    key,
                    {
                        "shipment": shipment,
                        "carton": carton,
                        "tracking": tracking,
                        "po": po,
                        "vendor": vendor,
                        "company_name": company_name,
                        "company_id": company_id,
                        "source_file": filename,
                        "items": [],
                    },
                )
                group["company_name"] = group.get("company_name") or company_name
                group["company_id"] = group.get("company_id") or company_id
                group["items"].append(item)
                report.append({"Source File": filename, "Source Row": source_row, "Carton": carton, "SKU": item["sku"], "Qty": item["qty"], "Status": "Grouped by carton number"})
            else:
                for case_index in range(1, max(cases, 1) + 1):
                    auto_sequence += 1
                    carton_id = f"AUTO-{auto_sequence:04d}"
                    group = {
                        "shipment": shipment,
                        "carton": carton_id,
                        "tracking": tracking,
                        "po": po,
                        "vendor": vendor,
                        "company_name": company_name,
                        "company_id": company_id,
                        "source_file": filename,
                        "items": [{**item, "qty": units_per_case}],
                    }
                    groups[f"{filename}|{shipment}|{carton_id}"] = group
                report.append({"Source File": filename, "Source Row": source_row, "Carton": f"{cases} auto label(s)", "SKU": item["sku"], "Qty": units_per_case, "Status": "Expanded from carton/case count"})

    labels = list(groups.values())
    labels.sort(key=lambda group: (cell_text(group.get("shipment")), natural_label_sort(cell_text(group.get("carton")))))
    shipment_totals: dict[str, int] = {}
    shipment_indexes: dict[str, int] = {}
    for group in labels:
        shipment_key = cell_text(group.get("shipment"))
        shipment_totals[shipment_key] = shipment_totals.get(shipment_key, 0) + 1

    total = len(labels)
    for index, group in enumerate(labels, start=1):
        shipment_key = cell_text(group.get("shipment"))
        shipment_indexes[shipment_key] = shipment_indexes.get(shipment_key, 0) + 1
        unique_skus = {normalized(item["sku"]) for item in group["items"] if normalized(item["sku"])}
        total_units = sum(positive_int(item.get("qty"), 1) for item in group["items"])
        group["label_index"] = index
        group["label_total"] = total
        group["b3_inbound"] = "B3 Inbound"
        group["carton_type"] = "Mixed SKU" if len(unique_skus) > 1 else "Single SKU"
        group["inbound_type"] = "A+" if total_units == 1 else "A" if len(unique_skus) <= 1 else "B" if len(unique_skus) <= 3 else "C"
        group["carton_sequence"] = f"{shipment_indexes[shipment_key]} of {shipment_totals[shipment_key]} cartons/pallets"
    return labels, report


def natural_label_sort(value: str) -> tuple[Any, ...]:
    parts = re.split(r"(\d+)", value)
    return tuple(int(part) if part.isdigit() else part.lower() for part in parts)


def render_inbound_labels_html(labels: list[dict[str, Any]]) -> str:
    label_pages = []
    for label in labels:
        items = label["items"]
        inbound_id = cell_text(label.get("shipment", ""))
        item_rows = "".join(
            "<tr>"
            f"<td>{html.escape(item.get('sku', ''))}</td>"
            f"<td>{html.escape(item.get('qty', ''))}</td>"
            f"<td class=\"long-text\">{html.escape(item.get('lot', '') or item.get('product_name', ''))}</td>"
            "</tr>"
            for item in items[:8]
        )
        extra_note = f'<div class="more">+ {len(items) - 8} more SKU line(s)</div>' if len(items) > 8 else ""
        unique_lots = []
        seen_lots = set()
        for item in items:
            lot = cell_text(item.get("lot", ""))
            if lot and lot not in seen_lots:
                unique_lots.append(lot)
                seen_lots.add(lot)
        lot_barcodes = "".join(
            f'<div class="lot-barcode">{code128_svg(lot, 34)}<span>{html.escape(lot)}</span></div>'
            for lot in unique_lots[:3]
        )
        lot_note = f'<div class="more">+ {len(unique_lots) - 3} more LOT ID(s) in review report</div>' if len(unique_lots) > 3 else ""
        label_pages.append(
            f"""
            <section class="label">
              <div class="top">
                <div>
                  <div class="eyebrow">Inbound Carton</div>
                  <h1>{html.escape(label.get("carton_type", ""))}</h1>
                </div>
                <div class="carton-count">Carton {html.escape(str(label.get("label_index", "")))} / {html.escape(str(label.get("label_total", "")))}</div>
              </div>
              <div class="meta">
                <div><span>Shipment</span><strong>{html.escape(label.get("shipment", ""))}</strong></div>
                <div><span>Carton</span><strong>{html.escape(label.get("carton", ""))}</strong></div>
                <div><span>PO / Ref</span><strong>{html.escape(label.get("po", ""))}</strong></div>
                <div><span>Tracking</span><strong>{html.escape(label.get("tracking", ""))}</strong></div>
              </div>
              <div class="scan-block">
                <span>Inbound ID</span>
                <strong>{html.escape(inbound_id)}</strong>
                {code128_svg(inbound_id, 52)}
              </div>
              <table>
                <thead><tr><th>SKU</th><th>Qty</th><th>LOT ID / Detail</th></tr></thead>
                <tbody>{item_rows}</tbody>
              </table>
              {extra_note}
              <div class="lot-scan-wrap">
                {lot_barcodes or '<div class="muted-scan">No LOT ID provided</div>'}
                {lot_note}
              </div>
              <div class="foot">
                <span>{html.escape(label.get("vendor", ""))}</span>
                <span>{html.escape(label.get("source_file", ""))}</span>
              </div>
            </section>
            """
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Inbound Carton Labels</title>
  <style>
    @page {{ size: 4in 6in; margin: 0; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #d8dee8; color: #111827; font-family: Arial, Helvetica, sans-serif; }}
    .label {{
      width: 4in;
      height: 6in;
      page-break-after: always;
      break-after: page;
      display: grid;
      grid-template-rows: auto auto auto 1fr auto auto;
      gap: .08in;
      padding: .18in;
      background: #fff;
      overflow: hidden;
    }}
    .top, .foot {{ display: flex; justify-content: space-between; gap: .08in; align-items: flex-start; }}
    .eyebrow, .meta span, .scan-block span {{ color: #4b5563; font-size: 8pt; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }}
    h1 {{ margin: .02in 0 0; font-size: 22pt; line-height: 1; }}
    .carton-count {{ border: 2px solid #111827; padding: .05in .08in; font-size: 11pt; font-weight: 800; white-space: nowrap; }}
    .meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: .06in; }}
    .meta div {{ min-width: 0; border: 1px solid #d1d5db; padding: .05in; }}
    .meta strong {{ display: block; min-height: .18in; overflow-wrap: anywhere; font-size: 10pt; line-height: 1.1; }}
    .scan-block {{ display: grid; gap: .035in; border-top: 3px solid #111827; border-bottom: 1px solid #111827; padding: .06in 0; }}
    .scan-block strong {{ display: block; font-size: 18pt; line-height: 1.05; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: .035in .025in; text-align: left; font-size: 8.5pt; line-height: 1.08; overflow: hidden; }}
    th {{ color: #4b5563; font-size: 7.5pt; text-transform: uppercase; }}
    th:nth-child(1), td:nth-child(1) {{ width: 42%; }}
    th:nth-child(2), td:nth-child(2) {{ width: 13%; text-align: right; }}
    th:nth-child(3), td:nth-child(3) {{ width: 45%; }}
    .long-text {{ overflow-wrap: anywhere; word-break: break-word; font-size: 7.8pt; }}
    .more {{ font-size: 8pt; font-weight: 700; }}
    .barcode {{ width: 100%; height: .42in; fill: #000; shape-rendering: crispEdges; }}
    .lot-scan-wrap {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .04in; text-align: center; font-size: 6.6pt; font-weight: 700; overflow: hidden; }}
    .lot-barcode {{ min-width: 0; display: grid; gap: .015in; }}
    .lot-barcode .barcode {{ height: .3in; }}
    .lot-barcode span {{ overflow-wrap: anywhere; word-break: break-word; line-height: 1.05; max-height: .22in; overflow: hidden; }}
    .lot-scan-wrap .more, .muted-scan {{ grid-column: 1 / -1; }}
    .muted-scan {{ color: #6b7280; font-size: 8pt; font-weight: 700; text-align: left; }}
    .foot {{ color: #4b5563; font-size: 7pt; min-height: .14in; }}
    @media screen {{
      body {{ padding: .25in; display: grid; gap: .2in; justify-content: center; }}
      .label {{ box-shadow: 0 14px 34px rgba(15, 23, 42, .2); page-break-after: auto; }}
    }}
    @media print {{
      body {{ background: #fff; }}
    }}
  </style>
</head>
<body>
  {"".join(label_pages)}
</body>
</html>"""


def write_inbound_label_report(report_rows_data: list[dict[str, str]]) -> Path:
    output_path = OUTPUT_DIR / f"inbound_label_review_{uuid.uuid4().hex[:8]}.csv"
    fieldnames = ["Source File", "Source Row", "Carton", "SKU", "Qty", "Status"]
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows_data)
    return output_path


DESIGNER_ALLOWED_FIELDS = {
    "b3_inbound": "B3 Inbound",
    "company_name": "Company Name",
    "company_id": "Company ID",
    "shipment": "Inbound ID",
    "carton": "Carton ID",
    "tracking": "Tracking",
    "po": "PO / Ref",
    "vendor": "Vendor",
    "carton_type": "Carton Type",
    "inbound_type": "Inbound Type",
    "carton_sequence": "Carton / Pallet Count",
    "sku": "SKU",
    "qty": "Qty",
    "lot": "LOT ID",
    "detail": "LOT ID / Detail",
    "product_name": "Product Name",
}


def label_field_value(label: dict[str, Any], item: dict[str, str], field: str) -> str:
    if field == "detail":
        return cell_text(item.get("lot") or item.get("product_name"))
    if field in item:
        return cell_text(item.get(field))
    if field in label:
        return cell_text(label.get(field))
    return ""


def designer_value(label: dict[str, Any], field: str, fallback: str = "") -> str:
    items = label.get("items") or []
    item = items[0] if items else {}
    value = label_field_value(label, item, field)
    if not value and fallback:
        value = label_field_value(label, item, fallback)
    return value


def render_designer_label_html(labels: list[dict[str, Any]], template: dict[str, Any]) -> str:
    elements = template.get("elements") if isinstance(template.get("elements"), list) else []
    if not elements:
        elements = default_label_template()["elements"]
    landscape = template.get("preset") == "blindReceive"
    page_width = 6.0 if landscape else 4.0
    page_height = 4.0 if landscape else 6.0
    pages = []
    for label in labels:
        items = label.get("items") or []
        rendered = []
        for element in elements:
            element_type = cell_text(element.get("type") or "text")
            field = cell_text(element.get("field") or "shipment")
            fallback = cell_text(element.get("fallback") or "")
            title = cell_text(element.get("title")) if "title" in element else DESIGNER_ALLOWED_FIELDS.get(field, field)
            x = max(0.0, min(page_width, float(element.get("x") or 0)))
            y = max(0.0, min(page_height, float(element.get("y") or 0)))
            w = max(0.15, min(page_width - x, float(element.get("w") or 1)))
            h = max(0.15, min(page_height - y, float(element.get("h") or 0.4)))
            size = max(6, min(34, int(float(element.get("size") or 10))))
            value = designer_value(label, field, fallback)
            style = f'left:{x}in;top:{y}in;width:{w}in;height:{h}in;font-size:{size}pt;'
            if element_type == "barcode":
                rendered.append(
                    f'<div class="designer-el barcode-el" style="{style}"><span>{html.escape(title)}</span>{code128_svg(value, 48)}<strong>{html.escape(value)}</strong></div>'
                )
            elif element_type == "table":
                rows = "".join(
                    "<tr>"
                    f"<td>{html.escape(cell_text(item.get('sku')))} x {html.escape(cell_text(item.get('qty') or '1'))}</td>"
                    "</tr>"
                    for item in items[:8]
                )
                rendered.append(
                    f'<div class="designer-el table-el" style="{style}"><table><thead><tr><th>SKU x Qty</th></tr></thead><tbody>{rows}</tbody></table></div>'
                )
            elif element_type == "qr":
                rendered.append(
                    f'<div class="designer-el qr-el" style="{style}"><span>{html.escape(title)}</span>{qr_svg(value)}<strong>{html.escape(value)}</strong></div>'
                )
            else:
                rendered.append(
                    f'<div class="designer-el text-el" style="{style}"><span>{html.escape(title)}</span><strong>{html.escape(value)}</strong></div>'
                )
        pages.append(f'<section class="designer-label">{"".join(rendered)}</section>')
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Custom Labels</title>
  <style>
    @page {{ size: {page_width:g}in {page_height:g}in; margin: 0; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #d8dee8; color: #111827; font-family: Arial, Helvetica, sans-serif; }}
    .designer-label {{ position: relative; width: {page_width:g}in; height: {page_height:g}in; page-break-after: always; break-after: page; background: #fff; overflow: hidden; }}
    .designer-el {{ position: absolute; overflow: hidden; padding: .035in; border: 1px solid transparent; }}
    .designer-el span {{ display: block; color: #4b5563; font-size: 7pt; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; line-height: 1.1; }}
    .designer-el strong {{ display: block; overflow-wrap: anywhere; line-height: 1.06; }}
    .text-el strong {{ margin-top: .02in; }}
    .barcode-el {{ display: grid; grid-template-rows: auto 1fr auto; gap: .015in; text-align: center; }}
    .barcode {{ width: 100%; height: 100%; fill: #000; shape-rendering: crispEdges; }}
    .barcode-el strong {{ font-size: 7pt; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .table-el {{ padding: 0; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: .03in; text-align: left; font-size: 7.5pt; line-height: 1.05; overflow-wrap: anywhere; }}
    th {{ color: #4b5563; font-size: 6.6pt; text-transform: uppercase; }}
    th:nth-child(1), td:nth-child(1) {{ width: 42%; }}
    th:nth-child(2), td:nth-child(2) {{ width: 13%; text-align: right; }}
    th:nth-child(3), td:nth-child(3) {{ width: 45%; }}
    .qr-el {{ display: grid; grid-template-rows: auto minmax(0, 1fr) auto; justify-items: center; gap: .02in; text-align: center; }}
    .qr-code {{ width: auto; max-width: 100%; height: 100%; max-height: 100%; aspect-ratio: 1; fill: #000; shape-rendering: crispEdges; }}
    @media screen {{
      body {{ padding: .25in; display: grid; gap: .2in; justify-content: center; }}
      .designer-label {{ box-shadow: 0 14px 34px rgba(15, 23, 42, .2); page-break-after: auto; }}
      .designer-el {{ border-color: #e5e7eb; }}
    }}
    @media print {{ body {{ background: #fff; }} }}
  </style>
</head>
<body>{"".join(pages)}</body>
</html>"""


def default_label_template() -> dict[str, Any]:
    return {
        "elements": [
            {"type": "text", "field": "carton_type", "title": "Label Type", "x": 0.18, "y": 0.15, "w": 2.0, "h": 0.32, "size": 18},
            {"type": "text", "field": "carton", "title": "Carton", "x": 2.55, "y": 0.16, "w": 1.25, "h": 0.3, "size": 12},
            {"type": "text", "field": "shipment", "title": "Inbound ID", "x": 0.18, "y": 0.62, "w": 3.64, "h": 0.34, "size": 16},
            {"type": "barcode", "field": "shipment", "title": "Scan Inbound ID", "x": 0.25, "y": 1.02, "w": 3.5, "h": 0.64, "size": 8},
            {"type": "table", "field": "sku", "title": "Items", "x": 0.18, "y": 1.82, "w": 3.64, "h": 2.1, "size": 8},
            {"type": "barcode", "field": "lot", "fallback": "detail", "title": "Scan LOT ID", "x": 0.25, "y": 4.18, "w": 3.5, "h": 0.64, "size": 8},
            {"type": "text", "field": "po", "title": "PO / Ref", "x": 0.18, "y": 5.15, "w": 1.75, "h": 0.32, "size": 9},
            {"type": "text", "field": "tracking", "title": "Tracking", "x": 2.0, "y": 5.15, "w": 1.82, "h": 0.32, "size": 9},
        ]
    }


def build_custom_labels_from_uploads(
    documents: list[UploadStorage],
    variant_upload: UploadStorage | None,
    template: dict[str, Any],
) -> dict[str, Any]:
    labels, report = build_inbound_label_groups(documents, variant_upload, allow_company_only=template.get("preset") == "blindReceive")
    if not labels:
        raise ValueError("No labels could be created. Blind Receive needs Company Name or Company ID; other labels need at least SKU plus carton/case quantity.")
    label_path = OUTPUT_DIR / f"custom_labels_{uuid.uuid4().hex[:8]}.html"
    label_path.write_text(render_designer_label_html(labels, template), encoding="utf-8")
    report_path = write_inbound_label_report(report)
    return {
        "download_url": f"/download/{label_path.name}",
        "report_url": f"/download/{report_path.name}",
        "label_count": len(labels),
        "preview": [
            {
                "Carton": label.get("carton", ""),
                "Type": label.get("carton_type", ""),
                "Inbound ID": label.get("shipment", ""),
                "Items": "; ".join(f"{item['sku']} x {item['qty']}" for item in label["items"][:4]),
            }
            for label in labels[:25]
        ],
    }


def build_inbound_labels_from_uploads(
    documents: list[UploadStorage],
    variant_upload: UploadStorage | None = None,
) -> dict[str, Any]:
    labels, report = build_inbound_label_groups(documents, variant_upload)
    if not labels:
        raise ValueError("No carton labels could be created. Upload an inbound document with at least SKU plus carton/case quantity.")
    label_path = OUTPUT_DIR / f"inbound_carton_labels_{uuid.uuid4().hex[:8]}.html"
    label_path.write_text(render_inbound_labels_html(labels), encoding="utf-8")
    report_path = write_inbound_label_report(report)
    preview = []
    for label in labels[:25]:
        preview.append(
            {
                "Carton": label.get("carton", ""),
                "Type": label.get("carton_type", ""),
                "Shipment": label.get("shipment", ""),
                "SKU Count": len({item["sku"] for item in label["items"]}),
                "Items": "; ".join(f"{item['sku']} x {item['qty']}" for item in label["items"][:4]),
            }
        )
    return {
        "download_url": f"/download/{label_path.name}",
        "report_url": f"/download/{report_path.name}",
        "label_count": len(labels),
        "mixed_count": sum(1 for label in labels if label.get("carton_type") == "Mixed SKU"),
        "single_count": sum(1 for label in labels if label.get("carton_type") == "Single SKU"),
        "preview": preview,
    }


def product_variant_upload_row(source: dict[str, str]) -> list[str]:
    def get(field: str) -> str:
        return row_value(source, PRODUCT_LISTING_ALIASES[field])

    product_name = get("product_name") or get("variant_name") or get("variant_sku")
    variant_name = get("variant_name") or product_name
    variant_sku = get("variant_sku") or get("fulfillment_sku")
    country = get("country")
    return [
        product_name,
        get("fulfillment_sku") or variant_sku,
        get("material"),
        get("customs_category"),
        country,
        variant_name,
        variant_sku,
        get("upc"),
        (get("active") or "Y").upper()[:1],
        (get("packaging") or "N").upper()[:1],
        (get("sync_inventory") or "N").upper()[:1],
        clean_number_for_upload(get("weight"), "0.00"),
        clean_number_for_upload(get("length"), "0.00"),
        clean_number_for_upload(get("width"), "0.00"),
        clean_number_for_upload(get("height"), "0.00"),
        digits_only(get("hs_code")),
        country,
        get("warehouse_code"),
        get("warehouse_location"),
        clean_number_for_upload(get("warehouse_qty"), "0"),
        get("lot"),
        get("vendor"),
        normalize_date_for_upload(get("received_date")),
        normalize_date_for_upload(get("production_date")),
    ]


def write_product_variants_upload(rows: list[list[str]]) -> Path:
    output_path = OUTPUT_DIR / f"product_variants_upload_{uuid.uuid4().hex[:8]}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(PRODUCT_VARIANT_FIELDS)
        writer.writerows(rows)
    return output_path


def product_variant_report_rows(source_rows: list[dict[str, str]], upload_rows: list[list[str]]) -> list[dict[str, str]]:
    report = []
    for index, upload_row in enumerate(upload_rows, start=1):
        missing = []
        if not upload_row[0]:
            missing.append("Product Name*")
        if not upload_row[5]:
            missing.append("Variant Name*")
        if not upload_row[6]:
            missing.append("Variant SKU*")
        if not upload_row[17]:
            missing.append("Warehouse Code*")
        report.append(
            {
                "Source Row": str(index),
                "Product Name": upload_row[0],
                "Variant SKU": upload_row[6],
                "UPC": upload_row[7],
                "Warehouse Code": upload_row[17],
                "Warehouse Qty": upload_row[19],
                "Status": "Missing " + ", ".join(missing) if missing else "Ready",
            }
        )
    return report


def write_product_variant_report(rows: list[dict[str, str]]) -> Path:
    output_path = OUTPUT_DIR / f"product_variants_review_{uuid.uuid4().hex[:8]}.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Source Row", "Product Name", "Variant SKU", "UPC", "Warehouse Code", "Warehouse Qty", "Status"])
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def build_product_variants_from_upload(upload: UploadStorage) -> dict[str, Any]:
    file_id, _filename = save_upload(upload)
    source_rows = load_file_rows(file_id)
    upload_rows = [product_variant_upload_row(row) for row in source_rows if any(row.values())]
    upload_rows = [row for row in upload_rows if row[0] or row[6] or row[7]]
    if not upload_rows:
        raise ValueError("No product listing rows could be found in that file.")
    report = product_variant_report_rows(source_rows, upload_rows)
    output_path = write_product_variants_upload(upload_rows)
    report_path = write_product_variant_report(report)
    return {
        "download_url": f"/download/{output_path.name}",
        "report_url": f"/download/{report_path.name}",
        "row_count": len(upload_rows),
        "review_count": len([row for row in report if row["Status"] != "Ready"]),
        "preview": [dict(zip(PRODUCT_VARIANT_FIELDS, row)) for row in upload_rows[:50]],
        "report_preview": report[:100],
    }


def save_upload_to_disk(storage) -> Path:
    file_id = uuid.uuid4().hex
    safe_name = Path(storage.filename or f"upload-{file_id}").name
    suffix = Path(safe_name).suffix.lower()
    saved_path = UPLOAD_DIR / f"{file_id}{suffix or '.xlsx'}"
    storage.save(saved_path)
    return saved_path


def read_smart_spreadsheet(path: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    suffix = path.suffix.lower()
    all_rows: list[dict[str, str]] = []
    combined_mapping: dict[str, str] = {field: "" for field in BULK_INBOUND_FIELD_LABELS}

    if suffix == ".csv":
        frames = {"CSV": pd.read_csv(path, dtype=object, header=None)}
    elif suffix in {".xlsx", ".xlsm", ".xls"}:
        frames = pd.read_excel(path, sheet_name=None, dtype=object, header=None)
    else:
        raise ValueError(f"{path.name} is not a supported spreadsheet type.")

    for sheet_name, frame in frames.items():
        rows, mapping = dataframe_to_smart_rows(frame)
        for field, column in mapping.items():
            if column and not combined_mapping.get(field):
                combined_mapping[field] = column
        for index, row in enumerate(rows, start=1):
            if any(row.values()):
                row["_source_sheet"] = sheet_name
                row["_source_row"] = str(index)
                all_rows.append(row)
    return all_rows, combined_mapping


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF reading requires the pypdf package. Rebuild or install requirements.txt, then try again.") from exc

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def regex_label_value(text: str, aliases: list[str]) -> str:
    for alias in aliases:
        escaped = re.escape(alias).replace("\\ ", r"\s*")
        match = re.search(rf"\b{escaped}\b\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9 ./#_-]{{0,40}})", text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            value = re.split(r"\s{2,}|\n", value)[0].strip()
            return value
    return ""


def pdf_defaults(text: str) -> dict[str, str]:
    defaults = {}
    for field in ["shipment_number", "date_sent_out", "receiving_date", "shipment_type", "inbound_pallets", "tracking"]:
        defaults[field] = regex_label_value(text, BULK_INBOUND_ALIASES[field])
    return defaults


def likely_sku_token(value: str) -> bool:
    token = cell_text(value).strip(" :,;")
    if len(token) < 3:
        return False
    if token.lower() in {"sku", "item", "qty", "case", "cases", "carton", "cartons", "units", "pallet", "pallets"}:
        return False
    return bool(re.search(r"[A-Za-z]", token) and re.search(r"[A-Za-z0-9]", token))


def pdf_line_to_row(line: str, defaults: dict[str, str]) -> dict[str, str] | None:
    clean = re.sub(r"\s+", " ", line).strip()
    if not clean or not any(word in normalized(clean) for word in PDF_TABLE_HEADER_WORDS):
        return None
    pieces = [piece.strip(" :,;") for piece in re.split(r"\s{2,}|\t+| \| ", line) if piece.strip()]
    if len(pieces) <= 1:
        pieces = [piece.strip(" :,;") for piece in clean.split(" ") if piece.strip()]

    sku = ""
    sku_index = -1
    for index, piece in enumerate(pieces):
        if likely_sku_token(piece) and not numeric_quantity(piece):
            sku = piece
            sku_index = index
            break
    if not sku:
        return None

    numbers = [clean_number_for_upload(piece) for piece in pieces[sku_index + 1 :] if clean_number_for_upload(piece)]
    lot = ""
    for piece in pieces:
        if "lot" in normalized(piece):
            lot = re.sub(r"(?i)\blot\b\s*[:#-]?\s*", "", piece).strip()
            break

    row = {
        "shipment_number": defaults.get("shipment_number", ""),
        "date_sent_out": defaults.get("date_sent_out", ""),
        "receiving_date": defaults.get("receiving_date", ""),
        "shipment_type": defaults.get("shipment_type", ""),
        "inbound_pallets": defaults.get("inbound_pallets", ""),
        "sku": sku,
        "lot": lot,
        "cases": numbers[0] if numbers else "",
        "units_per_case": numbers[1] if len(numbers) > 1 else "",
        "tracking": defaults.get("tracking", ""),
        "notes": clean[:180],
        "_source_sheet": "PDF",
        "_source_row": "",
    }
    return row


def read_smart_pdf(path: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    text = extract_pdf_text(path)
    defaults = pdf_defaults(text)
    rows: list[dict[str, str]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        row = pdf_line_to_row(line, defaults)
        if row:
            row["_source_row"] = str(index)
            rows.append(row)
    mapping = {field: field for field in BULK_INBOUND_FIELD_LABELS}
    return rows, mapping


def read_bulk_customer_document(storage) -> tuple[str, list[dict[str, str]], dict[str, str]]:
    path = save_upload_to_disk(storage)
    suffix = path.suffix.lower()
    filename = Path(storage.filename or path.name).name
    if suffix == ".pdf":
        rows, mapping = read_smart_pdf(path)
    else:
        rows, mapping = read_smart_spreadsheet(path)
    return filename, rows, mapping


def build_bulk_inbound_from_uploads(
    document_uploads: list[UploadStorage],
    variant_upload: UploadStorage | None = None,
) -> dict[str, Any]:
    product_file_id = ""
    product_skus: set[str] = set()
    if variant_upload:
        product_file_id, _filename = save_upload(variant_upload)
        product_skus = load_product_variant_skus(product_file_id)

    upload_rows: list[dict[str, str]] = []
    report: list[dict[str, str]] = []
    sources: list[dict[str, Any]] = []

    for document in document_uploads:
        filename, rows, mapping = read_bulk_customer_document(document)
        defaults = shipment_level_values(rows)
        sources.append(
            {
                "filename": filename,
                "row_count": len(rows),
                "detected": {BULK_INBOUND_FIELD_LABELS[field]: column for field, column in mapping.items() if column},
            }
        )
        for row_index, row in enumerate(rows, start=1):
            upload_row, issue = bulk_inbound_row_from_source(row, mapping, defaults, product_skus)
            if not upload_row:
                continue
            status = "Ready" if not issue else f"Review: {issue}"
            report.append(
                {
                    "Source File": filename,
                    "Source Row": row.get("_source_row", str(row_index)),
                    **upload_row,
                    "Status": status,
                }
            )
            if not issue or issue == "SKU not found in product variants":
                upload_rows.append(upload_row)

    if not report:
        raise ValueError("No inbound shipment rows could be found. Try a spreadsheet with SKU/cases columns, or a PDF with item rows.")

    upload_path = write_bulk_inbound_upload(upload_rows)
    report_path = write_bulk_inbound_report(report)
    return {
        "download_url": f"/download/{upload_path.name}",
        "report_url": f"/download/{report_path.name}",
        "row_count": len(upload_rows),
        "review_count": len([row for row in report if row["Status"] != "Ready"]),
        "preview": upload_rows[:50],
        "report_preview": report[:100],
        "sources": sources,
        "product_sku_count": len(product_skus),
    }


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

    ignored = {"ORDER", "ITEM", "ITEMS", "RETURN", "THANKS", "HAVN", "TEAM"}

    def parse_item_lines(value: str) -> list[dict[str, str]]:
        parsed: list[dict[str, str]] = []
        for raw_line in value.splitlines():
            line = cell_text(raw_line)
            if not line:
                continue
            match = re.search(r"\b(?P<sku>[A-Z0-9][A-Z0-9-]{2,})\b", line, re.IGNORECASE)
            if not match:
                continue
            sku = match.group("sku").upper()
            if sku in ignored or sku.isdigit():
                continue
            qty_text = "1"
            tail = line[match.end():]
            qty_match = (
                re.search(r"(?:^|[\s:-])(?:x|\*|qty\.?|quantity)\s*(\d+)\b", tail, re.IGNORECASE)
                or re.search(r"(?:^|[\s:-])(\d+)\s*(?:x|qty\.?|quantity)\b", tail, re.IGNORECASE)
            )
            if qty_match:
                qty_text = qty_match.group(1)
            parsed.append({"sku": sku, "qty": choose_quantity("", qty_text)})
        return parsed

    items = parse_item_lines(sku_block)

    if not items:
        for sku in re.findall(r"\b[A-Z]{2,}[A-Z0-9-]{3,}\b", normalized_text):
            sku = sku.upper()
            if sku not in ignored and not sku.isdigit():
                items.append({"sku": sku, "qty": "1"})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item["sku"], item["qty"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return {"order_number": order, "skus": [item["sku"] for item in deduped], "items": deduped, "raw": text}


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
    sku_key = cell_text(sku).upper()
    if sku_key in SKU_PACKAGE_DEFAULTS:
        package_type, length, width, height = SKU_PACKAGE_DEFAULTS[sku_key]
        return {"Package Type": package_type, "Package Length": length, "Package Width": width, "Package Height": height}

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
def extract_lightsource_field(text: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}\s*:\s*(.+?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    return cell_text(match.group(1)) if match else ""


def parse_lightsource_email(text: str) -> dict[str, Any]:
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    order = extract_lightsource_field(normalized_text, "Print Order #")
    if not order:
        order_match = re.search(r"^Print\s+Order\s+#\s*([A-Za-z0-9-]+)\s*$", normalized_text, re.IGNORECASE | re.MULTILINE)
        order = order_match.group(1).strip() if order_match else ""
    order = order or extract_lightsource_field(normalized_text, "Order Number")
    brand = extract_lightsource_field(normalized_text, "Brand")
    company_name = extract_lightsource_field(normalized_text, "Company")
    recipient = extract_lightsource_field(normalized_text, "Recipient")
    address = extract_lightsource_field(normalized_text, "Address")
    city = extract_lightsource_field(normalized_text, "City")
    state = extract_lightsource_field(normalized_text, "State/Province")
    postal_code = extract_lightsource_field(normalized_text, "Postal Code")
    country = extract_lightsource_field(normalized_text, "Country") or "US"
    email = extract_lightsource_field(normalized_text, "Purchaser Email")
    phone = digits_only(extract_lightsource_field(normalized_text, "Purchaser Phone"))

    address_line_2 = ""
    address_match = re.search(r"^Address\s*:\s*(.+?)\s*$", normalized_text, re.IGNORECASE | re.MULTILINE)
    if address_match:
        lines_after_address = normalized_text[address_match.end():].splitlines()
        extra_lines: list[str] = []
        for line in lines_after_address:
            stripped = line.strip()
            if not stripped:
                continue
            if re.match(r"^(City|State/Province|Postal Code|Country|Purchaser Email|Purchaser Phone)\s*:", stripped, re.IGNORECASE):
                break
            extra_lines.append(stripped)
        address_line_2 = " ".join(extra_lines)

    items: list[dict[str, str]] = []
    item_matches = list(re.finditer(r"^---\s*ITEM\s+\d+\s*---\s*$", normalized_text, re.IGNORECASE | re.MULTILINE))
    for index, match in enumerate(item_matches):
        start = match.end()
        end = item_matches[index + 1].start() if index + 1 < len(item_matches) else len(normalized_text)
        block = normalized_text[start:end]
        sku = extract_lightsource_field(block, "SKU")
        if not sku:
            continue
        items.append(
            {
                "sku": sku,
                "product_name": extract_lightsource_field(block, "Product Name"),
                "qty": choose_quantity("", extract_lightsource_field(block, "Quantity") or "1"),
            }
        )

    first_name, last_name = split_name(recipient)
    return {
        "order_number": order,
        "brand": brand,
        "company": company_name,
        "recipient": recipient,
        "first_name": first_name,
        "last_name": last_name,
        "address_line_1": address,
        "address_line_2": address_line_2,
        "city": city,
        "state": state,
        "postal_code": postal_code,
        "country": country,
        "email": email,
        "phone": phone,
        "items": items,
        "raw": text,
    }


def lightsource_order_rows(requests: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for request_item in requests:
        order = cell_text(request_item.get("order_number", ""))
        company = cell_text(request_item.get("company", "")) or cell_text(request_item.get("brand", "")) or "Acorn"
        notes = cell_text(request_item.get("brand", ""))
        recipient = cell_text(request_item.get("recipient", ""))
        first_name = cell_text(request_item.get("first_name", ""))
        last_name = cell_text(request_item.get("last_name", ""))
        if recipient and (not first_name or not last_name):
            first_name, last_name = split_name(recipient)
        for item in request_item.get("items", []):
            rows.append(
                {
                    "Order Number": order,
                    "Order Date": "",
                    "Requested Service": "",
                    "Item SKU": cell_text(item.get("sku", "")),
                    "Item Unit Price": "",
                    "Item Quantity": choose_quantity("", cell_text(item.get("qty", "1")) or "1"),
                    "HS Code": "",
                    "Country Of Origin": "",
                    "Company Name": company,
                    "First Name": first_name,
                    "Last Name": last_name,
                    "Address Line 1": cell_text(request_item.get("address_line_1", "")),
                    "Address Line 2": cell_text(request_item.get("address_line_2", "")),
                    "City": cell_text(request_item.get("city", "")),
                    "State/Province": cell_text(request_item.get("state", "")),
                    "Zip/Postal Code": cell_text(request_item.get("postal_code", "")),
                    "Country": cell_text(request_item.get("country", "")) or "US",
                    "Email": cell_text(request_item.get("email", "")),
                    "Phone": digits_only(cell_text(request_item.get("phone", ""))),
                    "Notes": notes,
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
    return rows


def write_lightsource_order_import(requests: list[dict[str, Any]]) -> Path:
    output_path = OUTPUT_DIR / f"Lightsource_SB_Import_{uuid.uuid4().hex[:8]}.csv"
    rows = lightsource_order_rows(requests)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=LIGHTSOURCE_SB_IMPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def lightsource_fedex_rows(requests: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for request_item in requests:
        order = cell_text(request_item.get("order_number", ""))
        company = cell_text(request_item.get("company", "")) or cell_text(request_item.get("brand", "")) or "Acorn"
        recipient = cell_text(request_item.get("recipient", ""))
        row = LIGHTSOURCE_FEDEX_DEFAULT_ROW.copy()
        row[0] = order
        row[12] = company
        row[13] = recipient
        row[14] = cell_text(request_item.get("address_line_1", ""))
        row[15] = cell_text(request_item.get("address_line_2", ""))
        row[16] = cell_text(request_item.get("city", ""))
        row[17] = cell_text(request_item.get("state", ""))
        row[18] = cell_text(request_item.get("postal_code", ""))
        row[19] = cell_text(request_item.get("country", "")) or "US"
        row[20] = cell_text(request_item.get("email", ""))
        row[21] = digits_only(cell_text(request_item.get("phone", "")))
        row[22] = "1"
        row[23] = ""
        row[25] = ""
        row[26] = ""
        row[27] = ""
        rows.append(row)
    return rows


def lightsource_ups_rows(requests: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for request_item in requests:
        order = cell_text(request_item.get("order_number", ""))
        brand = cell_text(request_item.get("brand", ""))
        company = cell_text(request_item.get("company", ""))
        recipient = cell_text(request_item.get("recipient", ""))
        contact_name = recipient if company and recipient else ""
        company_or_name = company or recipient or brand or "Lightsource"
        row = LIGHTSOURCE_UPS_DEFAULT_ROW.copy()
        row[0] = contact_name
        row[1] = company_or_name
        row[2] = cell_text(request_item.get("country", "")) or "US"
        row[3] = cell_text(request_item.get("address_line_1", ""))
        row[4] = cell_text(request_item.get("address_line_2", ""))
        row[6] = cell_text(request_item.get("city", ""))
        row[7] = cell_text(request_item.get("state", ""))
        row[8] = cell_text(request_item.get("postal_code", ""))
        row[9] = digits_only(cell_text(request_item.get("phone", "")))
        row[12] = cell_text(request_item.get("email", ""))
        row[13] = "2"
        row[24] = "03"
        row[32] = order
        rows.append(row)
    return rows


def lightsource_carrier_preview_rows(fields: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    preview: list[dict[str, str]] = []
    for row in rows:
        preview.append(dict(zip(fields, row)))
    return preview


def write_lightsource_carrier_import(requests: list[dict[str, Any]], carrier: str) -> Path:
    carrier_label = "UPS" if carrier.upper() == "UPS" else "FedEx"
    output_path = OUTPUT_DIR / f"Lightsource_{carrier_label}_Import_{uuid.uuid4().hex[:8]}.csv"
    fields = LIGHTSOURCE_UPS_IMPORT_FIELDS if carrier_label == "UPS" else LIGHTSOURCE_FEDEX_IMPORT_FIELDS
    rows = lightsource_ups_rows(requests) if carrier_label == "UPS" else lightsource_fedex_rows(requests)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)
    return output_path


def lightsource_report_rows(requests: list[dict[str, Any]]) -> list[dict[str, str]]:
    report: list[dict[str, str]] = []
    for row in lightsource_order_rows(requests):
        missing = []
        for field in ["Order Number", "Item SKU", "Item Quantity", "First Name", "Last Name", "Address Line 1", "City", "State/Province", "Zip/Postal Code", "Country", "Email", "Phone"]:
            if not row.get(field):
                missing.append(field)
        report.append(
            {
                "Order Number": row.get("Order Number", ""),
                "Name": f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip(),
                "SKU": row.get("Item SKU", ""),
                "Qty": row.get("Item Quantity", ""),
                "Address": ", ".join([part for part in [row.get("Address Line 1", ""), row.get("Address Line 2", ""), row.get("City", ""), row.get("State/Province", ""), row.get("Zip/Postal Code", "")] if part]),
                "Status": "Missing " + ", ".join(missing) if missing else "Ready",
            }
        )
    return report

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


def outbound_order_number(source: dict[str, str]) -> str:
    by_norm = {normalized(key): key for key in source.keys() if "external" not in normalized(key)}
    order = ""
    for candidate in OUTBOUND_ORDER_ALIASES:
        key = by_norm.get(normalized(candidate))
        if key:
            order = value_from(source, key)
            break
    if not order:
        for key in source.keys():
            key_norm = normalized(key)
            if "external" in key_norm:
                continue
            for candidate in OUTBOUND_ORDER_ALIASES:
                candidate_norm = normalized(candidate)
                if len(candidate_norm) > 5 and candidate_norm in key_norm:
                    order = value_from(source, key)
                    break
            if order:
                break
    if order:
        return normalize_order_number(order)

    external_order = row_value(source, ["External Order ID", "External Order", "External ID"])
    for key, value in source.items():
        text = cell_text(value)
        digits = digits_only(text)
        if not digits or text == external_order:
            continue
        if re.fullmatch(r"0?617022\d{9,}", digits):
            return normalize_order_number(digits)
    return ""


def outbound_order_rows(file_id: str) -> list[dict[str, str]]:
    source_rows = read_csv_dicts(file_id)
    output: list[dict[str, str]] = []
    for source in source_rows:
        order = outbound_order_number(source)
        full_name = title_case_name(row_value(source, ["Full Name", "Name", "Customer"]))
        skus = split_skus(row_value(source, OUTBOUND_SKU_ALIASES))
        if not skus:
            skus = [""]
        for sku in skus:
            cases = choose_quantity("", row_value(source, ["Cases *", "Cases"]) or "1")
            units = choose_quantity("", row_value(source, ["Units per Case *", "Units per Case"]))
            if units:
                qty = str(max(1, int(cases or "1") * int(units)))
            else:
                qty = choose_quantity("", row_value(source, OUTBOUND_QTY_ALIASES) or "1")
            package = package_for_sku(sku, qty)
            output.append(
                {
                    "Order Number": f"{order} RET" if order and not order.endswith(" RET") else order,
                    "Order Date": "",
                    "Requested Service": "",
                    "Item SKU": sku,
                    "Item Unit Price": "",
                    "Item Quantity": qty,
                    "HS Code": "",
                    "Country Of Origin": "",
                    **HAVN_DESTINATION_FIELDS,
                    "Notes": "",
                    "Signature Required": "",
                    "Package SKU": "",
                    "Package Type": package["Package Type"],
                    "Package Length": package["Package Length"],
                    "Package Width": package["Package Width"],
                    "Package Height": package["Package Height"],
                    "Declared Value": "",
                    "Package #": "",
                    "Origin Address Line 1": row_value(source, ["Address Line 1"]),
                    "Origin Address Line 2": row_value(source, ["Address Line 2"]),
                    "Origin City": row_value(source, ["City"]),
                    "Origin State/Province": row_value(source, ["State", "State/Province"]),
                    "Origin Zip/Postal Code": row_value(source, ["Zipcode", "Zip/Postal Code", "Zip"]),
                    "Origin Country": row_value(source, ["Country Code", "Country"]) or "US",
                    **HAVN_ORIGIN_DEFAULTS,
                    "Origin Contact Name": full_name,
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
        for field in ["Order Number", "First Name", "Last Name", "Address Line 1", "City", "State/Province", "Zip/Postal Code", "Country", "Item SKU", "Package Type", "Package Length", "Package Width", "Package Height", "Origin Address Line 1", "Origin City", "Origin State/Province", "Origin Zip/Postal Code", "Origin Country"]:
            if not row.get(field):
                missing.append(field)
        report.append(
            {
                "Order Number": row.get("Order Number", ""),
                "Name": row.get("Origin Contact Name", ""),
                "SKU": row.get("Item SKU", ""),
                "Address": ", ".join([part for part in [row.get("Origin Address Line 1", ""), row.get("Origin Address Line 2", ""), row.get("Origin City", ""), row.get("Origin State/Province", ""), row.get("Origin Zip/Postal Code", "")] if part]),
                "Package": " ".join([row.get("Package Type", ""), "x".join([row.get("Package Length", ""), row.get("Package Width", ""), row.get("Package Height", "")])]).strip(),
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
        if self.path == "/template/inbound-labels.csv":
            self.download_inbound_labels_template()
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

    def download_inbound_labels_template(self) -> None:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Shipment #",
            "Carton #",
            "SKU",
            "Product Name",
            "Qty",
            "Cases",
            "Units per Case",
            "Lot ID",
            "Tracking Info",
            "PO Number",
            "Vendor",
            "Company Name",
            "Company ID",
        ])
        writer.writerow(["INB-1001", "C001", "SKU-RED-S", "Red Shirt Small", "6", "1", "6", "2026060512345678901234567890", "1Z999999999", "PO-12345", "Sample Brand", "Sample Company", "WINIT-12345"])
        writer.writerow(["INB-1001", "C001", "SKU-BLUE-M", "Blue Shirt Medium", "4", "1", "4", "LOT-B", "1Z999999999", "PO-12345", "Sample Brand", "Sample Company", "WINIT-12345"])
        writer.writerow(["INB-1001", "", "SKU-GREEN-L", "Green Shirt Large", "", "2", "12", "", "1Z999999999", "PO-12345", "Sample Brand", "Sample Company", "WINIT-12345"])
        data = output.getvalue().encode("utf-8-sig")
        self.send_bytes(
            data,
            "text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="inbound-carton-label-template.csv"'},
        )

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
        if self.path == "/api/bulk-inbound/generate":
            self.handle_bulk_inbound_generate()
            return
        if self.path == "/api/inbound-labels/generate":
            self.handle_inbound_labels_generate()
            return
        if self.path == "/api/label-designer/generate":
            self.handle_label_designer_generate()
            return
        if self.path == "/api/product-variants/generate":
            self.handle_product_variants_generate()
            return
        if self.path == "/api/lightsource/parse":
            self.handle_lightsource_parse()
            return
        if self.path == "/api/lightsource/export":
            self.handle_lightsource_export()
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

    def handle_bulk_inbound_generate(self) -> None:
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
            document_fields = form["documents"] if "documents" in form else []
            if not isinstance(document_fields, list):
                document_fields = [document_fields]
            documents = [
                UploadStorage(field.filename or "document", field.file)
                for field in document_fields
                if getattr(field, "filename", None)
            ]
            variant_field = form["product_variants"] if "product_variants" in form else None
            variant_upload = None
            if variant_field is not None and getattr(variant_field, "filename", None):
                variant_upload = UploadStorage(variant_field.filename, variant_field.file)
            if not documents:
                self.send_json({"error": "Upload at least one customer document first."}, HTTPStatus.BAD_REQUEST)
                return
            result = build_bulk_inbound_from_uploads(documents, variant_upload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(result)

    def handle_inbound_labels_generate(self) -> None:
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
            document_fields = form["documents"] if "documents" in form else []
            if not isinstance(document_fields, list):
                document_fields = [document_fields]
            documents = [
                UploadStorage(field.filename or "document", field.file)
                for field in document_fields
                if getattr(field, "filename", None)
            ]
            variant_field = form["product_variants"] if "product_variants" in form else None
            variant_upload = None
            if variant_field is not None and getattr(variant_field, "filename", None):
                variant_upload = UploadStorage(variant_field.filename, variant_field.file)
            if not documents:
                self.send_json({"error": "Upload at least one inbound document first."}, HTTPStatus.BAD_REQUEST)
                return
            result = build_inbound_labels_from_uploads(documents, variant_upload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(result)

    def handle_label_designer_generate(self) -> None:
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
            document_fields = form["documents"] if "documents" in form else []
            if not isinstance(document_fields, list):
                document_fields = [document_fields]
            documents = [
                UploadStorage(field.filename or "document", field.file)
                for field in document_fields
                if getattr(field, "filename", None)
            ]
            variant_field = form["product_variants"] if "product_variants" in form else None
            variant_upload = None
            if variant_field is not None and getattr(variant_field, "filename", None):
                variant_upload = UploadStorage(variant_field.filename, variant_field.file)
            template_text = form.getvalue("template") if "template" in form else "{}"
            template = json.loads(template_text or "{}")
            if not isinstance(template, dict):
                template = {}
            if not documents:
                self.send_json({"error": "Upload at least one label source document first."}, HTTPStatus.BAD_REQUEST)
                return
            result = build_custom_labels_from_uploads(documents, variant_upload, template)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(result)

    def handle_product_variants_generate(self) -> None:
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
                self.send_json({"error": "Upload a customer product listing CSV or Excel file first."}, HTTPStatus.BAD_REQUEST)
                return
            result = build_product_variants_from_upload(UploadStorage(field.filename, field.file))
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(result)

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

    def handle_lightsource_parse(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            parsed = parse_lightsource_email(payload.get("text", ""))
            if not parsed["order_number"] or not parsed["items"]:
                self.send_json(
                    {
                        "error": "Could not find both a print order number and at least one item SKU in that pasted email.",
                        "parsed": parsed,
                    },
                    HTTPStatus.BAD_REQUEST,
                )
                return
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(parsed)

    def handle_lightsource_export(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            requests = payload.get("requests", [])
            carrier = cell_text(payload.get("carrier", "")).lower()
            if not requests:
                self.send_json({"error": "Add at least one Lightsource order email first."}, HTTPStatus.BAD_REQUEST)
                return
            if carrier not in {"", "none", "fedex", "ups"}:
                self.send_json({"error": "Choose FedEx, UPS, or no carrier import."}, HTTPStatus.BAD_REQUEST)
                return
            output_path = write_lightsource_order_import(requests)
            rows = lightsource_order_rows(requests)
            carrier_path = None
            carrier_rows: list[list[str]] = []
            carrier_fields: list[str] = []
            carrier_label = ""
            if carrier == "fedex":
                carrier_label = "FedEx"
                carrier_path = write_lightsource_carrier_import(requests, carrier_label)
                carrier_rows = lightsource_fedex_rows(requests)
                carrier_fields = LIGHTSOURCE_FEDEX_IMPORT_FIELDS
            elif carrier == "ups":
                carrier_label = "UPS"
                carrier_path = write_lightsource_carrier_import(requests, carrier_label)
                carrier_rows = lightsource_ups_rows(requests)
                carrier_fields = LIGHTSOURCE_UPS_IMPORT_FIELDS
            report = lightsource_report_rows(requests)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        response = {
            "download_url": f"/download/{output_path.name}",
            "row_count": len(rows),
            "preview": rows[:50],
            "report_preview": report[:100],
            "carrier_label": carrier_label,
            "carrier_download_url": f"/download/{carrier_path.name}" if carrier_path else "",
            "carrier_preview": lightsource_carrier_preview_rows(carrier_fields, carrier_rows[:50]) if carrier_path else [],
        }
        self.send_json(response)

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
  <title>Returns Shipment Builder</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f9fc;
      --panel: #ffffff;
      --surface: #ffffff;
      --surface-soft: #f7faff;
      --ink: #10233f;
      --text: #10233f;
      --muted: #5f6f86;
      --line: #d9e3f0;
      --brand: #050505;
      --brand-hover: #242424;
      --brand-soft: #f1f4f8;
      --brand-soft-hover: #e4eaf2;
      --accent: #ffa970;
      --accent-dark: #f59231;
      --focus: #a7b4c6;
      --row-hover: #f8fbff;
      --success: #0f9f6e;
      --success-soft: #e8fbf3;
      --danger: #b42318;
      --danger-soft: #fff1f2;
      --warn: #b7791f;
      --warning-soft: #fff8e8;
      --shadow: 0 8px 22px rgba(16, 35, 63, 0.06);
      --radius-sm: 6px;
      --radius-md: 8px;
      --font-eyebrow: "Messina Sans Mono", "Courier New", monospace;
      --font-heading: "Copernicus", Georgia, serif;
      --font-subheading: "Messina Sans", "Segoe UI", Arial, sans-serif;
      --font-body: "Messina Sans", "Segoe UI", Arial, sans-serif;
      --font-mono: "Messina Sans Mono", "Courier New", monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 var(--font-body);
    }
    header {
      position: sticky;
      top: 0;
      z-index: 20;
      padding: 12px 24px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
      box-shadow: 0 1px 0 rgba(16, 35, 63, 0.08);
    }
    .header-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      margin: 0 0 6px;
      font-family: var(--font-heading);
      font-size: 26px;
      line-height: 1.05;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #000;
    }
    .subtle { color: var(--muted); }
    .brand-kicker {
      display: block;
      margin-bottom: 4px;
      color: var(--muted);
      font-family: var(--font-eyebrow);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    main {
      width: min(1240px, calc(100vw - 40px));
      margin: 22px auto 64px;
      display: grid;
      gap: 18px;
      min-width: 0;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      padding: 20px;
      box-shadow: var(--shadow);
      min-width: 0;
    }
    .compact-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .tool-panel {
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .tool-panel h2 {
      margin-bottom: 2px;
    }
    .manual-entry {
      display: grid;
      grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) 90px auto;
      gap: 10px;
      align-items: end;
      margin: 14px 0;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: #f8fbff;
    }
    .manual-entry label {
      margin: 0;
    }
    .tool-panel input[type=file] {
      padding: 12px;
    }
    .helper {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
    }
    .result-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    h2 {
      margin: 0 0 14px;
      font-family: var(--font-heading);
      font-size: 20px;
      line-height: 1.15;
      letter-spacing: -0.02em;
      color: var(--text);
    }
    input[type=file], textarea {
      display: block;
      width: 100%;
      padding: 18px;
      border: 1px dashed #b8c7da;
      border-radius: var(--radius-md);
      background: #ffffff;
      font: inherit;
      transition: border-color .16s ease, box-shadow .16s ease, background-color .16s ease;
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
      min-height: 42px;
      padding: 0 16px;
      border: 1px solid var(--brand);
      border-radius: var(--radius-sm);
      background: var(--brand);
      color: #fff;
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
      text-decoration: none;
      cursor: pointer;
      transition: background-color .16s ease, border-color .16s ease, color .16s ease, box-shadow .16s ease;
    }
    button:hover, button:focus-visible {
      background: var(--brand-hover);
      border-color: var(--brand-hover);
      box-shadow: 0 8px 18px rgba(5, 5, 5, 0.12);
    }
    .download {
      background: var(--brand-soft);
      border-color: #d7e3f6;
      color: var(--text);
    }
    .download:hover, .download:focus-visible {
      background: var(--brand-soft-hover);
      border-color: var(--focus);
      color: var(--text);
      box-shadow: 0 7px 16px rgba(16, 35, 63, 0.08);
    }
    button.secondary {
      background: var(--brand-soft);
      border-color: #d7e3f6;
      color: var(--text);
    }
    button.secondary:hover { background: var(--brand-soft-hover); border-color: var(--focus); color: var(--text); }
    button.danger {
      min-height: 30px;
      padding: 0 10px;
      background: var(--danger-soft);
      border-color: #fecdd3;
      color: var(--danger);
    }
    button.danger:hover { background: #ffe4e6; color: var(--danger); border-color: #fda4af; }
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
      position: sticky;
      top: 74px;
      z-index: 15;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      padding: 6px;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: rgba(247, 249, 252, 0.94);
      box-shadow: 0 8px 20px rgba(16, 35, 63, 0.04);
      backdrop-filter: blur(8px);
    }
    .tab {
      min-width: 112px;
      background: var(--brand-soft);
      border-color: #d7e3f6;
      color: var(--text);
    }
    .tab:hover, .tab:focus-visible {
      background: var(--brand-soft-hover);
      border-color: var(--focus);
      color: var(--text);
      box-shadow: 0 7px 16px rgba(16, 35, 63, 0.08);
    }
    .tab.active {
      background: var(--brand);
      border-color: var(--brand);
      color: #fff;
      box-shadow: 0 7px 16px rgba(5, 5, 5, 0.14);
    }
    .tab.active:hover, .tab.active:focus-visible {
      background: var(--brand-hover);
      border-color: var(--brand-hover);
      color: #fff;
      box-shadow: 0 8px 18px rgba(5, 5, 5, 0.12);
    }
    .theme-dock {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 5px;
      padding-left: 10px;
      border-left: 1px solid var(--line);
    }
    .theme-dock-label {
      margin-right: 2px;
      color: var(--muted);
      font-family: var(--font-eyebrow);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: .1em;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .theme-choice {
      min-height: 34px;
      width: 36px;
      padding: 0;
      background: var(--brand-soft);
      border-color: #d7e3f6;
      color: var(--text);
      letter-spacing: .04em;
      box-shadow: none;
    }
    .theme-choice:hover, .theme-choice:focus-visible {
      background: var(--brand-soft-hover);
      border-color: var(--focus);
      color: var(--text);
      box-shadow: 0 7px 16px rgba(16, 35, 63, 0.08);
    }
    .theme-choice.active {
      background: var(--brand);
      border-color: var(--brand);
      color: #fff;
      box-shadow: 0 7px 16px rgba(5, 5, 5, 0.14);
    }
    .theme-choice.active:hover, .theme-choice.active:focus-visible {
      background: var(--brand-hover);
      border-color: var(--brand-hover);
      color: #fff;
    }
    .theme-swatch {
      width: 14px;
      height: 14px;
      flex: 0 0 auto;
      border-radius: 999px;
      background: var(--swatch);
      box-shadow: 0 0 0 1px rgba(16, 35, 63, .16);
    }
    .files {
      display: grid;
      gap: 16px;
    }
    .file {
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      overflow: hidden;
      background: #fff;
    }
    .file-title {
      padding: 12px 14px;
      background: #f6f8fb;
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
      font-size: 13px;
      font-weight: 650;
    }
    select, .list-input {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: 8px 10px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      transition: border-color .16s ease, box-shadow .16s ease;
    }
    .compact-control {
      width: 190px;
      flex: 0 0 190px;
    }
    .preview {
      display: block;
      width: 100%;
      max-width: 100%;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      max-height: 360px;
      box-shadow: 0 6px 18px rgba(16, 35, 63, 0.04);
    }
    .table-wrap {
      display: block;
      width: 100%;
      max-width: 100%;
      overflow: auto;
      max-height: 300px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: #fff;
      box-shadow: 0 6px 18px rgba(16, 35, 63, 0.04);
      contain: layout paint;
    }
    .table-wrap table {
      width: max-content;
      min-width: 100%;
      max-width: none;
      border-collapse: collapse;
      border-spacing: 0;
      border: 0;
    }
    .table-wrap th,
    .table-wrap td {
      max-width: 190px;
      padding: 7px 8px;
    }
    .table-wrap th {
      position: sticky;
      top: 0;
      z-index: 2;
    }
    details.preview-panel {
      margin-top: 14px;
      min-width: 0;
      max-width: 100%;
      overflow: hidden;
    }
    details.preview-panel summary {
      cursor: pointer;
      user-select: none;
    }
    details.preview-panel .table-wrap,
    details.preview-panel .preview {
      margin-top: 8px;
    }
    table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: 760px;
      background: #fff;
    }
    th, td {
      border-bottom: 1px solid #edf1f5;
      padding: 9px 10px;
      text-align: left;
      white-space: nowrap;
      max-width: 240px;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    th {
      color: #344255;
      background: #f6f8fb;
      font-size: 12px;
      font-weight: 700;
      position: sticky;
      top: 0;
      z-index: 1;
    }
    .list-input {
      min-height: 30px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: 0 8px;
      font: inherit;
    }
    .order-input { width: 180px; }
    .sku-input { width: 190px; }
    .qty-input { width: 72px; }
    tbody tr:hover td { background: var(--row-hover); }
    .notice {
      padding: 12px 14px;
      border-radius: var(--radius-md);
      background: var(--warning-soft);
      color: var(--warn);
      border: 1px solid #fed7aa;
    }
    .success {
      padding: 14px;
      border: 1px solid #b7e4d5;
      background: var(--success-soft);
      border-radius: var(--radius-md);
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
      background: var(--warning-soft);
    }
    .danger {
      background: var(--danger-soft);
      border-color: #fecdd3;
      color: var(--danger);
      min-height: 34px;
      padding-inline: 10px;
    }
    .danger:hover, .danger:focus-visible {
      background: #ffe4e6;
      border-color: #fda4af;
      color: var(--danger);
      box-shadow: 0 7px 16px rgba(180, 35, 24, .08);
    }
    input[type=file]:hover, textarea:hover, select:hover, .list-input:hover {
      border-color: var(--focus);
    }
    input[type=file]:focus-visible, textarea:focus-visible, select:focus-visible,
    .list-input:focus-visible, button:focus-visible, .download:focus-visible, summary:focus-visible {
      outline: 2px solid var(--focus);
      outline-offset: 2px;
    }
    .designer-shell {
      display: grid;
      grid-template-columns: minmax(340px, 1fr) minmax(320px, 430px);
      gap: 16px;
      align-items: start;
    }
    .designer-controls, .designer-preview-panel {
      min-width: 0;
      display: grid;
      gap: 12px;
    }
    .designer-list {
      display: grid;
      gap: 7px;
      max-height: 260px;
      overflow: auto;
      padding-right: 3px;
    }
    .designer-item {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: #fff;
      cursor: pointer;
    }
    .designer-item.active {
      border-color: var(--brand);
      box-shadow: inset 3px 0 0 var(--brand);
    }
    .designer-item strong { overflow-wrap: anywhere; }
    .designer-editor {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: #fff;
    }
    .designer-editor label {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .designer-editor input, .designer-editor select {
      width: 100%;
      min-height: 34px;
      padding: 7px 9px;
      border: 1px solid #cbd5e1;
      border-radius: var(--radius-sm);
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    .label-preview-canvas {
      position: relative;
      width: min(100%, 4in);
      aspect-ratio: 4 / 6;
      margin: 0 auto;
      border: 1px solid #111827;
      background: #fff;
      box-shadow: 0 14px 34px rgba(15, 23, 42, .16);
      overflow: visible;
    }
    .label-preview-canvas.landscape {
      width: min(100%, 6in);
      aspect-ratio: 6 / 4;
    }
    .preview-el {
      position: absolute;
      min-width: 8px;
      min-height: 8px;
      overflow: hidden;
      padding: 3px;
      border: 1px solid transparent;
      background: transparent;
      color: #111827;
      cursor: pointer;
      user-select: none;
      touch-action: none;
    }
    .preview-el.active {
      border: 2px solid var(--brand);
      background: rgba(255, 255, 255, .9);
      overflow: visible;
    }
    .preview-delete {
      position: absolute;
      top: -15px;
      right: -10px;
      z-index: 45;
      width: 16px;
      height: 16px;
      display: grid;
      place-items: center;
      border: 0;
      border-radius: 0;
      background: transparent;
      color: #b42318;
      font: 900 13px/1 Arial, sans-serif;
      cursor: pointer;
      box-shadow: none;
      padding: 0;
      min-height: 0;
    }
    .preview-delete:hover, .preview-delete:focus-visible { background: transparent; color: #7f1d1d; box-shadow: none; }
    .resize-handle {
      position: absolute;
      z-index: 44;
      width: 10px;
      height: 10px;
      border: 1px solid #fff;
      border-radius: 999px;
      background: var(--brand);
      box-shadow: 0 1px 4px rgba(16, 35, 63, .22);
    }
    .resize-handle.nw { left: -6px; top: -6px; cursor: nwse-resize; }
    .resize-handle.n { left: 50%; top: -6px; transform: translateX(-50%); cursor: ns-resize; }
    .resize-handle.ne { right: -6px; top: -6px; cursor: nesw-resize; }
    .resize-handle.e { right: -6px; top: 50%; transform: translateY(-50%); cursor: ew-resize; }
    .resize-handle.se { right: -6px; bottom: -6px; cursor: nwse-resize; }
    .resize-handle.s { left: 50%; bottom: -6px; transform: translateX(-50%); cursor: ns-resize; }
    .resize-handle.sw { left: -6px; bottom: -6px; cursor: nesw-resize; }
    .resize-handle.w { left: -6px; top: 50%; transform: translateY(-50%); cursor: ew-resize; }
    .snap-guide {
      position: absolute;
      z-index: 40;
      pointer-events: none;
      background: #1e90ff;
      box-shadow: 0 0 0 1px rgba(30, 144, 255, .18);
    }
    .snap-guide.vertical {
      top: 0;
      bottom: 0;
      width: 2px;
    }
    .snap-guide.horizontal {
      left: 0;
      right: 0;
      height: 2px;
    }
    .preview-el span {
      display: block;
      color: #64748b;
      font-size: 8px;
      font-weight: 800;
      text-transform: uppercase;
      line-height: 1.1;
    }
    .preview-el strong {
      display: block;
      overflow-wrap: anywhere;
      line-height: 1.05;
    }
    .preview-barcode {
      display: grid;
      gap: 2px;
      align-content: center;
      justify-items: stretch;
      text-align: center;
    }
    .preview-bars {
      height: 24px;
      background: repeating-linear-gradient(90deg, #000 0 2px, #fff 2px 4px, #000 4px 5px, #fff 5px 8px);
      border-inline: 8px solid #fff;
    }
    .preview-qr {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      place-items: center;
      text-align: center;
    }
    .preview-qr::after {
      content: "QR";
      display: grid;
      place-items: center;
      width: min(100%, 100px);
      height: min(100%, 100px);
      aspect-ratio: 1;
      border: 2px solid #111827;
      font-weight: 900;
    }
    .preview-table {
      padding: 0;
    }
    .preview-table-clip {
      width: 100%;
      height: 100%;
      overflow: hidden;
    }
    .preview-table table {
      width: 100%;
      max-width: 100%;
      min-width: 0;
      border-collapse: collapse;
      table-layout: fixed;
    }
    .preview-table td, .preview-table th {
      padding: 2px;
      border-bottom: 1px solid #e5e7eb;
      font-size: 8px;
      max-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .hidden { display: none; }
    @media (max-width: 860px) {
      header { padding-inline: 18px; }
      .mapping { grid-template-columns: 1fr; }
      .compact-grid, .result-grid { grid-template-columns: 1fr; }
      .designer-shell { grid-template-columns: 1fr; }
      .manual-entry { grid-template-columns: 1fr; }
      .theme-dock {
        width: 100%;
        margin-left: 0;
        padding-left: 0;
        padding-top: 8px;
        border-left: 0;
        border-top: 1px solid var(--line);
        overflow-x: auto;
      }
    }
  </style>
</head>
<body>
  <div id="updateBanner" class="update-banner"></div>
  <header>
    <div class="header-top">
      <div>
        <span class="brand-kicker">Soapbox Operations</span>
        <h1>Returns Shipment Builder</h1>
        <div class="subtle">Build inbound returns, onboarding imports, and replacement order CSVs from one local workspace.</div>
      </div>
      <button class="secondary" id="closeApp" type="button">Close App</button>
    </div>
  </header>
  <main>
    <div class="tabs">
      <button class="tab active" id="christyTab">Christy / Spreadsheet Upload</button>
      <button class="tab" id="havnTab">Havn Email Paste</button>
      <button class="tab" id="bulkInboundTab">Onboarding</button>
      <button class="tab" id="inboundLabelsTab">Carton Labels</button>
      <button class="tab" id="lightsourceTab">Lightsource</button>
      <button class="tab" id="outboundTab">Outbound Replacement</button>
      <div class="theme-dock" aria-label="Button color theme">
        <span class="theme-dock-label">Buttons</span>
        <button class="theme-choice active" type="button" data-theme-choice="default" title="Default black buttons" aria-label="Default black buttons"><span class="theme-swatch" style="--swatch:#050505"></span></button>
        <button class="theme-choice" type="button" data-theme-choice="dodger" title="Dodger blue mode" aria-label="Dodger blue mode"><span class="theme-swatch" style="--swatch:#1e90ff"></span></button>
        <button class="theme-choice" type="button" data-theme-choice="eagles" title="Eagles midnight green mode" aria-label="Eagles midnight green mode"><span class="theme-swatch" style="--swatch:#004c54"></span></button>
        <button class="theme-choice" type="button" data-theme-choice="sunset" title="Sunset orange mode" aria-label="Sunset orange mode"><span class="theme-swatch" style="--swatch:#f97316"></span></button>
        <button class="theme-choice" type="button" data-theme-choice="grape" title="Grape purple mode" aria-label="Grape purple mode"><span class="theme-swatch" style="--swatch:#7c3aed"></span></button>
        <button class="theme-choice" type="button" data-theme-choice="mint" title="Mint green mode" aria-label="Mint green mode"><span class="theme-swatch" style="--swatch:#0f9f6e"></span></button>
        <button class="theme-choice" type="button" id="randomTheme" title="Random color mode" aria-label="Random color mode"><span class="theme-swatch" style="--swatch:linear-gradient(135deg,#1e90ff,#f97316,#0f9f6e)"></span></button>
      </div>
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
        <div class="manual-entry">
          <label>Order #
            <input id="havnManualOrder" class="list-input" type="text" placeholder="0617022189174727">
          </label>
          <label>SKU
            <input id="havnManualSku" class="list-input" type="text" placeholder="FD-ULGHTBNE-BLK-1">
          </label>
          <label>Qty
            <input id="havnManualQty" class="list-input qty-input" type="text" inputmode="numeric" value="1">
          </label>
          <button id="havnManualAdd" type="button">Add Row</button>
        </div>
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

    <div id="bulkInboundApp" class="hidden">
      <div class="compact-grid">
        <section class="tool-panel">
          <h2>Product Setup</h2>
          <p class="helper">Convert a customer product listing into the product variants import CSV.</p>
          <input id="productListingFile" type="file" accept=".csv,.xlsx,.xls,.xlsm">
          <div class="row">
            <button id="productVariantsGenerate">Create Product CSV</button>
            <span id="productVariantsStatus" class="subtle"></span>
          </div>
        </section>

        <section class="tool-panel">
          <h2>Inbound Shipment</h2>
          <p class="helper">Convert a pack list, BOL, PO, CSV, Excel, or searchable PDF into the bulk inbound upload.</p>
          <label>Customer document
            <input id="bulkDocuments" type="file" multiple accept=".xlsx,.xls,.xlsm,.csv,.pdf">
          </label>
          <label>Product variants for SKU check
            <input id="bulkProductVariants" type="file" accept=".csv,.xlsx,.xls,.xlsm">
          </label>
          <div class="row">
            <button id="bulkInboundGenerate">Create Inbound CSV</button>
            <span id="bulkInboundStatus" class="subtle"></span>
          </div>
        </section>
      </div>

      <div class="result-grid">
        <section id="productVariantsResultSection" class="hidden">
          <h2>Product Result</h2>
          <div id="productVariantsResult"></div>
        </section>
        <section id="bulkInboundResultSection" class="hidden">
          <h2>Inbound Result</h2>
          <div id="bulkInboundResult"></div>
        </section>
      </div>
    </div>

    <div id="inboundLabelsApp" class="hidden">
      <section>
        <h2>Inbound 4x6 Carton Labels</h2>
        <p class="helper">Upload an inbound pack list, PO, BOL, CSV, Excel file, or searchable PDF. Carton-numbered rows are grouped into single or mixed-SKU carton labels; rows without carton numbers expand from carton/case count.</p>
        <label>Inbound document
          <input id="labelDocuments" type="file" multiple accept=".xlsx,.xls,.xlsm,.csv,.pdf">
        </label>
        <label>Product variants for product names
          <input id="labelProductVariants" type="file" accept=".csv,.xlsx,.xls,.xlsm">
        </label>
        <div class="row">
          <button id="inboundLabelsGenerate">Generate 4x6 Labels</button>
          <a class="download" href="/template/inbound-labels.csv">Download Label Template</a>
          <span id="inboundLabelsStatus" class="subtle"></span>
        </div>
      </section>

      <section id="inboundLabelsResultSection" class="hidden">
        <h2>Label Result</h2>
        <div id="inboundLabelsResult"></div>
      </section>

      <section>
        <h2>Label Designer</h2>
        <p class="helper">Build a reusable 4x6 layout from text, table, Code 128 barcode, and QR code blocks.</p>
        <div class="designer-shell">
          <div class="designer-controls">
            <div class="row">
              <label class="compact-control">Preset
                <select id="labelPreset">
                  <option value="blindReceive">Blind Receive</option>
                  <option value="systemReceive">System Receive</option>
                  <option value="inbound">Inbound Carton</option>
                  <option value="lot">LOT Label</option>
                  <option value="sku">SKU / Bin Label</option>
                  <option value="blank">Blank</option>
                </select>
              </label>
            </div>
            <div class="row">
              <button id="labelAddText" type="button">Add Text</button>
              <button id="labelAddBarcode" type="button">Add Barcode</button>
              <button id="labelAddTable" type="button">Add Table</button>
              <button id="labelAddQr" type="button">Add QR</button>
            </div>
            <div id="labelElementList" class="designer-list"></div>
            <div id="labelElementEditor" class="designer-editor subtle">Select an element to edit it.</div>
          </div>
          <div class="designer-preview-panel">
            <div id="labelPreviewCanvas" class="label-preview-canvas"></div>
          </div>
        </div>
        <div class="row">
          <button id="labelDesignerGenerate" type="button">Generate Custom Labels</button>
          <button id="labelSaveTemplate" class="tab" type="button">Save Template</button>
          <button id="labelLoadTemplate" class="tab" type="button">Load Saved Template</button>
          <span id="labelDesignerStatus" class="subtle"></span>
        </div>
      </section>

      <section id="labelDesignerResultSection" class="hidden">
        <h2>Custom Label Result</h2>
        <div id="labelDesignerResult"></div>
      </section>
    </div>

    <div id="lightsourceApp" class="hidden">
      <section>
        <h2>Lightsource Email</h2>
        <textarea id="lightsourceEmail" placeholder="Paste one Lightsource print order email here..."></textarea>
        <div class="row">
          <button id="lightsourceAdd">Add Email to List</button>
          <button id="lightsourceClear" class="tab">Clear List</button>
          <span id="lightsourceStatus" class="subtle"></span>
        </div>
      </section>

      <section>
        <h2>Lightsource Order List</h2>
        <div id="lightsourceList" class="subtle">No Lightsource emails added yet.</div>
        <div class="row">
          <label class="compact-control">Carrier import
            <select id="lightsourceCarrier">
              <option value="none">None</option>
              <option value="fedex">FedEx</option>
              <option value="ups">UPS</option>
            </select>
          </label>
          <button id="lightsourceExport">Generate Lightsource CSV</button>
        </div>
      </section>

      <section id="lightsourceResultSection" class="hidden">
        <h2>Lightsource Result</h2>
        <div id="lightsourceResult"></div>
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
    let lightsourceRequests = [];
    let labelDesignerElements = [];
    let selectedLabelElementId = "";

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
    const productVariantsStatusEl = document.querySelector("#productVariantsStatus");
    const productVariantsResultSection = document.querySelector("#productVariantsResultSection");
    const productVariantsResultEl = document.querySelector("#productVariantsResult");
    const bulkInboundStatusEl = document.querySelector("#bulkInboundStatus");
    const bulkInboundResultSection = document.querySelector("#bulkInboundResultSection");
    const bulkInboundResultEl = document.querySelector("#bulkInboundResult");
    const inboundLabelsStatusEl = document.querySelector("#inboundLabelsStatus");
    const inboundLabelsResultSection = document.querySelector("#inboundLabelsResultSection");
    const inboundLabelsResultEl = document.querySelector("#inboundLabelsResult");
    const labelDesignerStatusEl = document.querySelector("#labelDesignerStatus");
    const labelDesignerResultSection = document.querySelector("#labelDesignerResultSection");
    const labelDesignerResultEl = document.querySelector("#labelDesignerResult");
    const labelElementListEl = document.querySelector("#labelElementList");
    const labelElementEditorEl = document.querySelector("#labelElementEditor");
    const labelPreviewCanvasEl = document.querySelector("#labelPreviewCanvas");
    const lightsourceStatusEl = document.querySelector("#lightsourceStatus");
    const lightsourceListEl = document.querySelector("#lightsourceList");
    const lightsourceResultSection = document.querySelector("#lightsourceResultSection");
    const lightsourceResultEl = document.querySelector("#lightsourceResult");
    const outboundStatusEl = document.querySelector("#outboundStatus");
    const outboundResultSection = document.querySelector("#outboundResultSection");
    const outboundResultEl = document.querySelector("#outboundResult");
    const updateBannerEl = document.querySelector("#updateBanner");

    checkForUpdates();

    document.querySelector("#christyTab").addEventListener("click", () => setAppTab("christy"));
    document.querySelector("#havnTab").addEventListener("click", () => setAppTab("havn"));
    document.querySelector("#bulkInboundTab").addEventListener("click", () => setAppTab("bulkInbound"));
    document.querySelector("#inboundLabelsTab").addEventListener("click", () => setAppTab("inboundLabels"));
    document.querySelector("#lightsourceTab").addEventListener("click", () => setAppTab("lightsource"));
    document.querySelector("#outboundTab").addEventListener("click", () => setAppTab("outbound"));
    document.querySelectorAll("[data-theme-choice]").forEach((button) => {
      button.addEventListener("click", () => applyButtonTheme(button.dataset.themeChoice));
    });
    document.querySelector("#randomTheme").addEventListener("click", () => {
      const choices = ["dodger", "eagles", "sunset", "grape", "mint", "berry", "copper", "sky"];
      applyButtonTheme(choices[Math.floor(Math.random() * choices.length)]);
    });
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
      document.querySelector("#bulkInboundApp").classList.toggle("hidden", tabName !== "bulkInbound");
      document.querySelector("#inboundLabelsApp").classList.toggle("hidden", tabName !== "inboundLabels");
      document.querySelector("#lightsourceApp").classList.toggle("hidden", tabName !== "lightsource");
      document.querySelector("#outboundApp").classList.toggle("hidden", tabName !== "outbound");
      document.querySelector("#christyTab").classList.toggle("active", tabName === "christy");
      document.querySelector("#havnTab").classList.toggle("active", tabName === "havn");
      document.querySelector("#bulkInboundTab").classList.toggle("active", tabName === "bulkInbound");
      document.querySelector("#inboundLabelsTab").classList.toggle("active", tabName === "inboundLabels");
      document.querySelector("#lightsourceTab").classList.toggle("active", tabName === "lightsource");
      document.querySelector("#outboundTab").classList.toggle("active", tabName === "outbound");
      if (tabName === "inboundLabels") {
        requestAnimationFrame(renderLabelPreview);
      }
    }

    const buttonThemes = {
      default: { brand: "#050505", hover: "#242424", soft: "#f1f4f8", softHover: "#e4eaf2", focus: "#a7b4c6" },
      dodger: { brand: "#1e90ff", hover: "#0f74d1", soft: "#edf3ff", softHover: "#dce8ff", focus: "#9eb7e8" },
      eagles: { brand: "#004c54", hover: "#00373d", soft: "#e8f4f5", softHover: "#cfe7ea", focus: "#7bb9bf" },
      sunset: { brand: "#f97316", hover: "#ea580c", soft: "#fff7ed", softHover: "#ffedd5", focus: "#fdba74" },
      grape: { brand: "#7c3aed", hover: "#6d28d9", soft: "#f3e8ff", softHover: "#e9d5ff", focus: "#c4b5fd" },
      mint: { brand: "#0f9f6e", hover: "#0b7f58", soft: "#e8fbf3", softHover: "#d1fae5", focus: "#86efac" },
      berry: { brand: "#be185d", hover: "#9d174d", soft: "#fdf2f8", softHover: "#fce7f3", focus: "#f9a8d4" },
      copper: { brand: "#b45309", hover: "#92400e", soft: "#fffbeb", softHover: "#fef3c7", focus: "#fcd34d" },
      sky: { brand: "#0369a1", hover: "#075985", soft: "#e0f2fe", softHover: "#bae6fd", focus: "#7dd3fc" },
    };

    function applyButtonTheme(themeName, shouldSave = true) {
      const safeName = buttonThemes[themeName] ? themeName : "default";
      const theme = buttonThemes[safeName];
      const root = document.documentElement;
      root.style.setProperty("--brand", theme.brand);
      root.style.setProperty("--brand-hover", theme.hover);
      root.style.setProperty("--brand-soft", theme.soft);
      root.style.setProperty("--brand-soft-hover", theme.softHover);
      root.style.setProperty("--focus", theme.focus);
      document.querySelectorAll("[data-theme-choice]").forEach((button) => {
        button.classList.toggle("active", button.dataset.themeChoice === safeName);
      });
      document.querySelector("#randomTheme").classList.toggle("active", !document.querySelector(`[data-theme-choice="${safeName}"]`));
      if (shouldSave) {
        localStorage.setItem("returnsButtonTheme", safeName);
      }
    }

    applyButtonTheme(localStorage.getItem("returnsButtonTheme") || "default", false);

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
        const incomingItems = (data.items || data.skus.map(sku => ({ sku, qty: "1" }))).map(item => ({
          sku: String(item.sku || "").trim().toUpperCase(),
          qty: String(item.qty || "1").trim() || "1",
        })).filter(item => item.sku);
        const result = addHavnItems(data.order_number, incomingItems);
        document.querySelector("#havnEmail").value = "";
        renderHavnList();
        if (!result.added) {
          havnStatusEl.textContent = `Already added: ${data.order_number} with the same SKU and qty.`;
        } else if (result.duplicates) {
          havnStatusEl.textContent = `Added ${result.added} row${result.added === 1 ? "" : "s"} and skipped ${result.duplicates} duplicate row${result.duplicates === 1 ? "" : "s"}.`;
        } else {
          havnStatusEl.textContent = `Added ${data.order_number} with ${result.added} row${result.added === 1 ? "" : "s"}.`;
        }
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

    havnListEl.addEventListener("change", event => {
      if (!event.target.matches("[data-edit-havn-item]")) return;
      saveHavnItemEdit(event.target);
    });

    havnListEl.addEventListener("keydown", event => {
      if (!event.target.matches("[data-edit-havn-item]") || event.key !== "Enter") return;
      event.preventDefault();
      saveHavnItemEdit(event.target);
      event.target.blur();
    });

    havnListEl.addEventListener("click", event => {
      const button = event.target.closest("[data-remove-havn-item]");
      if (!button) return;
      const requestIndex = Number(button.dataset.requestIndex);
      const itemIndex = Number(button.dataset.itemIndex);
      const request = havnRequests[requestIndex];
      const item = request?.items?.[itemIndex];
      if (!request || !item) return;
      const orderNumber = `${request.order_number} RET`;
      if (!confirm(`Remove ${item.sku} from ${orderNumber}?`)) return;
      request.items.splice(itemIndex, 1);
      if (!request.items.length) {
        havnRequests.splice(requestIndex, 1);
      }
      havnResultSection.classList.add("hidden");
      havnStatusEl.textContent = `Removed ${item.sku} from ${orderNumber}.`;
      renderHavnList();
    });

    document.querySelector("#havnManualAdd").addEventListener("click", () => {
      const order = document.querySelector("#havnManualOrder").value.trim();
      const sku = document.querySelector("#havnManualSku").value.trim().toUpperCase();
      const qty = document.querySelector("#havnManualQty").value.trim() || "1";
      havnResultSection.classList.add("hidden");
      if (!order || !sku || !qty) {
        havnStatusEl.textContent = "Manual rows need an order number, SKU, and qty.";
        return;
      }
      const result = addHavnItems(order, [{ sku, qty }]);
      renderHavnList();
      if (!result.added) {
        havnStatusEl.textContent = `Already added: ${cleanHavnOrderNumber(order)} with ${sku} qty ${qty}.`;
        return;
      }
      document.querySelector("#havnManualOrder").value = "";
      document.querySelector("#havnManualSku").value = "";
      document.querySelector("#havnManualQty").value = "1";
      havnStatusEl.textContent = `Added manual row for ${cleanHavnOrderNumber(order)} / ${sku} / qty ${qty}.`;
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

    document.querySelector("#bulkInboundGenerate").addEventListener("click", async () => {
      const documents = [...document.querySelector("#bulkDocuments").files];
      const productVariants = document.querySelector("#bulkProductVariants").files[0];
      bulkInboundResultSection.classList.add("hidden");
      if (!documents.length) {
        bulkInboundStatusEl.textContent = "Upload at least one customer document first.";
        return;
      }
      bulkInboundStatusEl.textContent = "Reading customer documents...";
      document.querySelector("#bulkInboundGenerate").disabled = true;
      const form = new FormData();
      documents.forEach(file => form.append("documents", file));
      if (productVariants) {
        form.append("product_variants", productVariants);
      }
      try {
        const response = await fetch("/api/bulk-inbound/generate", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) {
          bulkInboundStatusEl.textContent = data.error || "Could not generate the bulk inbound CSV.";
          return;
        }
        bulkInboundStatusEl.textContent = "Bulk inbound CSV and review report are ready.";
        renderBulkInboundResult(data);
      } catch (error) {
        bulkInboundStatusEl.textContent = "The server stopped responding while reading the customer documents.";
      } finally {
        document.querySelector("#bulkInboundGenerate").disabled = false;
      }
    });
    document.querySelector("#inboundLabelsGenerate").addEventListener("click", async () => {
      const documents = [...document.querySelector("#labelDocuments").files];
      const productVariants = document.querySelector("#labelProductVariants").files[0];
      inboundLabelsResultSection.classList.add("hidden");
      if (!documents.length) {
        inboundLabelsStatusEl.textContent = "Upload at least one inbound document first.";
        return;
      }
      inboundLabelsStatusEl.textContent = "Building carton labels...";
      document.querySelector("#inboundLabelsGenerate").disabled = true;
      const form = new FormData();
      documents.forEach(file => form.append("documents", file));
      if (productVariants) {
        form.append("product_variants", productVariants);
      }
      try {
        const response = await fetch("/api/inbound-labels/generate", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) {
          inboundLabelsStatusEl.textContent = data.error || "Could not generate carton labels.";
          return;
        }
        inboundLabelsStatusEl.textContent = `${data.label_count} 4x6 label${data.label_count === 1 ? "" : "s"} ready.`;
        renderInboundLabelsResult(data);
      } catch (error) {
        inboundLabelsStatusEl.textContent = "The server stopped responding while building carton labels.";
      } finally {
        document.querySelector("#inboundLabelsGenerate").disabled = false;
      }
    });

    document.querySelector("#labelDesignerGenerate").addEventListener("click", async () => {
      const documents = [...document.querySelector("#labelDocuments").files];
      const productVariants = document.querySelector("#labelProductVariants").files[0];
      labelDesignerResultSection.classList.add("hidden");
      if (!documents.length) {
        labelDesignerStatusEl.textContent = "Upload at least one source document above.";
        return;
      }
      labelDesignerStatusEl.textContent = "Generating custom labels...";
      document.querySelector("#labelDesignerGenerate").disabled = true;
      const form = new FormData();
      documents.forEach(file => form.append("documents", file));
      if (productVariants) form.append("product_variants", productVariants);
      form.append("template", JSON.stringify({
        preset: document.querySelector("#labelPreset").value,
        elements: labelDesignerElements,
      }));
      try {
        const response = await fetch("/api/label-designer/generate", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) {
          labelDesignerStatusEl.textContent = data.error || "Could not generate custom labels.";
          return;
        }
        labelDesignerStatusEl.textContent = `${data.label_count} custom label${data.label_count === 1 ? "" : "s"} ready.`;
        renderLabelDesignerResult(data);
      } catch (error) {
        labelDesignerStatusEl.textContent = "The server stopped responding while generating custom labels.";
      } finally {
        document.querySelector("#labelDesignerGenerate").disabled = false;
      }
    });

    document.querySelector("#productVariantsGenerate").addEventListener("click", async () => {
      const file = document.querySelector("#productListingFile").files[0];
      productVariantsResultSection.classList.add("hidden");
      if (!file) {
        productVariantsStatusEl.textContent = "Upload a customer product listing first.";
        return;
      }
      productVariantsStatusEl.textContent = "Reading product listing...";
      document.querySelector("#productVariantsGenerate").disabled = true;
      const form = new FormData();
      form.append("file", file);
      try {
        const response = await fetch("/api/product-variants/generate", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) {
          productVariantsStatusEl.textContent = data.error || "Could not generate the product variants CSV.";
          return;
        }
        productVariantsStatusEl.textContent = "Product variants CSV and review report are ready.";
        renderProductVariantsResult(data);
      } catch (error) {
        productVariantsStatusEl.textContent = "The server stopped responding while reading the product listing.";
      } finally {
        document.querySelector("#productVariantsGenerate").disabled = false;
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

    document.querySelector("#lightsourceAdd").addEventListener("click", async () => {
      const text = document.querySelector("#lightsourceEmail").value.trim();
      lightsourceResultSection.classList.add("hidden");
      if (!text) {
        lightsourceStatusEl.textContent = "Paste one Lightsource email first.";
        return;
      }
      lightsourceStatusEl.textContent = "Reading email...";
      document.querySelector("#lightsourceAdd").disabled = true;
      try {
        const response = await fetch("/api/lightsource/parse", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        const data = await response.json();
        if (!response.ok) {
          lightsourceStatusEl.textContent = data.error || "Could not parse that email.";
          return;
        }
        if (lightsourceRequests.some(request => request.order_number.trim().toUpperCase() === data.order_number.trim().toUpperCase())) {
          lightsourceStatusEl.textContent = `Already added: ${data.order_number}.`;
          return;
        }
        lightsourceRequests.push(data);
        document.querySelector("#lightsourceEmail").value = "";
        lightsourceStatusEl.textContent = `Added ${data.order_number} with ${data.items.length} item${data.items.length === 1 ? "" : "s"}.`;
        renderLightsourceList();
      } catch (error) {
        lightsourceStatusEl.textContent = "The server stopped responding while parsing the email.";
      } finally {
        document.querySelector("#lightsourceAdd").disabled = false;
      }
    });

    document.querySelector("#lightsourceClear").addEventListener("click", () => {
      lightsourceRequests = [];
      lightsourceResultSection.classList.add("hidden");
      lightsourceStatusEl.textContent = "List cleared.";
      renderLightsourceList();
    });

    lightsourceListEl.addEventListener("change", event => {
      if (!event.target.matches("[data-edit-lightsource-item]")) return;
      saveLightsourceItemEdit(event.target);
    });

    lightsourceListEl.addEventListener("keydown", event => {
      if (!event.target.matches("[data-edit-lightsource-item]") || event.key !== "Enter") return;
      event.preventDefault();
      saveLightsourceItemEdit(event.target);
      event.target.blur();
    });

    lightsourceListEl.addEventListener("click", event => {
      const button = event.target.closest("[data-remove-lightsource-item]");
      if (!button) return;
      const requestIndex = Number(button.dataset.requestIndex);
      const itemIndex = Number(button.dataset.itemIndex);
      const request = lightsourceRequests[requestIndex];
      const item = request?.items?.[itemIndex];
      if (!request || !item) return;
      if (!confirm(`Remove ${item.sku} from ${request.order_number}?`)) return;
      request.items.splice(itemIndex, 1);
      if (!request.items.length) {
        lightsourceRequests.splice(requestIndex, 1);
      }
      lightsourceResultSection.classList.add("hidden");
      lightsourceStatusEl.textContent = `Removed ${item.sku} from ${request.order_number}.`;
      renderLightsourceList();
    });

    document.querySelector("#lightsourceExport").addEventListener("click", async () => {
      if (!lightsourceRequests.length) {
        lightsourceStatusEl.textContent = "Add at least one Lightsource email first.";
        return;
      }
      lightsourceStatusEl.textContent = "Generating Lightsource CSV...";
      document.querySelector("#lightsourceExport").disabled = true;
      try {
        const carrier = document.querySelector("#lightsourceCarrier").value;
        const response = await fetch("/api/lightsource/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ requests: lightsourceRequests, carrier }),
        });
        const data = await response.json();
        if (!response.ok) {
          lightsourceStatusEl.textContent = data.error || "Could not generate Lightsource import.";
          return;
        }
        lightsourceStatusEl.textContent = data.carrier_label ? `Lightsource SB and ${data.carrier_label} CSV files are ready.` : "Lightsource SB CSV is ready.";
        renderLightsourceResult(data);
      } catch (error) {
        lightsourceStatusEl.textContent = "The server stopped responding while generating the Lightsource import.";
      } finally {
        document.querySelector("#lightsourceExport").disabled = false;
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

    function havnItemKey(order, sku, qty) {
      return `${cleanHavnOrderNumber(order).toUpperCase()}|${String(sku || "").trim().toUpperCase()}|${String(qty || "1").trim() || "1"}`;
    }

    function addHavnItems(order, items) {
      const cleanOrder = cleanHavnOrderNumber(order);
      const existing = new Set();
      havnRequests.forEach(request => {
        request.items.forEach(item => existing.add(havnItemKey(request.order_number, item.sku, item.qty)));
      });
      let request = havnRequests.find(candidate => candidate.order_number.trim().toUpperCase() === cleanOrder.toUpperCase());
      let added = 0;
      let duplicates = 0;
      items.forEach(item => {
        const sku = String(item.sku || "").trim().toUpperCase();
        const qty = String(item.qty || "1").trim() || "1";
        if (!cleanOrder || !sku || !qty) return;
        const key = havnItemKey(cleanOrder, sku, qty);
        if (existing.has(key)) {
          duplicates += 1;
          return;
        }
        if (!request) {
          request = { order_number: cleanOrder, items: [] };
          havnRequests.push(request);
        }
        request.items.push({ sku, qty });
        existing.add(key);
        added += 1;
      });
      havnResultSection.classList.add("hidden");
      return { added, duplicates };
    }

    function renderHavnList() {
      if (!havnRequests.length) {
        havnListEl.className = "subtle";
        havnListEl.textContent = "No Havn emails added yet.";
        return;
      }
      const rows = [];
      havnRequests.forEach((request, requestIndex) => {
        request.items.forEach((item, itemIndex) => {
          rows.push({
            "Order Number": `<input class="list-input order-input" data-edit-havn-item data-field="order_number" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(`${request.order_number} RET`)}" aria-label="Order number for ${escapeHtml(item.sku)}">`,
            "SKU": `<input class="list-input sku-input" data-edit-havn-item data-field="sku" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(item.sku)}" aria-label="SKU for ${escapeHtml(`${request.order_number} RET`)}">`,
            "Qty": `<input class="list-input qty-input" data-edit-havn-item data-field="qty" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(item.qty || "1")}" inputmode="numeric" aria-label="Quantity for ${escapeHtml(item.sku)}">`,
            "Remove": `<button class="danger" type="button" data-remove-havn-item data-request-index="${requestIndex}" data-item-index="${itemIndex}">Remove</button>`,
          });
        });
      });
      havnListEl.className = "preview";
      havnListEl.innerHTML = htmlTable(rows);
    }

    function saveHavnItemEdit(input) {
      const requestIndex = Number(input.dataset.requestIndex);
      const itemIndex = Number(input.dataset.itemIndex);
      const field = input.dataset.field;
      const request = havnRequests[requestIndex];
      const item = request?.items?.[itemIndex];
      if (!request || !item) return;
      let value = input.value.trim();
      if (field === "order_number") {
        value = cleanHavnOrderNumber(value);
        request.order_number = value;
        renderHavnList();
      } else if (field === "sku") {
        value = value || item.sku;
        item.sku = value;
        input.value = value;
      } else if (field === "qty") {
        value = value || "1";
        item.qty = value;
        input.value = value;
      }
      havnResultSection.classList.add("hidden");
      havnStatusEl.textContent = `Saved ${fieldLabel(field)} for ${item.sku}.`;
    }

    function cleanHavnOrderNumber(value) {
      return value.replace(/\s+RET$/i, "").trim();
    }

    function fieldLabel(field) {
      if (field === "order_number") return "order number";
      if (field === "sku") return "SKU";
      if (field === "qty") return "qty";
      if (field === "recipient") return "recipient";
      if (field === "company") return "company";
      if (field === "address_line_1") return "address line 1";
      if (field === "address_line_2") return "address line 2";
      if (field === "city") return "city";
      if (field === "state") return "state";
      if (field === "postal_code") return "postal code";
      if (field === "country") return "country";
      if (field === "email") return "email";
      if (field === "phone") return "phone";
      return "change";
    }

    function renderLightsourceList() {
      if (!lightsourceRequests.length) {
        lightsourceListEl.className = "subtle";
        lightsourceListEl.textContent = "No Lightsource emails added yet.";
        return;
      }
      const rows = [];
      lightsourceRequests.forEach((request, requestIndex) => {
        request.items.forEach((item, itemIndex) => {
          rows.push({
            "Order Number": `<input class="list-input order-input" data-edit-lightsource-item data-field="order_number" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.order_number || "")}" aria-label="Order number for ${escapeHtml(item.sku)}">`,
            "Company": `<input class="list-input sku-input" data-edit-lightsource-item data-field="company" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.company || "")}" aria-label="Company for ${escapeHtml(request.order_number)}">`,
            "Recipient": `<input class="list-input sku-input" data-edit-lightsource-item data-field="recipient" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.recipient || "")}" aria-label="Recipient for ${escapeHtml(request.order_number)}">`,
            "Address 1": `<input class="list-input sku-input" data-edit-lightsource-item data-field="address_line_1" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.address_line_1 || "")}" aria-label="Address line 1 for ${escapeHtml(request.order_number)}">`,
            "Address 2": `<input class="list-input sku-input" data-edit-lightsource-item data-field="address_line_2" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.address_line_2 || "")}" aria-label="Address line 2 for ${escapeHtml(request.order_number)}">`,
            "City": `<input class="list-input sku-input" data-edit-lightsource-item data-field="city" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.city || "")}" aria-label="City for ${escapeHtml(request.order_number)}">`,
            "State": `<input class="list-input qty-input" data-edit-lightsource-item data-field="state" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.state || "")}" aria-label="State for ${escapeHtml(request.order_number)}">`,
            "Zip": `<input class="list-input sku-input" data-edit-lightsource-item data-field="postal_code" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.postal_code || "")}" aria-label="Postal code for ${escapeHtml(request.order_number)}">`,
            "Email": `<input class="list-input sku-input" data-edit-lightsource-item data-field="email" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.email || "")}" aria-label="Email for ${escapeHtml(request.order_number)}">`,
            "Phone": `<input class="list-input sku-input" data-edit-lightsource-item data-field="phone" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(request.phone || "")}" aria-label="Phone for ${escapeHtml(request.order_number)}">`,
            "SKU": `<input class="list-input sku-input" data-edit-lightsource-item data-field="sku" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(item.sku || "")}" aria-label="SKU for ${escapeHtml(request.order_number)}">`,
            "Qty": `<input class="list-input qty-input" data-edit-lightsource-item data-field="qty" data-request-index="${requestIndex}" data-item-index="${itemIndex}" value="${escapeHtml(item.qty || "1")}" inputmode="numeric" aria-label="Quantity for ${escapeHtml(item.sku)}">`,
            "Remove": `<button class="danger" type="button" data-remove-lightsource-item data-request-index="${requestIndex}" data-item-index="${itemIndex}">Remove</button>`,
          });
        });
      });
      lightsourceListEl.className = "preview";
      lightsourceListEl.innerHTML = htmlTable(rows);
    }

    function saveLightsourceItemEdit(input) {
      const requestIndex = Number(input.dataset.requestIndex);
      const itemIndex = Number(input.dataset.itemIndex);
      const field = input.dataset.field;
      const request = lightsourceRequests[requestIndex];
      const item = request?.items?.[itemIndex];
      if (!request || !item) return;
      let value = input.value.trim();
      if (field === "order_number") {
        request.order_number = value;
      } else if (["company", "address_line_1", "address_line_2", "city", "state", "postal_code", "country", "email", "phone"].includes(field)) {
        request[field] = value;
      } else if (field === "recipient") {
        request.recipient = value;
        const parts = value.split(/\s+/).filter(Boolean);
        request.first_name = parts.length ? parts.slice(0, -1).join(" ") || parts[0] : "";
        request.last_name = parts.length > 1 ? parts[parts.length - 1] : "";
      } else if (field === "sku") {
        value = value || item.sku;
        item.sku = value;
      } else if (field === "qty") {
        value = value || "1";
        item.qty = value;
      }
      input.value = value;
      lightsourceResultSection.classList.add("hidden");
      lightsourceStatusEl.textContent = `Saved ${fieldLabel(field)} for ${item.sku}.`;
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

    function renderBulkInboundResult(data) {
      const preview = data.preview || [];
      const reportPreview = data.report_preview || [];
      const sources = data.sources || [];
      bulkInboundResultEl.innerHTML = `
        <div class="success">
          <strong>${data.row_count} bulk inbound upload row${data.row_count === 1 ? "" : "s"} created.</strong>
          <div class="row">
            <a class="download" href="${data.download_url}">Download Bulk Inbound CSV</a>
            <a class="download" href="${data.report_url}">Download Review Report</a>
          </div>
        </div>
        ${data.review_count ? `
          <div class="notice" style="margin-top: 12px;">
            <strong>${data.review_count} row${data.review_count === 1 ? "" : "s"} need review.</strong>
            The upload CSV keeps the required template columns, and the review report shows what was inferred or missing.
          </div>
        ` : ""}
        ${sources.length ? `
          <details style="margin-top: 18px;">
            <summary><strong>Detected Fields</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(sources.map(source => ({
                "Source File": source.filename,
                "Rows Found": source.row_count,
                "Detected": Object.keys(source.detected || {}).join(", "),
              })))}
            </div>
          </details>
        ` : ""}
        ${reportPreview.length ? `
          <details style="margin-top: 18px;">
            <summary><strong>Review Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(reportPreview)}
            </div>
          </details>
        ` : ""}
        ${preview.length ? `
          <details style="margin-top: 18px;">
            <summary><strong>Bulk Inbound CSV Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(preview)}
            </div>
          </details>
        ` : ""}
      `;
      bulkInboundResultSection.classList.remove("hidden");
    }

    function renderInboundLabelsResult(data) {
      const preview = data.preview || [];
      inboundLabelsResultEl.innerHTML = `
        <div class="success">
          <strong>${data.label_count} printable 4x6 label${data.label_count === 1 ? "" : "s"} created.</strong>
          <div class="row">
            <a class="download" href="${data.download_url}" target="_blank" rel="noreferrer">Open / Print Labels</a>
            <a class="download" href="${data.report_url}">Download Review Report</a>
          </div>
          <div class="subtle">${data.single_count} single-SKU carton${data.single_count === 1 ? "" : "s"} and ${data.mixed_count} mixed-SKU carton${data.mixed_count === 1 ? "" : "s"}.</div>
        </div>
        ${preview.length ? `
          <details style="margin-top: 18px;" open>
            <summary><strong>Label Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(preview)}
            </div>
          </details>
        ` : ""}
      `;
      inboundLabelsResultSection.classList.remove("hidden");
    }

    const designerFields = [
      ["b3_inbound", "B3 Inbound"],
      ["company_name", "Company Name"],
      ["company_id", "Company ID"],
      ["shipment", "Inbound ID"],
      ["carton", "Carton ID"],
      ["tracking", "Tracking"],
      ["po", "PO / Ref"],
      ["vendor", "Vendor"],
      ["carton_type", "Carton Type"],
      ["inbound_type", "Inbound Type"],
      ["carton_sequence", "Carton / Pallet Count"],
      ["sku", "SKU"],
      ["qty", "Qty"],
      ["lot", "LOT ID"],
      ["detail", "LOT ID / Detail"],
      ["product_name", "Product Name"],
    ];
    const designerPresets = {
      blindReceive: [
        { type: "text", field: "b3_inbound", title: "", x: 0.3, y: 0.25, w: 5.4, h: 0.7, size: 32 },
        { type: "text", field: "company_name", title: "Company Name", x: 0.3, y: 1.35, w: 5.4, h: 0.85, size: 30 },
        { type: "text", field: "company_id", title: "Company ID", x: 0.3, y: 2.65, w: 5.4, h: 0.75, size: 30 },
      ],
      systemReceive: [
        { type: "text", field: "b3_inbound", title: "", x: 0.18, y: 0.12, w: 2.25, h: 0.45, size: 22 },
        { type: "text", field: "inbound_type", title: "Inbound Type", x: 2.65, y: 0.12, w: 1.15, h: 0.45, size: 22 },
        { type: "text", field: "company_name", title: "Company Name", x: 0.18, y: 0.7, w: 2.25, h: 0.45, size: 14 },
        { type: "text", field: "company_id", title: "Company ID", x: 2.48, y: 0.7, w: 1.34, h: 0.45, size: 12 },
        { type: "text", field: "shipment", title: "Inbound Shipment ID", x: 0.18, y: 1.28, w: 3.64, h: 0.42, size: 17 },
        { type: "barcode", field: "shipment", title: "Scan Inbound Shipment ID", x: 0.25, y: 1.82, w: 3.5, h: 0.72, size: 8 },
        { type: "table", field: "sku", title: "SKU", x: 0.18, y: 2.78, w: 3.64, h: 2.15, size: 9 },
        { type: "text", field: "carton_sequence", title: "Cartons / Pallets", x: 0.18, y: 5.25, w: 3.64, h: 0.42, size: 15 },
      ],
      inbound: [
        { type: "text", field: "carton_type", title: "Label Type", x: 0.18, y: 0.15, w: 2.0, h: 0.32, size: 18 },
        { type: "text", field: "carton", title: "Carton", x: 2.55, y: 0.16, w: 1.25, h: 0.3, size: 12 },
        { type: "text", field: "shipment", title: "Inbound ID", x: 0.18, y: 0.62, w: 3.64, h: 0.34, size: 16 },
        { type: "barcode", field: "shipment", title: "Scan Inbound ID", x: 0.25, y: 1.02, w: 3.5, h: 0.64, size: 8 },
        { type: "table", field: "sku", title: "Items", x: 0.18, y: 1.82, w: 3.64, h: 2.1, size: 8 },
        { type: "barcode", field: "lot", fallback: "detail", title: "Scan LOT ID", x: 0.25, y: 4.18, w: 3.5, h: 0.64, size: 8 },
        { type: "text", field: "po", title: "PO / Ref", x: 0.18, y: 5.15, w: 1.75, h: 0.32, size: 9 },
        { type: "text", field: "tracking", title: "Tracking", x: 2.0, y: 5.15, w: 1.82, h: 0.32, size: 9 },
      ],
      lot: [
        { type: "text", field: "lot", fallback: "detail", title: "LOT ID", x: 0.22, y: 0.28, w: 3.55, h: 0.85, size: 22 },
        { type: "barcode", field: "lot", fallback: "detail", title: "Scan LOT ID", x: 0.28, y: 1.32, w: 3.45, h: 0.8, size: 8 },
        { type: "text", field: "sku", title: "SKU", x: 0.25, y: 2.45, w: 2.4, h: 0.45, size: 16 },
        { type: "text", field: "qty", title: "Qty", x: 2.75, y: 2.45, w: 0.75, h: 0.45, size: 16 },
        { type: "text", field: "shipment", title: "Inbound ID", x: 0.25, y: 3.25, w: 3.4, h: 0.36, size: 11 },
      ],
      sku: [
        { type: "text", field: "sku", title: "SKU", x: 0.2, y: 0.35, w: 3.6, h: 0.75, size: 24 },
        { type: "barcode", field: "sku", title: "Scan SKU", x: 0.25, y: 1.35, w: 3.5, h: 0.85, size: 8 },
        { type: "text", field: "product_name", fallback: "detail", title: "Detail", x: 0.25, y: 2.55, w: 3.5, h: 0.7, size: 12 },
      ],
      blank: [],
    };
    const designerSample = {
      b3_inbound: "B3 Inbound",
      company_name: "Sample Company",
      company_id: "WINIT-12345",
      shipment: "INB-1001",
      carton: "C001",
      tracking: "1Z999999999",
      po: "PO-12345",
      vendor: "Sample Brand",
      carton_type: "Mixed SKU",
      inbound_type: "B",
      carton_sequence: "1 of 10 cartons/pallets",
      sku: "SKU-RED-S",
      qty: "6",
      lot: "2026060512345678901234567890",
      detail: "2026060512345678901234567890",
      product_name: "Red Shirt Small",
    };

    function initLabelDesigner() {
      labelDesignerElements = cloneDesignerElements(designerPresets.blindReceive);
      selectedLabelElementId = labelDesignerElements[0]?.id || "";
      document.querySelector("#labelPreset").addEventListener("change", () => {
        const preset = document.querySelector("#labelPreset").value;
        labelDesignerElements = cloneDesignerElements(designerPresets[preset] || []);
        selectedLabelElementId = labelDesignerElements[0]?.id || "";
        renderLabelDesigner();
      });
      document.querySelector("#labelAddText").addEventListener("click", () => addDesignerElement("text"));
      document.querySelector("#labelAddBarcode").addEventListener("click", () => addDesignerElement("barcode"));
      document.querySelector("#labelAddTable").addEventListener("click", () => addDesignerElement("table"));
      document.querySelector("#labelAddQr").addEventListener("click", () => addDesignerElement("qr"));
      document.querySelector("#labelSaveTemplate").addEventListener("click", () => {
        localStorage.setItem("returnsLabelDesignerTemplate", JSON.stringify({ elements: labelDesignerElements }));
        labelDesignerStatusEl.textContent = "Template saved in this browser.";
      });
      document.querySelector("#labelLoadTemplate").addEventListener("click", () => {
        try {
          const saved = JSON.parse(localStorage.getItem("returnsLabelDesignerTemplate") || "{}");
          if (!Array.isArray(saved.elements)) throw new Error("No saved template");
          labelDesignerElements = cloneDesignerElements(saved.elements);
          selectedLabelElementId = labelDesignerElements[0]?.id || "";
          renderLabelDesigner();
          labelDesignerStatusEl.textContent = "Saved template loaded.";
        } catch (error) {
          labelDesignerStatusEl.textContent = "No saved template found.";
        }
      });
      renderLabelDesigner();
    }

    function cloneDesignerElements(elements) {
      return elements.map(element => ({ ...element, id: element.id || `el-${Math.random().toString(16).slice(2)}` }));
    }

    function addDesignerElement(type) {
      const element = { id: `el-${Date.now()}`, type, field: type === "table" ? "sku" : "shipment", title: type === "table" ? "Items" : "Field", x: 0.35, y: 0.35, w: type === "table" ? 3.0 : type === "qr" ? 1.35 : 1.8, h: type === "table" ? 1.2 : type === "qr" ? 1.55 : 0.45, size: 10 };
      if (type === "barcode") element.title = "Scan Field";
      if (type === "qr") element.title = "QR Payload";
      labelDesignerElements.push(element);
      selectedLabelElementId = element.id;
      renderLabelDesigner();
    }

    function renderLabelDesigner() {
      renderLabelElementList();
      renderLabelElementEditor();
      renderLabelPreview();
    }

    function renderLabelElementList() {
      if (!labelDesignerElements.length) {
        labelElementListEl.innerHTML = '<div class="subtle">No elements yet.</div>';
        return;
      }
      labelElementListEl.innerHTML = labelDesignerElements.map((element, index) => `
        <div class="designer-item ${element.id === selectedLabelElementId ? "active" : ""}" data-label-element="${element.id}">
          <strong>${index + 1}. ${escapeHtml(element.title || element.type)} <span class="subtle">${escapeHtml(element.type)} / ${escapeHtml(element.field || "")}</span></strong>
          <button class="danger" type="button" data-remove-label-element="${element.id}">Remove</button>
        </div>
      `).join("");
      labelElementListEl.querySelectorAll("[data-label-element]").forEach(node => {
        node.addEventListener("click", event => {
          if (event.target.closest("[data-remove-label-element]")) return;
          selectedLabelElementId = node.dataset.labelElement;
          renderLabelDesigner();
        });
      });
      labelElementListEl.querySelectorAll("[data-remove-label-element]").forEach(button => {
        button.addEventListener("click", event => {
          event.stopPropagation();
          labelDesignerElements = labelDesignerElements.filter(element => element.id !== button.dataset.removeLabelElement);
          selectedLabelElementId = labelDesignerElements[0]?.id || "";
          renderLabelDesigner();
        });
      });
    }

    function renderLabelElementEditor() {
      const element = labelDesignerElements.find(candidate => candidate.id === selectedLabelElementId);
      if (!element) {
        labelElementEditorEl.className = "designer-editor subtle";
        labelElementEditorEl.innerHTML = "Select an element to edit it.";
        return;
      }
      const fieldOptions = designerFields.map(([value, label]) => `<option value="${value}" ${element.field === value ? "selected" : ""}>${label}</option>`).join("");
      const fallbackOptions = ['<option value="">None</option>', ...designerFields.map(([value, label]) => `<option value="${value}" ${element.fallback === value ? "selected" : ""}>${label}</option>`)].join("");
      labelElementEditorEl.className = "designer-editor";
      labelElementEditorEl.innerHTML = `
        <label>Type<select data-edit-designer="type"><option value="text">Text</option><option value="barcode">Code 128 Barcode</option><option value="table">Item Table</option><option value="qr">QR Code</option></select></label>
        <label>Field<select data-edit-designer="field">${fieldOptions}</select></label>
        <label>Fallback<select data-edit-designer="fallback">${fallbackOptions}</select></label>
        <label>Title<input data-edit-designer="title" value="${escapeHtml(element.title || "")}"></label>
        <label>X<input type="number" step="0.05" data-edit-designer="x" value="${element.x}"></label>
        <label>Y<input type="number" step="0.05" data-edit-designer="y" value="${element.y}"></label>
        <label>Width<input type="number" step="0.05" data-edit-designer="w" value="${element.w}"></label>
        <label>Height<input type="number" step="0.05" data-edit-designer="h" value="${element.h}"></label>
        <label>Font Size<input type="number" step="1" data-edit-designer="size" value="${element.size || 10}"></label>
      `;
      labelElementEditorEl.querySelector('[data-edit-designer="type"]').value = element.type || "text";
      labelElementEditorEl.querySelectorAll("[data-edit-designer]").forEach(input => {
        input.addEventListener("input", () => updateDesignerElement(input));
        input.addEventListener("change", () => updateDesignerElement(input));
      });
    }

    function updateDesignerElement(input) {
      const element = labelDesignerElements.find(candidate => candidate.id === selectedLabelElementId);
      if (!element) return;
      const key = input.dataset.editDesigner;
      const numeric = new Set(["x", "y", "w", "h", "size"]);
      element[key] = numeric.has(key) ? Number(input.value || 0) : input.value;
      renderLabelElementList();
      renderLabelPreview();
    }

    function sampleDesignerValue(element) {
      return designerSample[element.field] || (element.fallback ? designerSample[element.fallback] : "") || "";
    }

    function designerPageSize() {
      return document.querySelector("#labelPreset").value === "blindReceive"
        ? { width: 6, height: 4 }
        : { width: 4, height: 6 };
    }

    function renderLabelPreview() {
      const page = designerPageSize();
      labelPreviewCanvasEl.classList.toggle("landscape", page.width > page.height);
      const canvasWidth = labelPreviewCanvasEl.clientWidth || 384;
      const canvasHeight = labelPreviewCanvasEl.clientHeight || 576;
      const scaleX = canvasWidth / page.width;
      const scaleY = canvasHeight / page.height;
      labelPreviewCanvasEl.innerHTML = labelDesignerElements.map(element => {
        const left = Number(element.x || 0) * scaleX;
        const top = Number(element.y || 0) * scaleY;
        const width = Number(element.w || 1) * scaleX;
        const height = Number(element.h || .4) * scaleY;
        const style = `left:${left}px;top:${top}px;width:${width}px;height:${height}px;font-size:${Math.max(8, Number(element.size || 10))}px;`;
        const active = element.id === selectedLabelElementId ? "active" : "";
        const controls = active ? `<button class="preview-delete" type="button" data-delete-preview-element="${element.id}" aria-label="Remove element">x</button>${["nw","n","ne","e","se","s","sw","w"].map(handle => `<span class="resize-handle ${handle}" data-resize-handle="${handle}"></span>`).join("")}` : "";
        const title = escapeHtml(Object.prototype.hasOwnProperty.call(element, "title") ? element.title : element.type);
        const value = escapeHtml(sampleDesignerValue(element));
        if (element.type === "barcode") {
          return `<div class="preview-el preview-barcode ${active}" data-preview-element="${element.id}" style="${style}">${controls}<span>${title}</span><div class="preview-bars"></div><strong>${value}</strong></div>`;
        }
        if (element.type === "table") {
          return `<div class="preview-el preview-table ${active}" data-preview-element="${element.id}" style="${style}">${controls}<div class="preview-table-clip"><table><thead><tr><th>SKU x Qty</th></tr></thead><tbody><tr><td>SKU-RED-S x 6</td></tr><tr><td>SKU-BLUE-M x 4</td></tr></tbody></table></div></div>`;
        }
        if (element.type === "qr") {
          return `<div class="preview-el preview-qr ${active}" data-preview-element="${element.id}" style="${style}">${controls}<span>${title}</span><strong>${value}</strong></div>`;
        }
        return `<div class="preview-el ${active}" data-preview-element="${element.id}" style="${style}">${controls}<span>${title}</span><strong>${value}</strong></div>`;
      }).join("");
      labelPreviewCanvasEl.querySelectorAll("[data-delete-preview-element]").forEach(button => {
        button.addEventListener("pointerdown", event => {
          event.preventDefault();
          event.stopPropagation();
        });
        button.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation();
          labelDesignerElements = labelDesignerElements.filter(element => element.id !== button.dataset.deletePreviewElement);
          selectedLabelElementId = labelDesignerElements[0]?.id || "";
          renderLabelDesigner();
        });
      });
      labelPreviewCanvasEl.querySelectorAll("[data-preview-element]").forEach(node => {
        node.addEventListener("click", () => {
          selectedLabelElementId = node.dataset.previewElement;
          renderLabelDesigner();
        });
        node.addEventListener("pointerdown", event => startDesignerDrag(event, node));
      });
    }

    function startDesignerDrag(event, node) {
      const element = labelDesignerElements.find(candidate => candidate.id === node.dataset.previewElement);
      if (!element) return;
      event.preventDefault();
      event.stopPropagation();
      selectedLabelElementId = element.id;
      const rect = labelPreviewCanvasEl.getBoundingClientRect();
      const startX = event.clientX;
      const startY = event.clientY;
      const originX = Number(element.x || 0);
      const originY = Number(element.y || 0);
      const originW = Number(element.w || 1);
      const originH = Number(element.h || .4);
      const handle = event.target.dataset.resizeHandle || "";
      const page = designerPageSize();
      const scaleX = rect.width / page.width;
      const scaleY = rect.height / page.height;
      node.setPointerCapture?.(event.pointerId);

      function onMove(moveEvent) {
        const dx = (moveEvent.clientX - startX) / scaleX;
        const dy = (moveEvent.clientY - startY) / scaleY;
        let guides = [];
        if (handle) {
          const resized = resizeDesignerElement(element, handle, originX, originY, originW, originH, dx, dy);
          element.x = resized.x;
          element.y = resized.y;
          element.w = resized.w;
          element.h = resized.h;
          guides = resized.guides;
        } else {
          const maxX = Math.max(0, page.width - Number(element.w || 1));
          const maxY = Math.max(0, page.height - Number(element.h || .4));
          const snapped = snapDesignerPosition(element, originX + dx, originY + dy, maxX, maxY);
          element.x = snapped.x;
          element.y = snapped.y;
          guides = snapped.guides;
        }
        renderLabelPreview();
        renderSnapGuides(guides);
        renderLabelElementList();
        renderLabelElementEditor();
      }

      function onUp(upEvent) {
        node.releasePointerCapture?.(upEvent.pointerId);
        clearSnapGuides();
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      }

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp, { once: true });
    }

    function resizeDesignerElement(element, handle, originX, originY, originW, originH, dx, dy) {
      const page = designerPageSize();
      const minW = 0.25;
      const minH = 0.2;
      let x = originX;
      let y = originY;
      let w = originW;
      let h = originH;
      if (handle.includes("e")) w = originW + dx;
      if (handle.includes("s")) h = originH + dy;
      if (handle.includes("w")) {
        x = originX + dx;
        w = originW - dx;
      }
      if (handle.includes("n")) {
        y = originY + dy;
        h = originH - dy;
      }
      if (w < minW) {
        if (handle.includes("w")) x -= minW - w;
        w = minW;
      }
      if (h < minH) {
        if (handle.includes("n")) y -= minH - h;
        h = minH;
      }
      x = Math.max(0, Math.min(page.width - minW, x));
      y = Math.max(0, Math.min(page.height - minH, y));
      w = Math.max(minW, Math.min(page.width - x, w));
      h = Math.max(minH, Math.min(page.height - y, h));
      const grid = 0.05;
      x = Math.round(x / grid) * grid;
      y = Math.round(y / grid) * grid;
      w = Math.round(w / grid) * grid;
      h = Math.round(h / grid) * grid;
      const probe = { ...element, x, y, w, h };
      const snapped = snapDesignerPosition(probe, x, y, Math.max(0, page.width - w), Math.max(0, page.height - h));
      return {
        x: snapped.x,
        y: snapped.y,
        w: Number(w.toFixed(2)),
        h: Number(h.toFixed(2)),
        guides: snapped.guides,
      };
    }

    function snapDesignerPosition(element, rawX, rawY, maxX, maxY) {
      const page = designerPageSize();
      const grid = 0.05;
      const threshold = 0.04;
      const width = Number(element.w || 1);
      const height = Number(element.h || .4);
      let x = Math.round(rawX / grid) * grid;
      let y = Math.round(rawY / grid) * grid;
      const guides = [];
      const xTargets = [
        { value: 0, kind: "vertical" },
        { value: page.width / 2, kind: "vertical" },
        { value: page.width, kind: "vertical" },
      ];
      const yTargets = [
        { value: 0, kind: "horizontal" },
        { value: page.height / 2, kind: "horizontal" },
        { value: page.height, kind: "horizontal" },
      ];
      labelDesignerElements.forEach(other => {
        if (other.id === element.id) return;
        const ox = Number(other.x || 0);
        const oy = Number(other.y || 0);
        const ow = Number(other.w || 1);
        const oh = Number(other.h || .4);
        xTargets.push({ value: ox, kind: "vertical" }, { value: ox + ow / 2, kind: "vertical" }, { value: ox + ow, kind: "vertical" });
        yTargets.push({ value: oy, kind: "horizontal" }, { value: oy + oh / 2, kind: "horizontal" }, { value: oy + oh, kind: "horizontal" });
      });
      const xPoints = [
        { value: x, offset: 0 },
        { value: x + width / 2, offset: width / 2 },
        { value: x + width, offset: width },
      ];
      const yPoints = [
        { value: y, offset: 0 },
        { value: y + height / 2, offset: height / 2 },
        { value: y + height, offset: height },
      ];
      for (const point of xPoints) {
        const target = xTargets.find(candidate => Math.abs(candidate.value - point.value) <= threshold);
        if (target) {
          x = target.value - point.offset;
          guides.push(target);
          break;
        }
      }
      for (const point of yPoints) {
        const target = yTargets.find(candidate => Math.abs(candidate.value - point.value) <= threshold);
        if (target) {
          y = target.value - point.offset;
          guides.push(target);
          break;
        }
      }
      return {
        x: Math.max(0, Math.min(maxX, Number(x.toFixed(2)))),
        y: Math.max(0, Math.min(maxY, Number(y.toFixed(2)))),
        guides,
      };
    }

    function renderSnapGuides(guides) {
      clearSnapGuides();
      const page = designerPageSize();
      const scaleX = (labelPreviewCanvasEl.clientWidth || 384) / page.width;
      const scaleY = (labelPreviewCanvasEl.clientHeight || 576) / page.height;
      guides.forEach(guide => {
        const node = document.createElement("div");
        node.className = `snap-guide ${guide.kind}`;
        if (guide.kind === "vertical") {
          node.style.left = `${guide.value * scaleX}px`;
        } else {
          node.style.top = `${guide.value * scaleY}px`;
        }
        labelPreviewCanvasEl.appendChild(node);
      });
    }

    function clearSnapGuides() {
      labelPreviewCanvasEl.querySelectorAll(".snap-guide").forEach(node => node.remove());
    }

    function renderLabelDesignerResult(data) {
      const preview = data.preview || [];
      labelDesignerResultEl.innerHTML = `
        <div class="success">
          <strong>${data.label_count} custom label${data.label_count === 1 ? "" : "s"} created.</strong>
          <div class="row">
            <a class="download" href="${data.download_url}" target="_blank" rel="noreferrer">Open / Print Custom Labels</a>
            <a class="download" href="${data.report_url}">Download Review Report</a>
          </div>
        </div>
        ${preview.length ? `
          <details style="margin-top: 18px;" open>
            <summary><strong>Custom Label Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(preview)}
            </div>
          </details>
        ` : ""}
      `;
      labelDesignerResultSection.classList.remove("hidden");
    }

    function renderProductVariantsResult(data) {
      const preview = data.preview || [];
      const reportPreview = data.report_preview || [];
      productVariantsResultEl.innerHTML = `
        <div class="success">
          <strong>${data.row_count} product variant row${data.row_count === 1 ? "" : "s"} created.</strong>
          <div class="row">
            <a class="download" href="${data.download_url}">Download Product Variants CSV</a>
            <a class="download" href="${data.report_url}">Download Review Report</a>
          </div>
        </div>
        ${data.review_count ? `
          <div class="notice" style="margin-top: 12px;">
            <strong>${data.review_count} row${data.review_count === 1 ? "" : "s"} need review.</strong>
            Check the report for missing required product setup fields.
          </div>
        ` : ""}
        ${reportPreview.length ? `
          <details style="margin-top: 18px;">
            <summary><strong>Review Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(reportPreview)}
            </div>
          </details>
        ` : ""}
        ${preview.length ? `
          <details style="margin-top: 18px;">
            <summary><strong>Product Variants CSV Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(preview)}
            </div>
          </details>
        ` : ""}
      `;
      productVariantsResultSection.classList.remove("hidden");
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
          <details class="preview-panel">
            <summary><strong>Outbound Report Preview</strong></summary>
            <div class="table-wrap">
              ${simpleTable(reportPreview)}
            </div>
          </details>
        ` : ""}
        ${preview.length ? `
          <details class="preview-panel" open>
            <summary><strong>Soapbox CSV Preview</strong></summary>
            <div class="table-wrap">
              ${simpleTable(preview)}
            </div>
          </details>
        ` : ""}
      `;
      outboundResultSection.classList.remove("hidden");
    }

    function renderLightsourceResult(data) {
      const reportPreview = data.report_preview || [];
      const preview = data.preview || [];
      const carrierPreview = data.carrier_preview || [];
      lightsourceResultEl.innerHTML = `
        <div class="success">
          <strong>${data.row_count} Lightsource item rows created.</strong>
          <div class="row">
            <a class="download" href="${data.download_url}">Download SB Import CSV</a>
            ${data.carrier_download_url ? `<a class="download" href="${data.carrier_download_url}">Download ${escapeHtml(data.carrier_label)} Import CSV</a>` : ""}
          </div>
        </div>
        ${reportPreview.length ? `
          <details style="margin-top: 14px;">
            <summary><strong>Lightsource Report Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(reportPreview)}
            </div>
          </details>
        ` : ""}
        ${preview.length ? `
          <details open style="margin-top: 14px;">
            <summary><strong>SB Import Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(preview)}
            </div>
          </details>
        ` : ""}
        ${carrierPreview.length ? `
          <details open style="margin-top: 14px;">
            <summary><strong>${escapeHtml(data.carrier_label)} Import Preview</strong></summary>
            <div class="preview" style="margin-top: 8px; border: 1px solid var(--line); border-radius: 8px;">
              ${simpleTable(carrierPreview)}
            </div>
          </details>
        ` : ""}
      `;
      lightsourceResultSection.classList.remove("hidden");
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

    function htmlTable(rows) {
      if (!rows.length) return "";
      const columns = Object.keys(rows[0]);
      return `
        <table>
          <thead><tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.map(row => `<tr>${columns.map(column => `<td>${row[column] || ""}</td>`).join("")}</tr>`).join("")}
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

    initLabelDesigner();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    try:
        port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8776"))
        address = ("127.0.0.1", port)
        url = f"http://{address[0]}:{address[1]}/"
        if sys.stdout:
            print(f"Shipment CSV Builder running at {url}")
        if os.environ.get("SHIPMENT_CSV_OPEN_BROWSER", "1") != "0":
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        ThreadingHTTPServer(address, ShipmentHandler).serve_forever()
    except Exception as exc:
        with (BASE_DIR / "startup_error.log").open("w", encoding="utf-8") as handle:
            handle.write(f"{type(exc).__name__}: {exc}\n")
        raise
