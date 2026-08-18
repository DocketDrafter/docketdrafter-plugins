#!/usr/bin/env python3
"""Read, list, and search bundled federal court rules corpora."""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from corpus import ensure_corpus
from typing import Any


FRCP = "frcp"
FRAP = "frap"
FRE = "fre"
ADMIRALTY = "supplemental-admiralty"
SOCIAL_SECURITY = "supplemental-social-security"
SDNY_EDNY_LOCAL = "sdny-edny-local-rules"
SDNY_ECF = "sdny-ecf-rules"
FLSD_LOCAL = "flsd-local-rules"
FLMD_LOCAL = "flmd-local-rules"
FLND_LOCAL = "flnd-local-rules"
ILND_LOCAL = "ilnd-local-rules"
ILCD_LOCAL = "ilcd-local-rules"
ILSD_LOCAL = "ilsd-local-rules"
TXS_LOCAL = "txs-local-rules"
TXND_LOCAL = "txnd-local-rules"
TXWD_LOCAL = "txwd-local-rules"
TXED_LOCAL = "txed-local-rules"
DNJ_LOCAL = "dnj-local-rules"
AZD_LOCAL = "azd-local-rules"
AZD_ECF = "azd-ecf-rules"
PAED_CIVIL_LOCAL = "paed-local-civil-rules"
PAED_CRIMINAL_LOCAL = "paed-local-criminal-rules"
PAMD_LOCAL = "pamd-local-rules"
PAWD_LOCAL = "pawd-local-rules"

RULESET_ALIASES = {
    "frcp": FRCP,
    "main": FRCP,
    "civil": FRCP,
    "frap": FRAP,
    "appellate": FRAP,
    "fed-r-app-p": FRAP,
    "federal-rules-appellate-procedure": FRAP,
    "fre": FRE,
    "evidence": FRE,
    "fed-r-evid": FRE,
    "federal-rules-evidence": FRE,
    "admiralty": ADMIRALTY,
    "supplemental-admiralty": ADMIRALTY,
    "supplemental": ADMIRALTY,
    "supp": ADMIRALTY,
    "social-security": SOCIAL_SECURITY,
    "social": SOCIAL_SECURITY,
    "ss": SOCIAL_SECURITY,
    "sdny-edny-local-rules": SDNY_EDNY_LOCAL,
    "sdny-local": SDNY_EDNY_LOCAL,
    "edny-local": SDNY_EDNY_LOCAL,
    "local": SDNY_EDNY_LOCAL,
    "joint-local": SDNY_EDNY_LOCAL,
    "sdny-ecf-rules": SDNY_ECF,
    "sdny-ecf": SDNY_ECF,
    "ecf": SDNY_ECF,
    "flsd-local-rules": FLSD_LOCAL,
    "flsd-local": FLSD_LOCAL,
    "sd-fl-local": FLSD_LOCAL,
    "sdfla-local": FLSD_LOCAL,
    "s-d-fla-local": FLSD_LOCAL,
    "flmd-local-rules": FLMD_LOCAL,
    "flmd-local": FLMD_LOCAL,
    "md-fl-local": FLMD_LOCAL,
    "mdfla-local": FLMD_LOCAL,
    "m-d-fla-local": FLMD_LOCAL,
    "flnd-local-rules": FLND_LOCAL,
    "flnd-local": FLND_LOCAL,
    "nd-fl-local": FLND_LOCAL,
    "ndfla-local": FLND_LOCAL,
    "n-d-fla-local": FLND_LOCAL,
    "ilnd-local-rules": ILND_LOCAL,
    "ilnd-local": ILND_LOCAL,
    "nd-il-local": ILND_LOCAL,
    "ndill-local": ILND_LOCAL,
    "n-d-ill-local": ILND_LOCAL,
    "ilcd-local-rules": ILCD_LOCAL,
    "ilcd-local": ILCD_LOCAL,
    "cd-il-local": ILCD_LOCAL,
    "cdill-local": ILCD_LOCAL,
    "c-d-ill-local": ILCD_LOCAL,
    "ilsd-local-rules": ILSD_LOCAL,
    "ilsd-local": ILSD_LOCAL,
    "sd-il-local": ILSD_LOCAL,
    "sdill-local": ILSD_LOCAL,
    "s-d-ill-local": ILSD_LOCAL,
    "txs-local-rules": TXS_LOCAL,
    "txs-local": TXS_LOCAL,
    "txsd-local": TXS_LOCAL,
    "sd-tex-local": TXS_LOCAL,
    "sdtx-local": TXS_LOCAL,
    "s-d-tex-local": TXS_LOCAL,
    "txnd-local-rules": TXND_LOCAL,
    "txnd-local": TXND_LOCAL,
    "nd-tex-local": TXND_LOCAL,
    "ndtx-local": TXND_LOCAL,
    "n-d-tex-local": TXND_LOCAL,
    "txwd-local-rules": TXWD_LOCAL,
    "txwd-local": TXWD_LOCAL,
    "wd-tex-local": TXWD_LOCAL,
    "wdtx-local": TXWD_LOCAL,
    "w-d-tex-local": TXWD_LOCAL,
    "txed-local-rules": TXED_LOCAL,
    "txed-local": TXED_LOCAL,
    "ed-tex-local": TXED_LOCAL,
    "edtx-local": TXED_LOCAL,
    "e-d-tex-local": TXED_LOCAL,
    "dnj-local-rules": DNJ_LOCAL,
    "dnj-local": DNJ_LOCAL,
    "njd-local": DNJ_LOCAL,
    "d-n-j-local": DNJ_LOCAL,
    "d-nj-local": DNJ_LOCAL,
    "azd-local-rules": AZD_LOCAL,
    "azd-local": AZD_LOCAL,
    "d-ariz-local": AZD_LOCAL,
    "d-az-local": AZD_LOCAL,
    "arizona-local": AZD_LOCAL,
    "azd-ecf-rules": AZD_ECF,
    "azd-ecf": AZD_ECF,
    "d-ariz-ecf": AZD_ECF,
    "d-az-ecf": AZD_ECF,
    "arizona-ecf": AZD_ECF,
    "paed-local-civil-rules": PAED_CIVIL_LOCAL,
    "paed-civil-local": PAED_CIVIL_LOCAL,
    "ed-pa-civil-local": PAED_CIVIL_LOCAL,
    "edpa-civil-local": PAED_CIVIL_LOCAL,
    "e-d-pa-civil-local": PAED_CIVIL_LOCAL,
    "paed-local-criminal-rules": PAED_CRIMINAL_LOCAL,
    "paed-criminal-local": PAED_CRIMINAL_LOCAL,
    "ed-pa-criminal-local": PAED_CRIMINAL_LOCAL,
    "edpa-criminal-local": PAED_CRIMINAL_LOCAL,
    "e-d-pa-criminal-local": PAED_CRIMINAL_LOCAL,
    "pamd-local-rules": PAMD_LOCAL,
    "pamd-local": PAMD_LOCAL,
    "md-pa-local": PAMD_LOCAL,
    "mdpa-local": PAMD_LOCAL,
    "m-d-pa-local": PAMD_LOCAL,
    "pawd-local-rules": PAWD_LOCAL,
    "pawd-local": PAWD_LOCAL,
    "wd-pa-local": PAWD_LOCAL,
    "wdpa-local": PAWD_LOCAL,
    "w-d-pa-local": PAWD_LOCAL,
}


