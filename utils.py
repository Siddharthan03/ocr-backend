import re
from datetime import datetime

EXPECTED_FIELDS = [
    "Patient Name", "Date of Birth", "SSN", "MRN", "Delivery/Receipt Date", "Procedure Date",
    "Procedure", "ITEM CODES", "SIDE", "Diagnosis Code (ICD-10)", "Physician Name", "Patient Address",
    "Patient Phone", "Guarantor Name", "PRIMARY PAYER", "Policy Number", "GROUP NUMBER",
    "AUTHORIZATION NUMBER", "SECONDARY PAYER", "Policy Number.1", "GROUP NUMBER.1", "AUTHORIZATION NUMBER.1",
    "Relationship to Insured", "Surgery Location", "Employer", "Assist Surgeon", "Components Used"
]

KEY_ALIASES = {
    "home phone": "Patient Phone",
    "hm ph": "Patient Phone",
    "home #": "Patient Phone",
    "telephone": "Patient Phone",
    "guarantor": "Guarantor Name",
    "doctor": "Physician Name",
    "provider": "Physician Name",
    "surgeon": "Physician Name",
    "name": "Patient Name"
}

KEY_LOOKUP = {k.lower(): k for k in EXPECTED_FIELDS}
KEY_LOOKUP.update(KEY_ALIASES)

PHYSICIAN_CORRECTIONS = {
    "steve tiskiles": "Steven Skules",
    "steven skules": "Steven Skules",
    "dr skules": "Steven Skules",
    "steven skukes": "Steven Skules"
}

