# Returns Shipment Builder

Local browser app for building returns-related CSV imports.

## Current Workflows

- Christy inbound shipment builder from a tabbed workbook or source spreadsheets.
- Havn inbound shipment builder from pasted return-label request emails.
- Bulk inbound builder from customer pack lists, BOLs, POs, CSV/Excel files, and searchable PDFs.
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

## Build Windows Executable

Run:

```powershell
.\build_windows.ps1
```

The build creates:

- `dist\ReturnsShipmentBuilder.exe`
- `dist\ReturnsShipmentBuilder.zip`

Send users the ZIP file. They should extract it and double-click `ReturnsShipmentBuilder.exe`.
The packaged app runs without a command window; users can stop it with the **Close App** button in the browser.

## Updates

The packaged app checks the latest GitHub release on startup. To publish an update:

1. Build a new ZIP with `.\build_windows.ps1`.
2. Create a GitHub release with a higher tag, such as `v0.1.1`.
3. Attach `dist\ReturnsShipmentBuilder.zip` to the release.

Users will see an update banner the next time the app starts.