class LookupErrorWithDetail(SystemExit):
    pass


class RuleTextExtractor(HTMLParser):
    def __init__(self, target_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.target_id = target_id
        self.in_target_article = False
        self.in_pre = False
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "article" and attr_map.get("id") == self.target_id:
            self.in_target_article = True
            self.depth = 1
            return
        if self.in_target_article:
            self.depth += 1
            if tag == "pre":
                self.in_pre = True

    def handle_endtag(self, tag: str) -> None:
        if self.in_target_article and tag == "pre":
            self.in_pre = False
        if self.in_target_article:
            self.depth -= 1
            if self.depth <= 0:
                self.in_target_article = False

    def handle_data(self, data: str) -> None:
        if self.in_target_article and self.in_pre:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


class AllRulesExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_anchor: str | None = None
        self.in_pre = False
        self.depth = 0
        self.buf: list[str] = []
        self.results: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "article" and attr_map.get("id"):
            self.current_anchor = attr_map["id"]
            self.depth = 1
            self.buf = []
            return
        if self.current_anchor is not None:
            self.depth += 1
            if tag == "pre":
                self.in_pre = True

    def handle_endtag(self, tag: str) -> None:
        if self.current_anchor is None:
            return
        if tag == "pre":
            self.in_pre = False
        self.depth -= 1
        if self.depth <= 0:
            self.results[self.current_anchor] = "".join(self.buf)
            self.current_anchor = None
            self.buf = []

    def handle_data(self, data: str) -> None:
        if self.current_anchor is not None and self.in_pre:
            self.buf.append(data)


def default_root() -> Path:
    return ensure_corpus("federal-court-rules")


def fail(message: str) -> None:
    raise LookupErrorWithDetail(message)


def load_json(path: Path, *, purpose: str) -> Any:
    if not path.exists():
        fail(f"Missing {purpose}: {path}\nRecovery: reinstall the Federal Court Rules plugin and confirm its bundled references directory exists.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON while reading {purpose}: {path}\nJSON error: {exc}")


def normalize_alias(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace(".", " ").strip().upper())


def normalize_rule_set(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("_", "-")
    if normalized in RULESET_ALIASES:
        return RULESET_ALIASES[normalized]
    return normalized


def discover_rule_sets(root: Path) -> dict[str, dict[str, Any]]:
    master_path = root / "index.json"
    discovered: dict[str, dict[str, Any]] = {}
    if master_path.exists():
        master = load_json(master_path, purpose="master index")
        for rule_set, meta in (master.get("ruleSets") or {}).items():
            discovered[rule_set] = {
                "ruleSet": rule_set,
                "name": meta.get("name", rule_set),
                "directory": meta["directory"],
                "ruleCount": meta.get("ruleCount", 0),
            }

    for index_path in sorted(root.glob("*/index.json")):
        index = load_json(index_path, purpose=f"rule-set index at {index_path}")
        rule_set = index.get("ruleSet") or index_path.parent.name
        discovered[rule_set] = {
            "ruleSet": rule_set,
            "name": index.get("name", rule_set),
            "directory": index_path.parent.name,
            "ruleCount": index.get("ruleCount", len(index.get("rules") or {})),
        }
    return discovered


def rule_set_dir(root: Path, rule_set: str) -> Path:
    rule_sets = discover_rule_sets(root)
    meta = rule_sets.get(rule_set)
    if not meta:
        known = ", ".join(sorted(rule_sets))
        fail(f"Rule set not found: {rule_set!r}\nKnown rule sets: {known}")
    return root / meta["directory"]


def load_rule_set_index(root: Path, rule_set: str) -> dict[str, Any]:
    return load_json(rule_set_dir(root, rule_set) / "index.json", purpose=f"rule-set index for {rule_set}")


def load_aliases(root: Path) -> dict[str, dict[str, str]]:
    aliases: dict[str, dict[str, str]] = {}
    root_aliases = root / "aliases.json"
    if root_aliases.exists():
        aliases.update(load_json(root_aliases, purpose="alias index"))
    for alias_path in sorted(root.glob("*/aliases.json")):
        aliases.update(load_json(alias_path, purpose=f"alias index at {alias_path}"))
    return aliases


def parse_citation(root: Path, citation: str, explicit_rule_set: str | None = None) -> tuple[str, str]:
    normalized_input = " ".join(citation.strip().split())
    rule_set = explicit_rule_set

    alias_hit = load_aliases(root).get(normalize_alias(normalized_input))
    if alias_hit and (rule_set is None or alias_hit["ruleSet"] == rule_set):
        return alias_hit["ruleSet"], alias_hit["ruleId"]

    inferred = infer_rule_set(normalized_input)
    if rule_set is None:
        rule_set = inferred

    rule_id = parse_rule_id_for_rule_set(normalized_input, rule_set)
    if rule_id:
        return rule_set or FRCP, rule_id

    fail(
        f"Could not parse rule citation: {citation!r}\n"
        "Examples: 'FRCP 26', 'FRAP 4', 'FRE 403', 'Fed. R. App. P. 32', 'Fed. R. Evid. 801', "
        "'Supplemental Rule G', 'Social Security Rule 1', "
        "'SDNY Local Civil Rule 7.1', 'S.D. Fla. L.R. 5.1', 'M.D. Fla. L.R. 1.08', "
        "'N.D. Fla. L.R. 5.1', 'N.D. Ill. L.R. 5.2', 'C.D. Ill. Civ. L.R. 5.1', "
        "'SDIL-LR 5.1', 'S.D. Tex. L.R. 10', 'N.D. Tex. L.R. 7.2', "
        "'W.D. Tex. L.R. 10', 'E.D. Tex. CV L.R. 7', 'D.N.J. L.Civ.R. 7.1', "
        "'D. Ariz. LRCiv 7.2', 'D. Ariz. ECF Manual II.J', 'SDNY ECF Rule 23.4'."
    )


def infer_rule_set(citation: str) -> str | None:
    if re.search(r"\bECF\b|\belectronic case filing\b", citation, re.IGNORECASE):
        if re.search(r"\bD\.?\s*Ariz\.?\b|\bD\.?\s*AZ\b|\bAZD\b|\bDistrict of Arizona\b", citation, re.IGNORECASE):
            return AZD_ECF
        return SDNY_ECF
    if re.search(
        r"\blocal\b|\bL\.?\s*R\.?\b|\bLRCiv\b|\bLRCrim\b|\bLRBankr\b|\bSDNY\b|\bS\.D\.N\.Y\.\b|\bEDNY\b|\bE\.D\.N\.Y\.\b|\bILND\b|\bILCD\b|\bILSD\b|\bSDIL-LR\b|\bIll\.?\b|\bTXS\b|\bTXSD\b|\bTXND\b|\bTXWD\b|\bTXED\b|\bTex\.?\b|\bDNJ\b|\bD\.N\.J\.\b|\bNJD\b|\bNew Jersey\b|\bAZD\b|\bD\.?\s*Ariz\.?\b|\bD\.?\s*AZ\b|\bDistrict of Arizona\b|\bPAED\b|\bPAMD\b|\bPAWD\b|\bE\.?\s*D\.?\s*Pa\.?\b|\bM\.?\s*D\.?\s*Pa\.?\b|\bW\.?\s*D\.?\s*Pa\.?\b|\bEastern District of Pennsylvania\b|\bMiddle District of Pennsylvania\b|\bWestern District of Pennsylvania\b",
        citation,
        re.IGNORECASE,
    ):
        if re.search(r"\bD\.?\s*Ariz\.?\b|\bD\.?\s*AZ\b|\bAZD\b|\bDistrict of Arizona\b", citation, re.IGNORECASE):
            return AZD_LOCAL
        if re.search(r"\bE\.?\s*D\.?\s*Pa\.?\b|\bPAED\b|\bEastern District of Pennsylvania\b", citation, re.IGNORECASE):
            if re.search(r"\b(?:Crim(?:inal)?|Cr\.?|L\.?\s*Cr\.?\s*R\.?)\b", citation, re.IGNORECASE):
                return PAED_CRIMINAL_LOCAL
            return PAED_CIVIL_LOCAL
        if re.search(r"\bM\.?\s*D\.?\s*Pa\.?\b|\bPAMD\b|\bMiddle District of Pennsylvania\b", citation, re.IGNORECASE):
            return PAMD_LOCAL
        if re.search(r"\bW\.?\s*D\.?\s*Pa\.?\b|\bPAWD\b|\bWestern District of Pennsylvania\b", citation, re.IGNORECASE):
            return PAWD_LOCAL
        if re.search(r"\bD\.?\s*N\.?\s*J\.?\b|\bDNJ\b|\bNJD\b|\bDistrict of New Jersey\b", citation, re.IGNORECASE):
            return DNJ_LOCAL
        if re.search(r"\bS\.?\s*D\.?\s*Fla\.?\b|\bSDFL\b|\bSouthern District of Florida\b", citation, re.IGNORECASE):
            return FLSD_LOCAL
        if re.search(r"\bM\.?\s*D\.?\s*Fla\.?\b|\bFLMD\b|\bMiddle District of Florida\b", citation, re.IGNORECASE):
            return FLMD_LOCAL
        if re.search(r"\bN\.?\s*D\.?\s*Fla\.?\b|\bFLND\b|\bNorthern District of Florida\b", citation, re.IGNORECASE):
            return FLND_LOCAL
        if re.search(r"\bN\.?\s*D\.?\s*Ill\.?\b|\bILND\b|\bNorthern District of Illinois\b", citation, re.IGNORECASE):
            return ILND_LOCAL
        if re.search(r"\bC\.?\s*D\.?\s*Ill\.?\b|\bILCD\b|\bCentral District of Illinois\b", citation, re.IGNORECASE):
            return ILCD_LOCAL
        if re.search(r"\bS\.?\s*D\.?\s*Ill\.?\b|\bILSD\b|\bSDIL-LR\b|\bSouthern District of Illinois\b", citation, re.IGNORECASE):
            return ILSD_LOCAL
        if re.search(r"\bS\.?\s*D\.?\s*Tex\.?\b|\bTXS\b|\bTXSD\b|\bSDTX\b|\bSouthern District of Texas\b", citation, re.IGNORECASE):
            return TXS_LOCAL
        if re.search(r"\bN\.?\s*D\.?\s*Tex\.?\b|\bTXND\b|\bNDTX\b|\bNorthern District of Texas\b", citation, re.IGNORECASE):
            return TXND_LOCAL
        if re.search(r"\bW\.?\s*D\.?\s*Tex\.?\b|\bTXWD\b|\bWDTX\b|\bWestern District of Texas\b", citation, re.IGNORECASE):
            return TXWD_LOCAL
        if re.search(r"\bE\.?\s*D\.?\s*Tex\.?\b|\bTXED\b|\bEDTX\b|\bEastern District of Texas\b", citation, re.IGNORECASE):
            return TXED_LOCAL
        return SDNY_EDNY_LOCAL
    if re.search(r"\bsocial security\b|\b42\s+U\.?S\.?C\.?\s*§?\s*405\(g\)", citation, re.IGNORECASE):
        return SOCIAL_SECURITY
    if re.search(r"\badmiralty\b|\bsupp(?:lemental)?\.?\s+(?:r|rule)\b", citation, re.IGNORECASE):
        return ADMIRALTY
    if re.search(
        r"\bFRAP\b|\bFed\.?\s*R\.?\s*App\.?\s*P\.?\b|\bFederal Rules? of Appellate Procedure\b",
        citation,
        re.IGNORECASE,
    ):
        return FRAP
    if re.search(
        r"\bFRE\b|\bFed\.?\s*R\.?\s*Evid\.?\b|\bFederal Rules? of Evidence\b",
        citation,
        re.IGNORECASE,
    ):
        return FRE
    return None


def parse_rule_id_for_rule_set(citation: str, rule_set: str | None) -> str | None:
    if rule_set == SDNY_EDNY_LOCAL:
        family = "civil"
        family_match = re.search(r"\b(Civil|Social Security|Admiralty|Criminal|Patent)\b", citation, re.IGNORECASE)
        if family_match:
            family = family_match.group(1).lower().replace(" ", "-")
        m = re.search(r"\b([A-Z]?\d+(?:\.\d+)*|[A-Z]\.\d+|[A-Z])\b", citation)
        return f"{family}-{m.group(1)}" if m else None
    if rule_set == SDNY_ECF:
        m = re.search(r"\b(\d+(?:\.\d+)?)\b", citation)
        return m.group(1) if m else None
    if rule_set in {
        FLSD_LOCAL,
        FLMD_LOCAL,
        FLND_LOCAL,
        ILND_LOCAL,
        ILCD_LOCAL,
        ILSD_LOCAL,
        TXS_LOCAL,
        TXND_LOCAL,
        TXWD_LOCAL,
        TXED_LOCAL,
        DNJ_LOCAL,
        AZD_LOCAL,
        AZD_ECF,
        PAED_CIVIL_LOCAL,
        PAED_CRIMINAL_LOCAL,
        PAMD_LOCAL,
        PAWD_LOCAL,
    }:
        if rule_set == AZD_ECF:
            m = re.search(r"\b([IVX]+\.[A-Z])\b", citation, re.IGNORECASE)
            return m.group(1).upper() if m else None
        if rule_set == AZD_LOCAL:
            family = "civil"
            if re.search(r"\bLRCrim\b|\bCrim(?:inal)?\b", citation, re.IGNORECASE):
                family = "criminal"
            elif re.search(r"\bLRBankr\b|\bBankr(?:uptcy)?\b", citation, re.IGNORECASE):
                family = "bankruptcy"
            m = re.search(r"\b(\d+(?:\.\d+)*(?:-\d+)?)\b", citation)
            return f"{family}-{m.group(1)}" if m else None
        if rule_set == DNJ_LOCAL:
            family = "civil"
            if re.search(r"\b(?:Crim(?:inal)?|Cr\.?|L\.?\s*Cr\.?\s*R\.?)\b", citation, re.IGNORECASE):
                family = "criminal"
            m = re.search(r"\b(\d+(?:\.\d+)*)\b", citation)
            return f"{family}-{m.group(1)}" if m else None
        if rule_set in {PAED_CIVIL_LOCAL, PAED_CRIMINAL_LOCAL, PAMD_LOCAL}:
            roman = re.search(r"\b(XIII)\b", citation, re.IGNORECASE)
            if roman and rule_set == PAED_CIVIL_LOCAL:
                return roman.group(1).lower()
            m = re.search(r"\b(\d+(?:\.\d+)*)\b", citation)
            return m.group(1) if m else None
        if rule_set == PAWD_LOCAL:
            family_match = re.search(r"\b(LCvR-Adm|LCvR|LCrR|LAP|Civil|Crim(?:inal)?|Admiralty)\b", citation, re.IGNORECASE)
            family = "lcvr"
            if family_match:
                matched = family_match.group(1).lower()
                if matched.startswith("lcr") or matched.startswith("crim"):
                    family = "lcrr"
                elif matched.startswith("lap"):
                    family = "lap"
                elif "adm" in matched:
                    family = "lcvr-adm"
            m = re.search(r"\b(\d+[A-Za-z]?(?:\.\d+)*|71\.A|2241|2254|2255)\b", citation, re.IGNORECASE)
            return f"{family}-{m.group(1).lower()}" if m else None
        if rule_set == ILND_LOCAL:
            admiralty = re.search(r"\b(?:LRSup|Supplemental\s+Rule)\s*([A-Z](?:\.\d+)?)\b", citation, re.IGNORECASE)
            if admiralty:
                return f"admiralty-{admiralty.group(1).upper()}"
            dcf = re.search(r"\bD\.?\s*C\.?\s*F\.?\s*(?:Reg(?:ulation)?\.?)?\s*(\d+)\b", citation, re.IGNORECASE)
            if dcf:
                return f"dcf-reg-{dcf.group(1)}"
        if rule_set == ILCD_LOCAL:
            family = "civil"
            family_match = re.search(r"\b(Civ(?:il)?|Crim(?:inal)?)\b", citation, re.IGNORECASE)
            if family_match and family_match.group(1).lower().startswith("crim"):
                family = "criminal"
            m = re.search(r"\b(\d+(?:\.\d+)*(?:-\d+)?)\b", citation)
            return f"{family}-{m.group(1)}" if m else None
        if rule_set == FLSD_LOCAL:
            admiralty = re.search(r"\b(?:Admiralty\s+)?(?:Rule|R\.?)\s*([A-F])\b", citation, re.IGNORECASE)
            if admiralty:
                return f"admiralty-{admiralty.group(1).upper()}"
        if rule_set == TXS_LOCAL:
            criminal = re.search(r"\b(?:Crim(?:inal)?\.?\s*)?(?:L\.?\s*R\.?|Rule|CrLR)\s*(\d+(?:\.\d+)?)\b", citation, re.IGNORECASE)
            if criminal and re.search(r"\bCr(?:im|LR)\b|Criminal", citation, re.IGNORECASE):
                return f"criminal-{criminal.group(1)}"
        if rule_set == TXED_LOCAL:
            family_match = re.search(r"\b(CV|CR|AT|Patent|Admiralty)\b", citation, re.IGNORECASE)
            family = family_match.group(1).lower() if family_match else "cv"
            m = re.search(r"\b(\d+(?:\.\d+)?(?:-\d+)?)\b", citation)
            if m:
                if family.startswith("patent"):
                    return f"patent-{m.group(1)}"
                if family.startswith("admiralty"):
                    return f"admiralty-{m.group(1).lower()}"
                return f"{family}-{m.group(1)}"
        m = re.search(r"\b(\d+(?:\.\d+)*(?:-\d+)?)\b", citation)
        return m.group(1) if m else None
    if rule_set == ADMIRALTY:
        m = re.search(r"\b(?:Rule|R\.?)\s*([A-G])\b", citation, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        return citation.upper() if re.fullmatch(r"[A-Ga-g]", citation) else None
    if rule_set == FRAP:
        m = re.search(
            r"\b(?:Rule|R\.?|FRAP|Fed\.?\s*R\.?\s*App\.?\s*P\.?|Federal Rules? of Appellate Procedure)\s*(\d+(?:\.\d+)?)\b",
            citation,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)
        if re.fullmatch(r"\d+(?:\.\d+)?", citation):
            return citation
        return None
    if rule_set == FRE:
        m = re.search(
            r"\b(?:Rule|R\.?|FRE|Fed\.?\s*R\.?\s*Evid\.?|Federal Rules? of Evidence)\s*(\d{3,4})\b",
            citation,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)
        if re.fullmatch(r"\d{3,4}", citation):
            return citation
        return None
    m = re.search(r"\b(?:Rule|R\.?|FRCP|Fed\.?\s*R\.?\s*Civ\.?\s*P\.?)\s*(\d+(?:\.\d+)?)\b", citation, re.IGNORECASE)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d+(?:\.\d+)?", citation):
        return citation
    return None


def resolve(root: Path, citation: str, explicit_rule_set: str | None = None) -> tuple[dict[str, Any], str]:
    rule_set, rule_id = parse_citation(root, citation, explicit_rule_set)
    index = load_rule_set_index(root, rule_set)
    entry = (index.get("rules") or {}).get(rule_id)
    if not entry:
        sample = ", ".join(list((index.get("rules") or {}).keys())[:30])
        fail(
            f"Rule not found: {citation!r}\n"
            f"Parsed rule set: {rule_set!r}; parsed rule id: {rule_id!r}\n"
            f"Sample rule ids in this set: {sample}"
        )

    html_path = rule_set_dir(root, rule_set) / entry["path"]
    parser = RuleTextExtractor(entry["anchor"])
    parser.feed(html_path.read_text(encoding="utf-8"))
    text = parser.text()
    if not text and entry.get("textLength"):
        fail(f"Could not extract text for {entry['citation']}.\nExpected anchor: {entry['anchor']!r}; HTML path: {html_path}")
    return entry, text


def status_banner(entry: dict[str, Any]) -> str:
    bits = [entry.get("ruleSet", "unknown")]
    if entry.get("status") and entry["status"] != "current":
        bits.append(entry["status"])
    if entry.get("sourcePageStart"):
        pages = str(entry["sourcePageStart"])
        if entry.get("sourcePageEnd") and entry["sourcePageEnd"] != entry["sourcePageStart"]:
            pages += f"-{entry['sourcePageEnd']}"
        bits.append(f"PDF pages {pages}")
    if entry.get("textLength"):
        bits.append(f"{entry['textLength']:,} chars")
    if entry.get("publicUrl"):
        bits.append(f"source {entry['publicUrl']}")
    return " | ".join(bits)


def format_rule(entry: dict[str, Any], text: str, *, output_format: str, max_bytes: int | None) -> str:
    if max_bytes is not None and len(text) > max_bytes:
        text = text[:max_bytes].rstrip() + f"\n\n[TRUNCATED to {max_bytes} characters]"

    if output_format == "json":
        payload = dict(entry)
        payload["text"] = text
        return json.dumps(payload, indent=2, ensure_ascii=False)

    if output_format == "markdown":
        lines = [f"# {entry['citation']} - {entry.get('title') or ''}", "", f"_Status: {status_banner(entry)}_"]
        if entry.get("division"):
            lines.append(f"_Division: {entry['division']}_")
        if entry.get("publicUrl"):
            lines.append(f"_Public source: {entry['publicUrl']}_")
        if entry.get("amendmentHistory"):
            lines.append(f"_History: {entry['amendmentHistory']}_")
        lines.extend(["", text])
        return "\n".join(lines)

    lines = [f"=== {entry['citation']} -- {entry.get('title') or ''} [{status_banner(entry)}] ==="]
    if entry.get("division"):
        lines.append(f"Division: {entry['division']}")
    if entry.get("publicUrl"):
        lines.append(f"Public source: {entry['publicUrl']}")
    if entry.get("amendmentHistory"):
        lines.append(f"History: {entry['amendmentHistory']}")
    lines.append(text)
    return "\n".join(lines)


def read_rules(root: Path, citations: list[str], *, rule_set: str | None, output_format: str, max_bytes: int | None) -> list[str]:
    output = []
    for citation in citations:
        entry, text = resolve(root, citation, rule_set)
        output.append(format_rule(entry, text, output_format=output_format, max_bytes=max_bytes))
    return output


def list_rule_sets(root: Path) -> str:
    lines = ["ruleSet                         rules  name"]
    for rule_set, meta in sorted(discover_rule_sets(root).items()):
        lines.append(f"{rule_set.ljust(30)} {str(meta.get('ruleCount', 0)).rjust(5)}  {meta.get('name', '')}")
    return "\n".join(lines)


def list_rules(root: Path, rule_set_arg: str | None) -> str:
    rule_set = normalize_rule_set(rule_set_arg) or FRCP
    index = load_rule_set_index(root, rule_set)
    lines = [f"{index.get('name')} ({index.get('ruleCount')} rules)"]
    current_division = None
    for rule_id, entry in sorted((index.get("rules") or {}).items(), key=lambda item: rule_sort_key(item[0])):
        division = entry.get("division") or ""
        if division and division != current_division:
            current_division = division
            lines.extend(["", division])
        status = f" [{entry.get('status')}]" if entry.get("status") and entry.get("status") != "current" else ""
        lines.append(f"  {rule_id.ljust(12)} {entry.get('title', '')}{status}")
    return "\n".join(lines)


def search_rules(
    root: Path,
    query: str,
    scopes: list[str],
    *,
    regex: bool,
    case_sensitive: bool,
    titles_only: bool,
    max_per_rule: int,
) -> str:
    pattern = compile_pattern(query, regex=regex, case_sensitive=case_sensitive)
    if scopes:
        rule_sets = [normalize_rule_set(scope) or FRCP for scope in scopes]
    else:
        rule_sets = list(discover_rule_sets(root).keys())

    lines: list[str] = []
    for rule_set in rule_sets:
        index = load_rule_set_index(root, rule_set)
        html_texts: dict[str, str] = {}
        if not titles_only:
            html_path = rule_set_dir(root, rule_set) / "rules.html"
            parser = AllRulesExtractor()
            parser.feed(html_path.read_text(encoding="utf-8"))
            html_texts = parser.results

        for rule_id, entry in sorted((index.get("rules") or {}).items(), key=lambda item: rule_sort_key(item[0])):
            haystack = entry.get("title", "") if titles_only else html_texts.get(entry["anchor"], "")
            matches = list(pattern.finditer(haystack))
            if not matches:
                continue
            lines.append(f"{entry['citation']} -- {entry.get('title', '')} [{entry.get('ruleSet')}]")
            if not titles_only:
                for match in matches[:max_per_rule]:
                    lines.append(f"  ...{snippet(haystack, match.start(), match.end())}...")
    return "\n".join(lines)


def compile_pattern(query: str, *, regex: bool, case_sensitive: bool) -> re.Pattern[str]:
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(query if regex else re.escape(query), flags)


def snippet(text: str, start: int, end: int, width: int = 100) -> str:
    left = max(0, start - width)
    right = min(len(text), end + width)
    value = text[left:right].replace("\n", " ")
    return re.sub(r"\s+", " ", value).strip()


def rule_sort_key(rule_id: str) -> tuple[int, int, str]:
    local = re.match(r"^([a-z-]+)-(.+)$", rule_id)
    prefix = ""
    if local:
        prefix = local.group(1)
        rule_id = local.group(2)
    if rule_id.isalpha():
        return (1000, 0, f"{prefix}:{rule_id}")
    if "." in rule_id:
        major, minor = rule_id.split(".", 1)
        minor_num = int(minor) if minor.isdigit() else 0
        major_num = int(major) if major.isdigit() else 1000
        return (major_num, minor_num, prefix)
    if rule_id.isdigit():
        return (int(rule_id), 0, prefix)
    return (1000, 0, f"{prefix}:{rule_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("citations", nargs="*", help="Rule citation(s), e.g. 'FRCP 26', 'SDNY ECF Rule 23.4'.")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--rule-set", help="Force a rule set for reads/lists.")
    parser.add_argument("--format", choices=["text", "markdown", "json"], default="text")
    parser.add_argument("--max-bytes", type=int, help="Truncate rule text to this many characters.")
    parser.add_argument("--list-rule-sets", action="store_true")
    parser.add_argument("--list", nargs="?", const="frcp", metavar="RULE_SET", help="List rules in a rule set.")
    parser.add_argument("--search", help="Search rule text; positional args become optional rule-set scopes.")
    parser.add_argument("--regex", action="store_true")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--titles-only", action="store_true")
    parser.add_argument("--max-per-rule", type=int, default=2)
    return parser


def run_cli(args: argparse.Namespace) -> int:
    forced_rule_set = normalize_rule_set(args.rule_set)
    if args.list_rule_sets:
        print(list_rule_sets(args.root))
        return 0
    if args.list is not None:
        print(list_rules(args.root, args.list))
        return 0
    if args.search:
        result = search_rules(
            args.root,
            args.search,
            args.citations,
            regex=args.regex,
            case_sensitive=args.case_sensitive,
            titles_only=args.titles_only,
            max_per_rule=args.max_per_rule,
        )
        if result:
            print(result)
        else:
            scope = f" in {', '.join(args.citations)}" if args.citations else ""
            print(f"No rules matched {args.search!r}{scope}.")
            if args.titles_only:
                print("Try again without --titles-only to search the bundled rule text.")
        return 0
    if not args.citations:
        raise ValueError("provide a citation, --list-rule-sets, --list, or --search")
    print("\n\n".join(read_rules(args.root, args.citations, rule_set=forced_rule_set, output_format=args.format, max_bytes=args.max_bytes)))
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(run_cli(args))
    except ValueError as exc:
        parser.error(str(exc))
    except LookupErrorWithDetail as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
