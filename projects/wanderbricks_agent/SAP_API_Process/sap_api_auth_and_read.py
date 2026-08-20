# Databricks notebook source
# MAGIC %md
# MAGIC # sap_api_auth_and_read
# MAGIC Initial discovery notebook for the SAP S/4HANA read APIs reached through SAP CPI
# MAGIC (collection `DATABRICKS_TO_S4__CPI_NONPROD`). This is **not** a production ETL
# MAGIC pipeline — it authenticates, calls each service's basic GET endpoint, and shows
# MAGIC both the raw response and a best-effort projection onto the business fields from
# MAGIC the "SAP Fields – Real Time Data" reference picture, so the real field mapping can
# MAGIC be confirmed and refined in a later iteration.
# MAGIC
# MAGIC Covers collection folders `01`–`05` (PIR, Source List, Vendor BP, Product Master,
# MAGIC Purchase Order). Folder `06` is skipped — the collection itself marks it "NOT WORKING".
# MAGIC
# MAGIC ## Before running
# MAGIC This notebook reads the CPI OAuth client credentials from a Databricks secret
# MAGIC scope. Create it and populate it first:
# MAGIC ```
# MAGIC databricks secrets create-scope sap_cpi_nonprod
# MAGIC databricks secrets put-secret sap_cpi_nonprod cpi_client_id
# MAGIC databricks secrets put-secret sap_cpi_nonprod cpi_client_secret
# MAGIC ```
# MAGIC Scope/key names are configurable below if you use different ones.

# COMMAND ----------

import requests
from requests.auth import HTTPBasicAuth
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sap_api_auth_and_read")

BASE_URL = "https://l700767-iflmap.hcisbp.eu2.hana.ondemand.com/http/odatarequest2sap"
TOKEN_URL = "https://oauthasservices-n4avd0ima5.eu2.hana.ondemand.com/oauth2/api/v1/token?grant_type=client_credentials"
SYSTEM_ID = "S4D120"
SOURCE = "DATABRICKS"

# Placeholders — create this scope/these keys yourself (see markdown cell above)
SECRET_SCOPE = "sap_cpi_nonprod"
SECRET_KEY_CLIENT_ID = "cpi_client_id"
SECRET_KEY_CLIENT_SECRET = "cpi_client_secret"

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
    try:
        client_id = dbutils.secrets.get(scope=SECRET_SCOPE, key=SECRET_KEY_CLIENT_ID)
        client_secret = dbutils.secrets.get(scope=SECRET_SCOPE, key=SECRET_KEY_CLIENT_SECRET)
    except Exception as e:
        raise RuntimeError(
            f"Could not read CPI credentials from secret scope '{SECRET_SCOPE}' "
            f"(keys '{SECRET_KEY_CLIENT_ID}', '{SECRET_KEY_CLIENT_SECRET}'). "
            f"Create the scope and secrets first — see the markdown cell above. Original error: {e}"
        )

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
    desired_fields=["PurchasingInfoRecord", "Supplier", "Material"],
    label="01 PIR (root)",
)
display(pir_root_fields)

# COMMAND ----------

# Raw — org/plant sub-entity, all columns (needed for Valid To Date / Currency / UoM / Purch. Org)
pir_orgplant_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_INFORECORD_PROCESS_SRV/A_PurgInfoRecdOrgPlantData?$top=100&$format=json",
    access_token,
))
display(pir_orgplant_raw)

# COMMAND ----------

# Business fields per the picture (PurchasingOrganization, PriceValidityEndDate ~ "Valid To Date",
# Currency, PurgDocOrderQuantityUnit ~ "UoM")
pir_orgplant_fields = project_business_fields(
    pir_orgplant_raw,
    desired_fields=[
        "PurchasingInfoRecord", "PurchasingOrganization", "Plant",
        "PriceValidityEndDate", "Currency", "PurgDocOrderQuantityUnit",
    ],
    label="01 PIR (org/plant)",
)
display(pir_orgplant_fields)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 02 - Source List (ME0M) — API_PURCHASING_SOURCE_SRV
# MAGIC **Picture mapping** — Input: Material Number, Plant. Output: Material Number,
# MAGIC Plant, Valid From, Valid To, Vendor code, Purchase Organisation, Fixed supplier
# MAGIC indicator, Materials Planning.
# MAGIC
# MAGIC **Unverified**: this service has no saved `$metadata` in the collection. Field
# MAGIC names below (especially the MRP/"Materials Planning" relevance flag) are
# MAGIC best-effort guesses from standard SAP API naming and must be confirmed once run.

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
        "IsFixedSourceOfSupply", "MRPPurchasingSourceIsRlvt",
    ],
    label="02 Source List",
)
display(source_list_fields)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 03 - Vendor Master (LFA1/MKVZ) — API_BUSINESS_PARTNER
# MAGIC **Picture mapping** — Input: Vendor code, Purchase Organisation. Output: Vendor
# MAGIC code, Purchase Organisation, Currency, Vendor master status, Purchasing Group,
# MAGIC Confirmation Control.
# MAGIC
# MAGIC **Gap**: the collection's basic folders only query the root `A_Supplier` entity
# MAGIC (general data, no purchasing-org fields). `Currency`, `Purchasing Group`, and
# MAGIC `Confirmation Control` live on the purchasing-org sub-entity
# MAGIC `A_SupplierPurchasingOrg`, which isn't in the collection's basic folders — queried
# MAGIC here anyway since it's required to satisfy the picture's Output fields.
# MAGIC **Unverified**: no saved `$metadata` for either entity in the collection.

# COMMAND ----------

# Raw — root Supplier entity, all columns
vendor_root_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier?$top=100&$format=json",
    access_token,
))
display(vendor_root_raw)

# COMMAND ----------

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

vendor_purchorg_fields = project_business_fields(
    vendor_purchorg_raw,
    desired_fields=[
        "Supplier", "PurchasingOrganization", "OrderCurrency",
        "PurchasingGroup", "SupplierConfirmationControlKey", "PurchasingIsBlocked",
    ],
    label="03 Vendor Master (purchasing org)",
)
display(vendor_purchorg_fields)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 04 - Material Master (MARA, MARC) — API_PRODUCT_SRV
# MAGIC **Picture mapping** — Input: Material Number, Plant. Output: Material Number,
# MAGIC Plant, Procurement type, Plant-Specific Material Status.
# MAGIC
# MAGIC No gap here — both entities the picture needs (`A_Product` for MARA-level,
# MAGIC `A_ProductPlant` for MARC-level) are already in the collection's basic folders.

# COMMAND ----------

# Raw — A_Product (MARA-level), all columns
product_raw = extract_records(sap_get(
    "/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product?$top=100&$format=json",
    access_token,
))
display(product_raw)

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
display(product_plant_raw)

# COMMAND ----------

product_plant_fields = project_business_fields(
    product_plant_raw,
    desired_fields=["Product", "Plant", "ProcurementType", "PlantSpecProductStatus"],
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
display(po_header_raw)

# COMMAND ----------

po_header_fields = project_business_fields(
    po_header_raw,
    desired_fields=["PurchaseOrder", "Supplier", "CompanyCode", "PurchasingOrganization"],
    label="05 Open PO (header)",
)
display(po_header_fields)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC Every "fields not found" warning logged above is a business field from the
# MAGIC picture that could not be confirmed against the actual API response — treat
# MAGIC those as the punch list for the next iteration of this notebook.

# COMMAND ----------

logger.info("sap_api_auth_and_read completed. Review WARNING-level log lines above for unresolved field mappings.")
