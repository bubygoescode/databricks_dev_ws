# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
import requests
from requests.auth import HTTPBasicAuth
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sap_api_auth_and_read")

BASE_URL = "https://l700767-iflmap.hcisbp.eu2.hana.ondemand.com/http/odatarequest2sap"
TOKEN_URL = "https://oauthasservices-n4avd0ima5.eu2.hana.ondemand.com/oauth2/api/v1/token?grant_type=client_credentials"
SYSTEM_ID = "S4D120"
SOURCE = "DATABRICKS"

CPI_CLIENT_ID = "databricks_cpi_nonprod"
CPI_CLIENT_SECRET = "DaTA8r1cK$2Cp1$Test"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 00 - Authentication
# MAGIC Client-credentials OAuth token request against the CPI OAuth host (a different
# MAGIC host from `BASE_URL`). The returned bearer token is used as the `Authorization`
# MAGIC header on every subsequent GET.

# COMMAND ----------

def get_cpi_access_token():
    """Fetch a client-credentials bearer token from the CPI OAuth host.
    Fails visibly — no hardcoded fallback token.
    """
    client_id = CPI_CLIENT_ID
    client_secret = CPI_CLIENT_SECRET

    response = requests.post(
        TOKEN_URL,
        auth=HTTPBasicAuth(client_id, client_secret),
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError(f"CPI token response had no 'access_token': {response.text}")
    return token


access_token = get_cpi_access_token()
logger.info("CPI access token acquired.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Shared helpers

# COMMAND ----------

import re
import pandas as pd
from datetime import datetime, timezone

# SAP S/4HANA max-date sentinel (ms since epoch for 9999-12-31)
_SAP_MAX_DATE_MS = 253402214400000


def sap_headers(token):
    return {
        "Accept": "application/json",
        "source": SOURCE,
        "systemid": SYSTEM_ID,
        "Authorization": f"Bearer {token}",
    }


def sap_get(path, token):
    """GET against BASE_URL + path. Raises on non-2xx (fail visibly)."""
    url = f"{BASE_URL}{path}"
    response = requests.get(url, headers=sap_headers(token))
    response.raise_for_status()
    return response.json()


def extract_records(payload):
    """Normalize OData V2 ({'d': {'results': [...]}}) and V4 ({'value': [...]}) envelopes."""
    if isinstance(payload, dict):
        if "d" in payload and isinstance(payload["d"], dict) and "results" in payload["d"]:
            return payload["d"]["results"]
        if "value" in payload:
            return payload["value"]
        return [payload]
    if isinstance(payload, list):
        return payload
    return []


def project_business_fields(records, desired_fields, label):
    """Keep only desired_fields from each record. Logs a warning listing any
    desired_fields absent from the first record, so unverified field-name
    guesses surface immediately instead of failing silently.
    """
    if not records:
        logger.warning(f"{label}: no records returned, nothing to project")
        return []

    missing = [f for f in desired_fields if f not in records[0]]
    if missing:
        logger.warning(f"{label}: fields not found in response, verify against $metadata: {missing}")

    present = [f for f in desired_fields if f not in missing]
    return [{f: r.get(f) for f in present} for r in records]


def parse_sap_odata_date(value):
    """Parse SAP OData V2 date format '/Date(milliseconds)/' to Python date.
    SAP CPI returns dates as /Date(<ms-since-epoch>)/ in JSON responses.
    The SAP max-date 9999-12-31 (meaning 'no end date') is returned as NaT
    since pandas datetime64[ns] cannot represent dates beyond ~2262.
    Returns None for null/unparseable values or the max-date sentinel.
    """
    if not value or not isinstance(value, str):
        return None
    match = re.search(r"/Date\(([-+]?\d+)\)/", value)
    if not match:
        return None
    ms = int(match.group(1))
    if ms >= _SAP_MAX_DATE_MS:
        return None  # SAP 'no end date' → NaT
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()



# COMMAND ----------

# MAGIC %md
# MAGIC ## 01 - PIR List (ME1M) — API_INFORECORD_PROCESS_SRV
# MAGIC **Picture mapping** — Input: Vendor code, Material Number, Purchase Organisation.
# MAGIC Output: PIR number, Valid To Date, Currency, UoM.
# MAGIC
# MAGIC **Gap**: the collection's "Read - Basic" folder only queries the root
# MAGIC `A_PurchasingInfoRecord` entity, which has `PurchasingInfoRecord` (PIR number),
# MAGIC `Supplier` (vendor code), `Material` — but **not** `Valid To Date`, `Currency`,
# MAGIC `UoM`, or `Purchase Organisation`. Those live on the org/plant sub-entity
# MAGIC `A_PurgInfoRecdOrgPlantData`, so this notebook queries both — the second call is
# MAGIC beyond the literal Read-Basic folder but required to satisfy the picture's Output
# MAGIC fields.

# COMMAND ----------

# Raw — root entity, all columns
pir_root_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_INFORECORD_PROCESS_SRV/A_PurchasingInfoRecord?$top=100&$format=json",
    access_token,
))
display(pir_root_raw)

