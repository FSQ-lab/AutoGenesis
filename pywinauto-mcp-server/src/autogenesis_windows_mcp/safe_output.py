"""Fixed diagnostics for Windows runtime observation output."""


def safe_error(_error=None) -> str:
    return "Automation operation failed; sensitive details withheld."
