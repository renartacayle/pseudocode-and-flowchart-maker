#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ui_reverse_doc.py
Tool sederhana untuk:
1) Memilih bahasa pemrograman target
2) Membaca berkas program yang sudah ada
3) Menghasilkan Pseudocode (gaya "internasional") dan Flowchart (Mermaid + HTML)

Catatan:
- Heuristik keyword-based lintas bahasa (Python/JS/Java/C/C++/C#/PHP/Go/Rust).
- Tidak menggantikan parser/AST formal, tapi cukup untuk dokumentasi cepat.
- Flowchart default pakai bentuk paling kompatibel lintas renderer Mermaid.
"""

import re
import os
from pathlib import Path
from textwrap import dedent

LANGS = [
    "python", "javascript", "java", "c", "cpp", "csharp", "php", "go", "rust"
]

# Pola heuristik lintas-bahasa
KEYWORDS = {
    "io_in": [
        r"\binput\s*\(",              # Python
        r"\bscanf\s*\(",              # C/C
        r"\bcin\s*>>",                # C++
        r"\bConsole\.Read(Line)?\s*\(", # C#
        r"\breadline\s*\(",           # JS (node readline)
        r"\bprompt\s*\(",             # JS (browser)
        r"\bread\s*\(",               # Go bufio.NewReader.ReadString dll (kasar)
        r"\bgets\s*\(",               # C lama / PHP lama
        r"\bstd::getline\s*\(",       # C++
        r"\bBufferedReader\b.*readLine\s*\(", # Java
        r"\b$_(GET|POST|REQUEST)\b",  # PHP superglobals
        r"\bfmt\.Scan[fln]?\s*\(",    # Go
    ],
    "io_out": [
        r"\bprint\s*\(",              # Python
        r"\bprintf\s*\(",             # C/C++
        r"\bcout\s*<<",               # C++
        r"\bConsole\.Write(Line)?\s*\(", # C#
        r"\bSystem\.out\.print(ln)?\s*\(", # Java
        r"\bconsole\.log\s*\(",       # JS
        r"\becho\b",                  # PHP
        r"\bfmt\.Print[fln]?\s*\(",   # Go
    ],
    "if": [
        r"\bif\s*\(", r"\bif\s+[^:]+:"  # C-like & Python colon
    ],
    "elif": [
        r"\belse if\b", r"\belif\b"
    ],
    "else": [
        r"\belse\b"
    ],
    "for": [
        r"\bfor\s*\(",     # C/JS/Java/Go/Rust
        r"\bfor\b\s+.+\s+in\s+.+:" # Python for ... in ...
    ],
    "while": [
        r"\bwhile\s*\(", r"\bwhile\b\s*.+:" # C-like & Python
    ],
    "do": [
        r"\bdo\s*\{?"   # do { ... } while (...)
    ],
    "switch": [
        r"\bswitch\s*\("
    ],
    "case": [
        r"\bcase\b"
    ],
    "default": [
        r"\bdefault\b"
    ],
    "function": [
        r"\bdef\s+\w+\s*\(",          # Python
        r"\bfunction\s+\w+\s*\(",     # JS/PHP
        r"\b\w+\s+\w+\s*\([^;]*\)\s*\{", # Java/C/C++/C#/Go/Rust (kasar)
        r"\bfn\s+\w+\s*\(",           # Rust
        r"\bfunc\s+\w+\s*\(",         # Go
    ],
    "return": [
        r"\breturn\b"
    ],
    "open_block": [
        r"\{"
    ],
    "close_block": [
        r"\}"
    ]
}
def sanitize_mermaid_text(s: str) -> str:
    # normalize newline
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # hapus karakter kontrol non-printable (kecuali \n, \t)
    # rentang yang aman: TAB(0x09), LF(0x0A), CR(0x0D), spasi (0x20) s.d. 0x7E, plus BMP umum
    s = re.sub(r"[^\x09\x0A\x0D\x20-\x7E\u00A0-\uD7FF\uE000-\uFFFD]", "", s)
    # rapikan tab berlebih
    s = s.replace("\t", "  ")
    return s

def detect_matches(line, category):
    """Cek apakah line cocok salah satu regex di kategori."""
    for pat in KEYWORDS.get(category, []):
        if re.search(pat, line):
            return True
    return False

def normalize_indentation(lines, lang):
    """
    Normalisasi indent (Python: leading spaces; C-like: kurung kurawal).
    Hasil: list of tuples (indent_level, stripped_line)
    """
    out = []
    indent_level = 0

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        # Skip empty/comment-only
        if not stripped or stripped.startswith(("//", "#")) or stripped.startswith("/*"):
            continue

        # Handle penutup blok lebih dulu
        if stripped in ("}", "};"):
            # turunkan indent, JANGAN buat node
            indent_level = max(0, indent_level - 1)
            continue

        # Python: hitung indent
        if lang == "python":
            lead = len(line) - len(line.lstrip(" "))
            indent_level = lead // 4

        # Skip pembuka blok yang hanya "{" (tanpa konten)
        if stripped == "{":
            # naikkan indent untuk baris berikutnya, JANGAN buat node
            if lang != "python":
                indent_level += 1
            continue

        # Tambah node normal
        out.append((indent_level, stripped))

        # C-like: kalau baris ini diakhiri '{' (mis. `if (...) {`) → naikkan indent utk baris berikutnya
        if lang != "python" and stripped.endswith("{"):
            indent_level += 1

        # Python: tambah indent setelah ':'
        if lang == "python" and re.search(r":\s*$", stripped) and (
            stripped.startswith(("if ", "elif ", "else", "for ", "while ", "def ", "class "))
        ):
            indent_level += 1

        # C-like: penutup '};' (sudah ditangani di atas bila barisnya murni '};')
        if lang != "python" and stripped.endswith("};"):
            indent_level = max(0, indent_level - 1)

    return out

def line_to_step(line):
    """Klasifikasi baris menjadi tipe step untuk flow/pseudocode."""
    for t in ["function", "if", "elif", "else", "for", "while", "do", "switch", "case", "default",
              "return", "io_in", "io_out"]:
        if detect_matches(line, t):
            return t
    return "process"

def build_steps(norm_lines):
    """
    Dari (indent, line) -> daftar node langkah.
    Node: dict {id, type, text, indent}
    """
    steps = []
    nid = 0
    steps.append({"id": f"N{nid}", "type": "start", "text": "START", "indent": 0})
    nid += 1
    for indent, text in norm_lines:
        t = line_to_step(text)
        short = text if len(text) <= 140 else text[:137] + "..."
        steps.append({"id": f"N{nid}", "type": t, "text": short, "indent": indent})
        nid += 1
    steps.append({"id": f"N{nid}", "type": "end", "text": "END", "indent": 0})
    return steps

def to_pseudocode(steps):
    """
    Pseudocode terstruktur.
    """
    pc = []
    indent = 0

    def w(s):
        pc.append("  " * indent + s)

    w("BEGIN")
    indent += 1

    func_stack = []
    ctrl_stack = []

    for node in steps:
        t = node["type"]
        txt = node["text"]

        if t in ("start", "end"):
            continue

        if t == "function":
            name = "procedure"
            m = re.search(r"\b(def|function|fn|func)\s+(\w+)\s*\(", txt)
            if m:
                name = m.group(2)
            w(f"PROCEDURE {name}(...)")
            func_stack.append(name)
            indent += 1

        elif t == "return":
            m = re.search(r"\breturn\b(.*)", txt, flags=re.IGNORECASE)
            val = m.group(1).strip() if m else ""
            w("RETURN " + val if val else "RETURN")

        elif t == "if":
            cond = extract_condition(txt)
            w(f"IF {cond} THEN")
            ctrl_stack.append("IF")
            indent += 1

        elif t == "elif":
            if ctrl_stack and ctrl_stack[-1] == "IF":
                indent = max(1, indent - 1)
                cond = extract_condition(txt)
                w(f"ELSE IF {cond} THEN")
                indent += 1
            else:
                cond = extract_condition(txt)
                w(f"ELSE IF {cond} THEN")

        elif t == "else":
            if ctrl_stack and ctrl_stack[-1] == "IF":
                indent = max(1, indent - 1)
                w("ELSE")
                indent += 1
            else:
                w("ELSE")

        elif t == "for":
            rng = extract_loop_header(txt)
            w(f"FOR {rng} DO")
            ctrl_stack.append("FOR")
            indent += 1

        elif t == "while":
            cond = extract_condition(txt)
            w(f"WHILE {cond} DO")
            ctrl_stack.append("WHILE")
            indent += 1

        elif t == "do":
            w("DO")
            ctrl_stack.append("DO")
            indent += 1

        elif t == "switch":
            key = extract_condition(txt)
            w(f"SWITCH {key}")
            ctrl_stack.append("SWITCH")
            indent += 1

        elif t == "case":
            val = extract_case_value(txt)
            w(f"CASE {val}:")
            indent += 1
            ctrl_stack.append("CASE")

        elif t == "default":
            w("DEFAULT:")
            indent += 1
            ctrl_stack.append("CASE")

        elif t == "io_in":
            w(f"INPUT  ←  {compact_io(txt)}")

        elif t == "io_out":
            w(f"OUTPUT ←  {compact_io(txt)}")

        else:
            w(f"PROCESS {txt}")

        # Heuristik penutupan blok jika ada kata penutup eksplisit
        if re.search(r"\b(end|endif|end if|endfor|end for|endwhile|end while|break;?)\b", txt, flags=re.IGNORECASE):
            if ctrl_stack:
                end_one_block(pc, ctrl_stack, lambda s: pc.append("  " * (indent-1) + s))
                indent = max(1, indent - 1)

    # Tutup sisa blok
    while ctrl_stack:
        end_one_block(pc, ctrl_stack, lambda s: pc.append("  " * (indent-1) + s))
        indent = max(1, indent - 1)

    # Tutup procedure
    while func_stack:
        name = func_stack.pop()
        indent = max(1, indent - 1)
        w(f"END PROCEDURE  // {name}")

    indent = max(0, indent - 1)
    w("END")
    return "\n".join(pc)

def end_one_block(pc_list, stack, write_fn):
    last = stack.pop()
    if last == "IF":
        write_fn("END IF")
    elif last == "FOR":
        write_fn("END FOR")
    elif last == "WHILE":
        write_fn("END WHILE")
    elif last == "DO":
        write_fn("END DO")
    elif last == "SWITCH":
        write_fn("END SWITCH")
    elif last == "CASE":
        write_fn("// END CASE")

def extract_condition(txt):
    m = re.search(r"\((.*)\)", txt)
    if m:
        cond = m.group(1).strip()
        cond = cond.rstrip("{").strip()
        return cond if cond else "<condition>"
    m2 = re.search(r"\b(if|elif|while)\s+(.+):", txt)
    if m2:
        return m2.group(2).strip()
    m3 = re.search(r"\bswitch\s*\((.*)\)", txt, flags=re.IGNORECASE)
    if m3:
        return m3.group(1).strip()
    return "<condition>"

def extract_loop_header(txt):
    m = re.search(r"for\s*\((.*)\)", txt)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"for\s+(.+)\s+in\s+(.+):", txt)
    if m2:
        return f"{m2.group(1).strip()} IN {m2.group(2).strip()}"
    return "<loop>"

def extract_case_value(txt):
    m = re.search(r"\bcase\s+([^:]+):?", txt, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return "<value>"

def compact_io(txt):
    return re.sub(r"\s+", " ", txt).strip()

# ===================== PATCH: Mermaid-safe escaping & HTML output =====================

def escape_mermaid(s: str) -> str:
    """
    Mode aman untuk Mermaid (renderer lama/new):
    - Hilangkan bracket/brace/paren di label (bentuk node sudah kita kontrol).
    - Jinakkan <, >, "<<", kutip ganda, semicolon, backslash, backtick.
    - Normalisasi spasi.
    """
    s = re.sub(r"\s+", " ", s).strip()

    # buang bracket/brace/paren yang bentrok dengan bentuk Mermaid
    for ch in "[]{}()":
        s = s.replace(ch, "")

    # << dan tanda panah, hindari jadi TAGSTART/TAGEND
    s = s.replace("<<", "‹‹").replace("<", "‹").replace(">", "›")

    # kutip ganda → hapus (atau ganti apostrof kalau mau)
    s = s.replace('"', "").replace("“", "").replace("”", "")

    # semicolon full-width agar tak dianggap pemisah
    s = s.replace(";", "；")

    # backslash & backtick
    s = s.replace("\\", "⧵").replace("`", "ˋ")

    return s

# Tambahkan di dekat konstanta lain
ISO_FLOWCHART = True  # True = bentuk & border sesuai ISO 5807

def to_mermaid(steps):
    """
    Flowchart Mermaid:
    - Decision: { ... }
    - Start/End: ( ... )  [terminator/rounded]
    - Process: [ ... ]
    - I/O: parallelogram [/ ... /] (ISO) atau fallback kotak + prefix
    """
    out = []
    out.append("flowchart TD")

    def mm_label(node):
        t = node["type"]
        text = node["text"]
        if len(text) > 120:
            text = text[:117] + "..."
        text = escape_mermaid(text).strip()
        if not text:
            text = "NO-OP"

        # ISO shapes
        if t in ("if", "elif", "else", "while", "switch", "case", "default"):
            return f"{node['id']}{{{text}}}"          # decision (diamond)
        if t in ("start", "end"):
            return f"{node['id']}({text})"            # terminator (rounded)
        if t in ("io_in", "io_out"):
            if ISO_FLOWCHART:
                # parallelogram (butuh Mermaid 10+). Kita tetap escape karakter nakal.
                return f"{node['id']}[/{text}/]"
            else:
                prefix = "INPUT" if t == "io_in" else "OUTPUT"
                return f"{node['id']}[{prefix}: {text}]"
        # default process
        return f"{node['id']}[{text}]"

    # Definisi node (1 baris per node)
    for n in steps:
        out.append("  " + mm_label(n))

    # Edge linear (1 baris per edge)
    for i in range(len(steps) - 1):
        out.append(f"  {steps[i]['id']} --> {steps[i+1]['id']}")

    # ====== Styling border & teks sesuai standar (hitam, 1.5px, putih) ======
    # Kelas default untuk semua node
    out.append("  classDef default stroke:#000,stroke-width:1.5px,fill:#fff,color:#000;")
    # (opsional) kelas spesifik kalau mau beda tipis; untuk konsisten kita samakan
    out.append("  classDef term stroke:#000,stroke-width:1.5px,fill:#fff,color:#000;")
    out.append("  classDef io stroke:#000,stroke-width:1.5px,fill:#fff,color:#000;")
    out.append("  classDef decision stroke:#000,stroke-width:1.5px,fill:#fff,color:#000;")
    out.append("  classDef process stroke:#000,stroke-width:1.5px,fill:#fff,color:#000;")

    # Terapkan kelas (tidak wajib karena default sudah set, tapi eksplisit enak)
    term_ids = [steps[0]["id"], steps[-1]["id"]]  # START & END
    for nid in term_ids:
        out.append(f"  class {nid} term;")
    # Tandai IO & decision & process (opsional)
    for n in steps:
        t = n["type"]
        if t in ("io_in", "io_out"):
            out.append(f"  class {n['id']} io;")
        elif t in ("if", "elif", "else", "while", "switch", "case", "default"):
            out.append(f"  class {n['id']} decision;")
        elif t not in ("start", "end"):
            out.append(f"  class {n['id']} process;")

    # Styling garis panah (hitam, 1.5px)
    out.append("  linkStyle default stroke:#000,stroke-width:1.5px;")

    return "\n".join(out)

HTML_TMPL = """<!doctype html>
<html lang="id"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Flowchart (Mermaid)</title>
<style>
body{margin:0;padding:24px;font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial}
.wrap{max-width:1200px;margin:0 auto}
.info{color:#666;margin-bottom:12px}
.scroll-x{overflow:auto;border:1px solid #eee;border-radius:8px;padding:16px;background:#fafafa}
.mermaid{white-space:pre;}
.err{color:#b00020;background:#fee;border:1px solid #f99;padding:8px 12px;border-radius:6px;margin-top:12px;display:none;}
</style>
</head><body>
<div class="wrap">
  <div class="info">Mermaid render – file ini pakai CDN. Jika offline, gunakan mermaid CLI (mmdc) untuk ekspor PNG/SVG.</div>
  <div class="scroll-x">
    <!-- Kode Mermaid disimpan aman di <script>, nanti dikonversi ke <div> -->
    <script type="text/plain" class="mermaid-src">
{MERMAID_CODE}
    </script>
  </div>
  <div id="err" class="err"></div>
</div>

<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";

/* 1) Ubah <script type="text/plain" class="mermaid-src"> → <div class="mermaid"> */
const scripts = Array.from(document.querySelectorAll('script.mermaid-src[type="text/plain"]'));
for (const s of scripts) {
  const d = document.createElement('div');
  d.className = 'mermaid';
  // pakai textContent supaya karakter spesial tidak diparse sebagai HTML
  d.textContent = s.textContent;
  s.replaceWith(d);
}

/* 2) Init + render manual */
mermaid.initialize({ startOnLoad:false, securityLevel:"loose", theme:"default",
  flowchart:{ htmlLabels:true, curve:"basis" }});

try {
  await mermaid.run({querySelector:'.mermaid'});
} catch (e) {
  const box = document.getElementById('err');
  box.style.display='block';
  box.textContent = String(e?.error?.str ?? e?.message ?? e).slice(0, 700);
}
</script>
</body></html>"""

def write_mermaid_html(mermaid_code: str, out_path: Path):
    # rapikan & cegah penutupan <script> prematur
    safe = sanitize_mermaid_text(mermaid_code).replace("</script>", "</scr"+"ipt>")
    out_path.write_text(HTML_TMPL.replace("{MERMAID_CODE}", safe), encoding="utf-8")


# ===================== /PATCH =====================

def main():
    print("=== Reverse Doc UI: Pseudocode & Flowchart Generator ===")
    print("Pilih bahasa target:")
    for i, l in enumerate(LANGS, 1):
        print(f"{i}. {l}")
    try:
        choice = int(input("Masukkan nomor bahasa: ").strip())
        lang = LANGS[choice-1]
    except Exception:
        print("Pilihan tidak valid. Default ke 'python'.")
        lang = "python"

    path = input("Path file program yang sudah ada: ").strip()
    if not path:
        print("Path kosong. Keluar.")
        return

    p = Path(path)
    if not p.exists():
        print(f"File tidak ditemukan: {p}")
        return

    code = p.read_text(encoding="utf-8", errors="ignore").splitlines()

    # Normalisasi indent sesuai bahasa
    norm = normalize_indentation(code, lang)
    steps = build_steps(norm)

    pseudocode = to_pseudocode(steps)
    mermaid = to_mermaid(steps)

    outdir = Path("output")
    outdir.mkdir(exist_ok=True)
    (outdir/"pseudocode.txt").write_text(pseudocode, encoding="utf-8")
    # force LF newline
    (outdir/"flowchart.mmd").write_text(mermaid.replace("\r\n","\n"), encoding="utf-8")
    # HTML auto
    write_mermaid_html(mermaid, outdir/"flowchart.html")

    print("\nSelesai.")
    print("Output:")
    print(f" - {outdir/'pseudocode.txt'}")
    print(f" - {outdir/'flowchart.mmd'}")
    print(f" - {outdir/'flowchart.html'}  (buka di browser)")
    print("\nTips:")
    print("• Kalau renderer masih rewel, lihat 10 baris awal flowchart.mmd—"
          "pastikan tidak ada tanda \">\", \"<\", '\"', ';' mentah di label.")
    print("• HTML pakai CDN Mermaid@10; butuh internet saat dibuka.")

if __name__ == "__main__":
    main()