ICD10_PATTERN = re.compile(r"\b([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?)\b")
DATE_PATTERN = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
SSN_PATTERN = re.compile(r"\b(?:\d{3}-\d{2}-\d{4}|xxx-xx-\d{4})\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
MRN_PATTERN = re.compile(r"\bMRN[:\s]*([A-Z0-9]{5,15})\b", re.IGNORECASE)
CPT_PATTERN = re.compile(r"\b(\d{5})\b")
COMPONENTS_KEYWORDS = ["Zimmer", "femur", "insert", "tibia", "Persona", "component", "baseplate", "augments"]

def clean_text(val):
    return re.sub(r"[^\w\s:/@.,()\-\[\]]+", "", val).strip()

def extract_key_value_pairs(line):
    pairs = []
    segments = re.split(r'(?<=\w):\s*', line)
    i = 0
    while i < len(segments) - 1:
        key = clean_text(segments[i])
        val = clean_text(segments[i + 1])
        pairs.append((key, val))
        i += 1
    return pairs

def is_valid(key, value):
    value = value.strip()
    if len(value) < 2 or len(value) > 150:
        return False
    if "date" in key.lower() or "dob" in key.lower():
        return bool(DATE_PATTERN.search(value))
    if "phone" in key.lower():
        return bool(PHONE_PATTERN.search(value))
    if "ssn" in key.lower():
        return bool(SSN_PATTERN.search(value))
    if "mrn" in key.lower():
        return value.isalnum()
    return True

def fuzzy_fix(key, value):
    if key == "Physician Name":
        val_lower = value.lower()
        for wrong, correct in PHYSICIAN_CORRECTIONS.items():
            if wrong in val_lower:
                return correct
    return value

def extract_metadata(text, filename=None):
    lines = text.splitlines()
    metadata = {}
    validations = {}
    icds = set()
    cpts = set()

    for line in lines:
        line_clean = clean_text(line)
        if not line_clean or ":" not in line_clean:
            continue
        for key, val in extract_key_value_pairs(line_clean):
            key_lower = key.lower().strip()
            match = next((k for k in KEY_LOOKUP if key_lower == k or key_lower in k or k in key_lower), None)
            if match:
                canonical_key = KEY_LOOKUP[match]
                val = fuzzy_fix(canonical_key, val)

                if canonical_key == "PRIMARY PAYER" and ICD10_PATTERN.search(val):
                    continue

                if canonical_key == "Patient Phone" and "214-645-3300" in val:
                    continue

                if canonical_key not in metadata and is_valid(canonical_key, val):
                    metadata[canonical_key] = val
                    validations[canonical_key] = "✅"

    for line in lines:
        line = clean_text(line)
        icds.update(ICD10_PATTERN.findall(line))
        cpts.update(CPT_PATTERN.findall(line))

        if not metadata.get("SSN"):
            match = SSN_PATTERN.search(line)
            if match:
                metadata["SSN"] = match.group(0)
                validations["SSN"] = "✅"

        if not metadata.get("MRN"):
            match = MRN_PATTERN.search(line)
            if match:
                metadata["MRN"] = match.group(1)
                validations["MRN"] = "✅"

    # ✅ DOB (only from proper label)
    if not metadata.get("Date of Birth"):
        for line in lines:
            if "dob" in line.lower() or "date of birth" in line.lower():
                match = DATE_PATTERN.search(line)
                if match:
                    mm, dd, yyyy = match.groups()
                    yyyy = "19" + yyyy if len(yyyy) == 2 and int(yyyy) > 30 else ("20" + yyyy if len(yyyy) == 2 else yyyy)
                    metadata["Date of Birth"] = f"{mm}/{dd}/{yyyy}"
                    validations["Date of Birth"] = "✅"
                    break

    # ✅ Home Phone fallback
    if not metadata.get("Patient Phone"):
        for line in lines:
            if "home phone" in line.lower() or "hm ph" in line.lower():
                match = PHONE_PATTERN.search(line)
                if match:
                    phone = match.group()
                    if "214-645-3300" not in phone:
                        metadata["Patient Phone"] = phone
                        validations["Patient Phone"] = "✅"
                        break

    # ✅ Guarantor Name
    if not metadata.get("Guarantor Name"):
        for line in lines:
            if "guarantor" in line.lower():
                parts = line.split(":")
                if len(parts) > 1:
                    name = parts[1].strip()
                    if len(name.split()) >= 2:
                        metadata["Guarantor Name"] = name
                        validations["Guarantor Name"] = "✅"
                        break

    # ✅ Delivery/Receipt Date from filename
    if filename and not metadata.get("Delivery/Receipt Date"):
        match = re.search(r'(\d{8})', filename)
        if match:
            digits = match.group(1)
            try:
                dt = datetime.strptime(digits, "%m%d%Y")
                metadata["Delivery/Receipt Date"] = dt.strftime("%m/%d/%Y")
                validations["Delivery/Receipt Date"] = "✅"
            except:
                pass

    if icds and "Diagnosis Code (ICD-10)" not in metadata:
        metadata["Diagnosis Code (ICD-10)"] = ", ".join(list(icds)[:3])
        validations["Diagnosis Code (ICD-10)"] = "✅"

    if cpts and "ITEM CODES" not in metadata:
        metadata["ITEM CODES"] = ", ".join(list(cpts)[:3])
        validations["ITEM CODES"] = "✅"

    if not metadata.get("Components Used"):
        for line in lines:
            if any(word.lower() in line.lower() for word in COMPONENTS_KEYWORDS):
                cleaned = clean_text(line)
                if len(cleaned.split()) > 4:
                    metadata["Components Used"] = cleaned
                    validations["Components Used"] = "✅"
                    break

    if "Physician Name" in metadata:
        val = metadata["Physician Name"]
        if not re.search(r"[A-Z][a-z]+\s+[A-Z]\.?\s+[A-Z][a-z]+", val) and len(val) < 5:
            metadata["Physician Name"] = "[Not provided]"
            validations["Physician Name"] = "❌ suspicious format"

    for field in ["Policy Number", "Policy Number.1"]:
        if field in metadata and len(metadata[field].split()) > 5:
            metadata[field] = "[Not provided]"
            validations[field] = "❌ too long"

    for field in EXPECTED_FIELDS:
        metadata.setdefault(field, "[Not provided]")
        validations.setdefault(field, "❌ missing")

    metadata["__validations__"] = validations
    return metadata
