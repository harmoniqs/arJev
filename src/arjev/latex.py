"""LaTeX→Unicode cleanup for Slack mrkdwn: arXiv titles are full of $\\sqrt{\\text{X}}$-style
math, which renders raw and ugly. Pragmatic, lossless-enough cleanup — tested, not
exhaustive."""

from __future__ import annotations

import re

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ",
    "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ",
    "Theta": "Θ", "Lambda": "Λ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
SYMBOLS = {
    "sqrt": "√", "times": "×", "cdot": "·", "pm": "±", "leq": "≤", "geq": "≥",
    "neq": "≠", "approx": "≈", "infty": "∞", "hbar": "ℏ", "langle": "⟨", "rangle": "⟩",
}
SUBSUP = {"+": "⁺", "-": "⁻", "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
          "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉"}


def latex_to_unicode(text: str) -> str:
    out = text
    out = re.sub(r"\$+[^$]*\$+", _clean_math, out)  # math spans first
    out = re.sub(r"\\text\{([^{}]*)\}", r"\1", out)
    out = re.sub(r"\\([a-zA-Z]+)", _macro, out)
    out = out.replace("\\\\", " ").replace("$", "")
    return re.sub(r"\s+", " ", out).strip()


def _clean_math(m: re.Match) -> str:
    inner = m.group(0).strip("$")
    inner = re.sub(r"\\text\{([^{}]*)\}", r"\1", inner)
    inner = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", inner)
    inner = re.sub(r"\\sqrt", "√", inner)
    for name, sym in SYMBOLS.items():
        inner = inner.replace(f"\\{name}", sym)
    for name, sym in GREEK.items():
        inner = re.sub(rf"\\{name}\b", sym, inner)
    inner = re.sub(r"\\left\b|\\right\b", "", inner)
    inner = re.sub(r"[_^]\{([^{}]+)\}", lambda m: _subsup(m.group(1)), inner)
    inner = re.sub(r"[_^]([a-zA-Z0-9+\-])", lambda m: _subsup(m.group(1)), inner)
    return inner.replace("{", "").replace("}", "")


def _subsup(chars: str) -> str:
    return "".join(SUBSUP.get(c, c) for c in chars)


def _macro(m: re.Match) -> str:
    name = m.group(1)
    return GREEK.get(name) or SYMBOLS.get(name) or ""