# COMMAND ----------

# Business fields available on the root entity
pir_root_fields = project_business_fields(
    pir_root_raw,
    desired_fields=["PurchasingInfoRecord", "AvailabilityEndDate", "BaseUnit"],
    label="01 PIR (root)",
)

## NOTES TO ER: Is AvailabilityEndDate same as Valid To Date? UOM use BaseUnit?
#   Not exist field: Currency

df_pir_root = pd.DataFrame(pir_root_fields)
df_pir_root["AvailabilityEndDate"] = pd.to_datetime(
    df_pir_root["AvailabilityEndDate"].apply(parse_sap_odata_date)
)
display(df_pir_root)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 02 - Source List (ME0M) — API_PURCHASING_SOURCE_SRV
# MAGIC **Picture mapping** — Input: Material Number, Plant. Output: Material Number,
# MAGIC Plant, Valid From, Valid To, Vendor code, Purchase Organisation, Fixed supplier
# MAGIC indicator, Materials Planning.
# MAGIC

# COMMAND ----------

# Raw — all columns
source_list_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_PURCHASING_SOURCE_SRV/A_PurchasingSource?$top=100&$format=json",
    access_token,
))
display(source_list_raw)

# COMMAND ----------

source_list_fields = project_business_fields(
    source_list_raw,
    desired_fields=[
        "Material", "Plant", "Supplier", "PurchasingOrganization",
        "ValidityStartDate", "ValidityEndDate",
        "SourceOfSupplyIsFixed",
    ],
    label="02 Source List",
)

## NOTES TO ER: Not exist field: Materials Planning

source_list_fields = pd.DataFrame(source_list_fields)
source_list_fields[["ValidityStartDate", "ValidityEndDate"]] = source_list_fields[["ValidityStartDate", "ValidityEndDate"]].apply(lambda col: pd.to_datetime(col.apply(parse_sap_odata_date), errors="coerce"))

display(source_list_fields)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 03 - Vendor Master (LFA1/MKVZ) — API_BUSINESS_PARTNER
# MAGIC **Picture mapping** — Input: Vendor code, Purchase Organisation. Output: Vendor
# MAGIC code, Purchase Organisation, Currency, Vendor master status, Purchasing Group,
# MAGIC Confirmation Control.
# MAGIC

# COMMAND ----------

vendor_root_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier?$top=100&$format=json",
    access_token,
))

display(pd.DataFrame(vendor_root_raw))

# COMMAND ----------

## NOTES TO ER: Field Purchase Organization seems like the API to API
#   Not exist field: Currency, Vendor Master Status, Purchasing Group, Confirmation Control​

vendor_root_fields = project_business_fields(
    vendor_root_raw,
    desired_fields=["Supplier"],
    label="03 Vendor Master (root)",
)
display(vendor_root_fields)

# COMMAND ----------

# Raw — purchasing-org sub-entity, all columns (needed for Currency / Purchasing Group / Confirmation Control)
vendor_purchorg_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_SupplierPurchasingOrg?$top=100&$format=json",
    access_token,
))
display(vendor_purchorg_raw)

# COMMAND ----------

## NOTES TO ER: Not exist field: Field Purchase Organization seems like the API to API
#   Is field Confirmation Control​ = SupplierConfirmationControlKey ?
#   Not exist field: Venfor Master Status

vendor_purchorg_fields = project_business_fields(
    vendor_purchorg_raw,
    desired_fields=[
        "Supplier", "PurchasingOrganization", "PurchaseOrderCurrency",
        "PurchasingGroup", "SupplierConfirmationControlKey",
    ],
    label="03 Vendor Master (purchasing org)",
)
display(vendor_purchorg_fields)

# COMMAND ----------

