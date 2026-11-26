"""UnicodeEngine: algorithmic text styles and encoders.

These are *algorithmic styles* (character substitutions defined by the Unicode
standard), not fonts. They are listed separately from genuine FIGlet/TOIlet
fonts throughout the application.
"""
from __future__ import annotations

import base64

# (upper A, lower a, digit 0, exceptions)
_MATH = {
    "bold": (0x1D400, 0x1D41A, 0x1D7CE, {}),
    "italic": (0x1D434, 0x1D44E, None, {"h": 0x210E}),
    "bold_italic": (0x1D468, 0x1D482, None, {}),
    "script": (0x1D49C, 0x1D4B6, None, {"B": 0x212C, "E": 0x2130, "F": 0x2131, "H": 0x210B, "I": 0x2110, "L": 0x2112,
                                       "M": 0x2133, "R": 0x211B, "e": 0x212F, "g": 0x210A, "o": 0x2134}),
    "bold_script": (0x1D4D0, 0x1D4EA, None, {}),
    "fraktur": (0x1D504, 0x1D51E, None, {"C": 0x212D, "H": 0x210C, "I": 0x2111, "R": 0x211C, "Z": 0x2128}),
    "bold_fraktur": (0x1D56C, 0x1D586, None, {}),
    "double_struck": (0x1D538, 0x1D552, 0x1D7D8, {"C": 0x2102, "H": 0x210D, "N": 0x2115, "P": 0x2119, "Q": 0x211A,
                                                "R": 0x211D, "Z": 0x2124}),
    "sans": (0x1D5A0, 0x1D5BA, 0x1D7E2, {}),
    "sans_bold": (0x1D5D4, 0x1D5EE, 0x1D7EC, {}),
    "sans_italic": (0x1D608, 0x1D622, None, {}),
    "sans_bold_italic": (0x1D63C, 0x1D656, None, {}),
    "monospace": (0x1D670, 0x1D68A, 0x1D7F6, {}),
}

_SMALL_CAPS = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"))
_SUPER = dict(zip("0123456789abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVW+-=()",
                  "⁰¹²³⁴⁵⁶⁷⁸⁹ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ⁺⁻⁼⁽⁾"))
_SUB = dict(zip("0123456789aehijklmnoprstuvx+-=()", "₀₁₂₃₄₅₆₇₈₉ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ₊₋₌₍₎"))
_UPSIDE = dict(zip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,!?'\"()[]{}<>_&;",
                   "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz∀ꓭƆꓷƎℲ⅁HIſꓘ˥WNOԀΌꓤS⊥∩ΛMX⅄Z0ƖᄅƐㄣϛ9ㄥ86˙'¡¿,„)(][}{><‾⅋؛"))

COMBINING = {"strike": "̶", "underline": "̲", "double_underline": "̳", "overline": "̅",
             "slash": "̸", "dots_above": "̇", "x_above": "̽"}

STYLE_NAMES = {
    "bold": "Mathematical bold", "italic": "Mathematical italic", "bold_italic": "Mathematical bold italic",
    "script": "Script", "bold_script": "Bold script", "fraktur": "Fraktur", "bold_fraktur": "Bold Fraktur",
    "double_struck": "Double-struck", "sans": "Sans-serif", "sans_bold": "Sans-serif bold",
    "sans_italic": "Sans-serif italic", "sans_bold_italic": "Sans-serif bold italic", "monospace": "Monospace",
    "fullwidth": "Full-width", "circled": "Bubble (circled)", "negative_circled": "Negative bubble",
    "squared": "Squared", "negative_squared": "Negative squared", "parenthesized": "Parenthesized",
    "small_caps": "Small caps", "superscript": "Superscript", "subscript": "Subscript",
    "upside_down": "Upside down", "strike": "Strikethrough", "underline": "Underline",
    "double_underline": "Double underline", "overline": "Overline", "slash": "Slashed",
    "spaced": "Spaced (aesthetic)", "regional": "Regional indicator letters",
}


