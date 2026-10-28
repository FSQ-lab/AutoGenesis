"""Structural Appium page-source safety at the observation seam."""

import xml.etree.ElementTree as ET

from autogenesis_agent_contract import REDACTED, execution_plaintext, mark_secret, require_sensitive_target
_VALUE_ATTRIBUTES = {
    "text", "value", "label", "title", "name", "identifier",
    "placeholderValue", "content-desc", "resource-id",
}


def password_control(attributes):
    flags = (attributes.get("password"), attributes.get("secure"))
    types = {str(attributes.get(key, "")).lower() for key in ("type", "class", "role", "subrole")}
    return any(value is True or str(value).lower() == "true" for value in flags) or bool(types & {
        "xcuielementtypesecuretextfield", "axsecuretextfield", "securetextfield",
        "android.widget.passwordedittext",
    })


def _secure_element(element):
    return password_control(element.attrib) or password_control({"type": element.tag})


def mark_element_input_secret(element, value, parameter="text") -> bool:
    """Mark secure text and reject references aimed at an ordinary control."""
    attributes = {}
    for name in ("password", "secure", "type", "class", "role", "subrole"):
        try:
            attributes[name] = element.get_attribute(name)
        except Exception:
            continue
    secure = password_control(attributes)
    require_sensitive_target(parameter, "password" if secure else "")
    if secure and isinstance(value, str) and value:
        mark_secret(value, parameter)
        return True
    return False


def sanitize_page_source(value: str) -> str:
    """Remove secure values before any lossy transform, summary, file, or response."""
    if not value or not value.strip():
        return value
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        return "<hierarchy><summary>Page source unavailable</summary></hierarchy>"

    execution_secrets = execution_plaintext()
    changed = False
    for element in root.iter():
        secure = _secure_element(element)
        for key, original in tuple(element.attrib.items()):
            if original and (secure and key in _VALUE_ATTRIBUTES or original in execution_secrets):
                element.set(key, REDACTED)
                changed = True
        if element.text and element.text.strip() and (secure or element.text in execution_secrets):
            mark_secret(element.text)
            element.text = REDACTED
            changed = True
        if element.tail and element.tail in execution_secrets:
            mark_secret(element.tail)
            element.tail = REDACTED
            changed = True

    return ET.tostring(root, encoding="unicode") if changed else value