# DBTITLE 1,Vendor Master — consolidated view (root + purchasing org)

vendor_expanded_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier"
    "?$top=100&$format=json"
    "&$expand=to_SupplierPurchasingOrg",
    access_token,
))

# Flatten: explode the nested navigation property into one row per Supplier x PurchasingOrg
rows = []
for rec in vendor_expanded_raw:
    supplier = rec.get("Supplier")
    nav = rec.get("to_SupplierPurchasingOrg", {})
    children = nav.get("results", []) if isinstance(nav, dict) else []
    if children:
        for child in children:
            rows.append({
                "Supplier": supplier,
                "PurchasingOrganization": child.get("PurchasingOrganization"),
                "PurchaseOrderCurrency": child.get("PurchaseOrderCurrency"),
                "PurchasingGroup": child.get("PurchasingGroup"),
                "SupplierConfirmationControlKey": child.get("SupplierConfirmationControlKey"),
            })
    else:
        rows.append({
            "Supplier": supplier,
            "PurchasingOrganization": None,
            "PurchaseOrderCurrency": None,
            "PurchasingGroup": None,
            "SupplierConfirmationControlKey": None,
        })

df_vendor_master = pd.DataFrame(rows)
print(f"Vendors: {len(vendor_expanded_raw)} | Flattened rows: {len(df_vendor_master)}")
display(df_vendor_master)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 04 - Material Master (MARA, MARC) — API_PRODUCT_SRV
# MAGIC **Picture mapping** — Input: Material Number, Plant. Output: Material Number,
# MAGIC Plant, Procurement type, Plant-Specific Material Status.
# MAGIC
# MAGIC No gap here — both entities the picture needs (`A_Product` for MARA-level,
# MAGIC `A_ProductPlant` for MARC-level) are already in the collection's basic folders.

# COMMAND ----------

## NOTES TO ER: Not exist field: Field Purchase Organization seems like the API to API
#   Not exist field: Currency, Venfor Master Status, Purchasing Group, Confirmation Control​

product_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product?$top=100&$format=json",
    access_token,
))

display(pd.DataFrame(product_raw))

# COMMAND ----------

product_fields = project_business_fields(
    product_raw,
    desired_fields=["Product", "ProductType", "BaseUnit"],
    label="04 Material Master (A_Product)",
)
display(product_fields)

# COMMAND ----------

# Raw — A_ProductPlant (MARC-level), all columns
product_plant_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_PRODUCT_SRV/A_ProductPlant?$top=100&$format=json",
    access_token,
))

display(pd.DataFrame(product_plant_raw))

# COMMAND ----------

## NOTES TO ER: Not exist field: Plant-Specific Material Status​

product_plant_fields = project_business_fields(
    product_plant_raw,
    desired_fields=["Product", "Plant", "ProcurementType"],
    label="04 Material Master (A_ProductPlant)",
)
display(product_plant_fields)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 05 - Open PO (ME2M) — API_PURCHASEORDER_2 (OData V4)
# MAGIC **Picture mapping** — Input: Material or Part No, Plant, Vendor code. Output: PO
# MAGIC Number, Item, Material, PO Document date. Remarks call for Scope of List "ALV"
# MAGIC and Selection Parameters "WE101" — these are ME2M list-transaction filters with
# MAGIC no direct OData equivalent in what's provided.
# MAGIC
# MAGIC **Gap**: the collection only has the PO **header** GET (`PurchaseOrder` entity —
# MAGIC no `Item`, `Material`, or line-level date). Those are on an item/line entity
# MAGIC (e.g. `PurchaseOrderItem`) that isn't present anywhere in the given collection —
# MAGIC not queried here; confirm the entity name and navigation path via this service's
# MAGIC `$metadata` before adding it. Note this API is OData V4, so `extract_records`
# MAGIC reads the `value` envelope, not `d.results`.

# COMMAND ----------

# Raw — PO header, all columns
po_header_raw = extract_records(sap_get(
    "/sap/opu/odata4/sap/api_purchaseorder_2/srvd_a2x/sap/purchaseorder/0001/PurchaseOrder?$top=100&$count=true",
    access_token,
))

display(pd.DataFrame(po_header_raw))

# COMMAND ----------

po_header_fields = project_business_fields(
    po_header_raw,
    desired_fields=["PurchaseOrder", "Supplier", "CompanyCode", "PurchasingOrganization"],
    label="05 Open PO (header)",
)
display(po_header_fields)