def _math(text: str, style: str) -> str:
    A, a, zero, exc = _MATH[style]
    out = []
    for c in text:
        if c in exc:
            out.append(chr(exc[c]))
        elif "A" <= c <= "Z":
            out.append(chr(A + ord(c) - 65))
        elif "a" <= c <= "z":
            out.append(chr(a + ord(c) - 97))
        elif zero and "0" <= c <= "9":
            out.append(chr(zero + ord(c) - 48))
        else:
            out.append(c)
    return "".join(out)


def stylize(text: str, style: str) -> str:
    if style in _MATH:
        return _math(text, style)
    if style == "fullwidth":
        return "".join("　" if c == " " else chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)
    if style == "circled":
        def f(c):
            if "A" <= c <= "Z": return chr(0x24B6 + ord(c) - 65)
            if "a" <= c <= "z": return chr(0x24D0 + ord(c) - 97)
            if c == "0": return "⓪"
            if "1" <= c <= "9": return chr(0x2460 + ord(c) - 49)
            return c
        return "".join(f(c) for c in text)
    if style == "negative_circled":
        def f(c):
            if "A" <= c <= "Z" or "a" <= c <= "z": return chr(0x1F150 + ord(c.upper()) - 65)
            if c == "0": return "⓿"
            if "1" <= c <= "9": return chr(0x2776 + ord(c) - 49)
            return c
        return "".join(f(c) for c in text)
    if style in ("squared", "negative_squared"):
        base = 0x1F130 if style == "squared" else 0x1F170
        return "".join(chr(base + ord(c.upper()) - 65) if c.isascii() and c.isalpha() else c for c in text)
    if style == "parenthesized":
        def f(c):
            if "a" <= c <= "z": return chr(0x249C + ord(c) - 97)
            if "A" <= c <= "Z": return chr(0x1F110 + ord(c) - 65)
            if "1" <= c <= "9": return chr(0x2474 + ord(c) - 49)
            return c
        return "".join(f(c) for c in text)
    if style == "small_caps":
        return "".join(_SMALL_CAPS.get(c.lower(), c) if c.isascii() and c.isalpha() else c for c in text)
    if style == "superscript":
        return "".join(_SUPER.get(c, _SUPER.get(c.lower(), c)) for c in text)
    if style == "subscript":
        return "".join(_SUB.get(c, _SUB.get(c.lower(), c)) for c in text)
    if style == "upside_down":
        return "".join(_UPSIDE.get(c, c) for c in reversed(text))
    if style in COMBINING:
        m = COMBINING[style]
        return "".join(c + m if not c.isspace() else c for c in text)
    if style == "spaced":
        return " ".join(text)
    if style == "regional":
        return "​".join(chr(0x1F1E6 + ord(c.upper()) - 65) if c.isascii() and c.isalpha() else c for c in text)
    raise ValueError(f"unknown style {style!r}")


# ---------------------------------------------------------------------------
# encoders
# ---------------------------------------------------------------------------

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....", "I": "..",
    "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....", "6": "-....",
    "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.",
    "!": "-.-.--", "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...", ";": "-.-.-.",
    "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-", '"': ".-..-.", "$": "...-..-", "@": ".--.-.",
}
MORSE_REV = {v: k for k, v in MORSE.items()}

_BRAILLE_LETTERS = {
    "a": "⠁", "b": "⠃", "c": "⠉", "d": "⠙", "e": "⠑", "f": "⠋", "g": "⠛", "h": "⠓", "i": "⠊", "j": "⠚",
    "k": "⠅", "l": "⠇", "m": "⠍", "n": "⠝", "o": "⠕", "p": "⠏", "q": "⠟", "r": "⠗", "s": "⠎", "t": "⠞",
    "u": "⠥", "v": "⠧", "w": "⠺", "x": "⠭", "y": "⠽", "z": "⠵", ",": "⠂", ";": "⠆", ":": "⠒", ".": "⠲",
    "!": "⠖", "?": "⠦", "'": "⠄", "-": "⠤", "(": "⠐⠣", ")": "⠐⠜", "/": "⠸⠌", " ": " ",
}
_BRAILLE_DIGITS = dict(zip("1234567890", "⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚"))


