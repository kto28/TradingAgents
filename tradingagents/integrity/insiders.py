"""SEC ownership XML parsing, preserving codes, footnotes and ownership scopes."""

from datetime import date

from defusedxml import ElementTree as ET
from pydantic import BaseModel, Field


class Transaction(BaseModel):
    owner: str
    form: str
    filed: date
    transaction_date: date | None
    code: str
    category: str
    shares: float | None
    price: float | None
    price_currency: str | None = None
    acquired_disposed: str
    ownership: str
    ownership_nature: str
    post_shares: float | None
    planned_10b5_1: bool | None
    derivative: bool
    footnotes: list[str]
    source_url: str


class OwnershipFiling(BaseModel):
    form: str
    owner: str
    filed: date
    amendment: bool
    original_filing_date: str | None
    filing_10b5_1_checkbox: bool | None = None
    transactions: list[Transaction] = Field(default_factory=list)
    holdings: list[dict] = Field(default_factory=list)
    proposed_disposals: list[dict] = Field(default_factory=list)
    source_url: str
    limitations: list[str] = Field(default_factory=lambda: [
        "Post-transaction positions refer to the disclosed ownership bucket, not all beneficial ownership.",
        "Amendments must be reconciled with originals, not summed as new transactions.",
        "No bullish/bearish inference is made from transaction codes alone.",
    ])

    def liquidation_claim_supported(self) -> bool:
        # Even a zero bucket is not evidence of complete liquidation.
        return False


def parse_ownership(raw: bytes, filed: date, source_url: str, currency: str | None = None) -> OwnershipFiling:
    root = ET.fromstring(raw)
    for node in root.iter():
        node.tag = node.tag.split("}")[-1]

    def text(node, path, default=""):
        return node.findtext(path, default=default).strip()

    def number(node, path):
        value = text(node, path)
        return float(value.replace(",", "")) if value else None

    form = text(root, "documentType") or text(root, ".//submissionType")
    owner = text(root, ".//rptOwnerName") or text(root, ".//nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold")
    result = OwnershipFiling(form=form, owner=owner, filed=filed,
                             amendment=form.endswith("/A"), original_filing_date=text(root, "dateOfOriginalSubmission") or None,
                             source_url=source_url)
    if form.startswith("144"):
        for node in root.findall(".//securitiesInformation"):
            result.proposed_disposals.append({
                "proposed_shares": number(node, "noOfUnitsSold"),
                "proposed_market_value": number(node, "aggregateMarketValue"),
                "approximate_sale_date": text(node, "approxSaleDate"),
                "completed": False,
            })
        result.limitations.append("Form 144 is notice of proposed disposal, not proof of a completed sale.")
        return result
    if form not in {"4", "4/A"}:
        raise ValueError("Expected Form 4, 4/A or 144")
    notes = {n.attrib.get("id"): "".join(n.itertext()) for n in root.findall(".//footnote")}
    flag = text(root, ".//aff10b5One")
    result.filing_10b5_1_checkbox = True if flag in {"1", "true"} else False if flag in {"0", "false"} else None
    for node in [*root.findall(".//nonDerivativeTransaction"), *root.findall(".//derivativeTransaction")]:
        code = text(node, "transactionCoding/transactionCode")
        refs = [notes.get(n.attrib.get("id"), "") for n in node.findall(".//footnoteId")]
        joined = " ".join(refs).lower()
        category = {"P": "OPEN_MARKET_OR_PRIVATE_PURCHASE", "S": "OPEN_MARKET_OR_PRIVATE_SALE",
                    "F": "TAX_OR_EXERCISE_WITHHOLDING", "A": "AWARD", "M": "EXERCISE_OR_CONVERSION",
                    "G": "GIFT", "J": "OTHER_REQUIRES_FOOTNOTE"}.get(code, "UNCLASSIFIED")
        if code in {"G", "J"} and "trust" in joined and any(x in joined for x in ("transfer", "annuity", "termination")):
            category = "TRUST_TRANSFER"
        if code == "F" and "tax" in joined:
            category = "TAX_WITHHOLDING"
        # A checked filing box means at least one transaction was planned, not all.
        planned = True if "10b5-1" in joined else False if flag in {"0", "false"} else None
        if code not in {"S", "P"}:
            planned = None
        txdate = text(node, "transactionDate/value")
        result.transactions.append(Transaction(
            owner=owner, form=form, filed=filed, transaction_date=date.fromisoformat(txdate) if txdate else None,
            code=code, category=category, shares=number(node, "transactionAmounts/transactionShares/value"),
            price=number(node, "transactionAmounts/transactionPricePerShare/value"),
            price_currency=currency,
            acquired_disposed=text(node, "transactionAmounts/transactionAcquiredDisposedCode/value"),
            ownership=text(node, "ownershipNature/directOrIndirectOwnership/value"),
            ownership_nature=text(node, "ownershipNature/natureOfOwnership/value"),
            post_shares=number(node, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"),
            planned_10b5_1=planned, derivative=node.tag == "derivativeTransaction",
            footnotes=refs, source_url=source_url,
        ))
    for node in root.findall(".//nonDerivativeHolding"):
        result.holdings.append({
            "shares": number(node, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"),
            "ownership": text(node, "ownershipNature/directOrIndirectOwnership/value"),
            "nature": text(node, "ownershipNature/natureOfOwnership/value"),
        })
    return result
