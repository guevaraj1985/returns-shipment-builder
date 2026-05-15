# Returns Shipment Builder

Local browser app for building returns-related CSV imports.

## Current Workflows

- Christy inbound shipment builder from a tabbed workbook or source spreadsheets.
- Havn inbound shipment builder from pasted return-label request emails.
- Outbound replacement order starter from `shopify_orders_shipping_skus.csv`.

## Run Locally

```powershell
python shipment_csv_app.py 8776
```

Then open:

```text
http://localhost:8776/
```

## Notes

Generated uploads, downloads, and temporary workbook copies are written to `uploads/` and `outputs/`; those folders are intentionally ignored by git.