def to_braille(text: str) -> str:
    """Uncontracted (Grade 1) English Braille transliteration."""
    out = []
    in_number = False
    for c in text:
        if "0" <= c <= "9":
            if not in_number:
                out.append("⠼")
                in_number = True
            out.append(_BRAILLE_DIGITS[c])
            continue
        in_number = False
        if c != c.lower() and c == c.upper():  # same test as the JS edition
            out.append("⠠")
            c = c.lower()
        out.append(_BRAILLE_LETTERS.get(c, c))
    return "".join(out)


def encode(text: str, kind: str, sep: str = " ") -> str:
    data = text.encode("utf-8")
    if kind == "binary":
        return sep.join(format(b, "08b") for b in data)
    if kind == "hex":
        return sep.join(format(b, "02X") for b in data)
    if kind == "octal":
        return sep.join(format(b, "03o") for b in data)
    if kind == "decimal":
        return sep.join(str(ord(c)) for c in text)
    if kind == "codepoints":
        return sep.join(f"U+{ord(c):04X}" for c in text)
    if kind == "base64":
        return base64.b64encode(data).decode("ascii")
    if kind == "morse":
        words = []
        for w in text.upper().split():
            words.append(" ".join(MORSE.get(c, "?") for c in w if c in MORSE or not c.isspace()))
        return " / ".join(words)
    if kind == "braille":
        return to_braille(text)
    raise ValueError(f"unknown encoding {kind!r}")


def decode(text: str, kind: str) -> str:
    t = text.strip()
    if kind == "binary":
        bits = "".join(ch for ch in t if ch in "01")
        if len(bits) % 8:
            raise ValueError("binary length is not a multiple of 8")
        return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)).decode("utf-8", errors="replace")
    if kind == "hex":
        h = "".join(ch for ch in t if ch in "0123456789abcdefABCDEF")
        if len(h) % 2:
            raise ValueError("odd number of hex digits")
        return bytes.fromhex(h).decode("utf-8", errors="replace")
    if kind == "morse":
        return " ".join("".join(MORSE_REV.get(sym, "?") for sym in w.split()) for w in t.split("/"))
    if kind == "base64":
        return base64.b64decode(t, validate=False).decode("utf-8", errors="replace")
    raise ValueError(f"cannot decode {kind!r}")


ENCODINGS = {"binary": "Binary", "hex": "Hexadecimal", "octal": "Octal", "decimal": "Decimal code points",
             "codepoints": "Unicode code points", "base64": "Base64", "morse": "Morse code",
             "braille": "Braille (Grade 1)"}

BOX_STYLES = {
    "rounded": ("╭", "─", "╮", "│", "╰", "╯"), "single": ("┌", "─", "┐", "│", "└", "┘"),
    "double": ("╔", "═", "╗", "║", "╚", "╝"), "heavy": ("┏", "━", "┓", "┃", "┗", "┛"),
    "ascii": ("+", "-", "+", "|", "+", "+"), "stars": ("*", "*", "*", "*", "*", "*"),
    "hash": ("#", "#", "#", "#", "#", "#"), "block": ("█", "▀", "█", "█", "█", "█"),
}


def text_box(text: str, style: str = "rounded", padding: int = 1, align: str = "left", title: str = "") -> str:
    from .figlet import char_width, graphemes
    tl, h, tr, v, bl, br = BOX_STYLES.get(style, BOX_STYLES["rounded"])
    lines = text.split("\n")
    def w(s: str) -> int:
        return sum(char_width(g) for g in graphemes(s))
    inner = max([w(ln) for ln in lines] + [w(title) + 2 if title else 0])
    pad = " " * padding
    top = tl + h * (inner + 2 * padding) + tr
    if title:
        t = f" {title} "
        top = tl + h + t + h * max(0, inner + 2 * padding - w(t) - 1) + tr
    out = [top]
    for ln in lines:
        gap = inner - w(ln)
        if align == "center":
            ln = " " * (gap // 2) + ln + " " * (gap - gap // 2)
        elif align == "right":
            ln = " " * gap + ln
        else:
            ln = ln + " " * gap
        out.append(v + pad + ln + pad + v)
    out.append(bl + (h if style != "block" else "▄") * (inner + 2 * padding) + br)
    return "\n".join(out)
