#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ui_reverse_doc.py
Tool sederhana untuk:
1) Memilih bahasa pemrograman target
2) Membaca berkas program yang sudah ada
3) Menghasilkan Pseudocode (gaya "internasional") dan Flowchart (Mermaid)

Catatan:
- Heuristik keyword-based lintas bahasa (Python/JS/Java/C/C++/C#/PHP/Go/Rust).
- Tidak menggantikan parser/AST formal, tapi cukup untuk dokumentasi cepat.
- Flowchart mengikuti konvensi ISO 5807 (terminator/process/decision/input-output),
  direpresentasikan via Mermaid flowchart.
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

def detect_matches(line, category):
    """Cek apakah line cocok salah satu regex di kategori."""
    for pat in KEYWORDS.get(category, []):
        if re.search(pat, line):
            return True
    return False

def normalize_indentation(lines, lang):
    """
    Coba normalisasi indent (untuk Python pakai leading spaces,
    untuk C-like berdasarkan kurung kurawal).
    Hasil berupa list of tuples: (indent_level, stripped_line)
    """
    out = []
    indent_level = 0
    soft_stack = []

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        # Skip empty/comment-only lines untuk kebersihan
        if not stripped or stripped.startswith(("//", "#")) or stripped.startswith("/*"):
            continue

        # C-like: kurangi indent jika baris mulai dengan '}'.
        if stripped.startswith("}"):
            indent_level = max(0, indent_level - 1)

        # Python: gunakan jumlah leading spaces/4
        if lang == "python":
            lead = len(line) - len(line.lstrip(" "))
            # heuristik: 4 spaces = 1 indent
            py_indent = lead // 4
            indent_level = py_indent

        out.append((indent_level, stripped))

        # C-like: tambah indent kalau ada '{' di baris ini.
        if lang != "python" and stripped.endswith("{"):
            indent_level += 1

        # Python: tambah indent setelah titik dua ':' pada kontrol struktur.
        if lang == "python" and re.search(r":\s*$", stripped) and (
            stripped.startswith(("if ", "elif ", "else", "for ", "while ", "def ", "class "))
        ):
            indent_level += 1

        # C-like: kurangi indent jika baris diakhiri '};' atau hanya '}' (ditangani di atas)
        if lang != "python" and stripped.endswith("};"):
            indent_level = max(0, indent_level - 1)

    return out

def line_to_step(line):
    """Klasifikasi baris menjadi tipe step untuk flow/pseudocode."""
    # Urutan penting: if/elif/else sebelum io/process umum
    for t in ["function", "if", "elif", "else", "for", "while", "do", "switch", "case", "default",
              "return", "io_in", "io_out"]:
        if detect_matches(line, t):
            return t
    # fallback
    return "process"

def build_steps(norm_lines):
    """
    Dari (indent, line) -> daftar node langkah.
    Node: dict {id, type, text, indent}
    """
    steps = []
    nid = 0
    # Start/End sebagai kerangka
    steps.append({"id": f"N{nid}", "type": "start", "text": "START", "indent": 0})
    nid += 1
    for indent, text in norm_lines:
        t = line_to_step(text)
        # Rapikan text (potong panjang sangat)
        short = text
        if len(short) > 140:
            short = short[:137] + "..."
        steps.append({"id": f"N{nid}", "type": t, "text": short, "indent": indent})
        nid += 1
    steps.append({"id": f"N{nid}", "type": "end", "text": "END", "indent": 0})
    return steps

def to_pseudocode(steps):
    """
    Buat pseudocode terstruktur.
    Konvensi:
    - BEGIN/END
    - PROCEDURE <name> / END PROCEDURE (jika terdeteksi)
    - IF/ELSEIF/ELSE/END IF
    - WHILE/END WHILE ; FOR/END FOR ; SWITCH/CASE/DEFAULT/END SWITCH
    - INPUT/OUTPUT ; PROCESS <...> ; RETURN <...>
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

        if t == "start" or t == "end":
            continue

        if t == "function":
            name = "procedure"
            # coba ambil nama fungsi
            m = re.search(r"\b(def|function|fn|func)\s+(\w+)\s*\(", txt)
            if m:
                name = m.group(2)
            w(f"PROCEDURE {name}(...)")
            func_stack.append(name)
            indent += 1

        elif t == "return":
            # ambil ekspresi setelah return
            m = re.search(r"\breturn\b(.*)", txt, flags=re.IGNORECASE)
            val = m.group(1).strip() if m else ""
            if val:
                w(f"RETURN {val}")
            else:
                w("RETURN")

        elif t == "if":
            cond = extract_condition(txt)
            w(f"IF {cond} THEN")
            ctrl_stack.append("IF")
            indent += 1

        elif t == "elif":
            # else-if: tutup blok sebelumnya satu tingkat, buka ELSE IF
            if ctrl_stack and ctrl_stack[-1] == "IF":
                indent = max(1, indent - 1)
                cond = extract_condition(txt)
                w(f"ELSE IF {cond} THEN")
                indent += 1
            else:
                # fallback jika struktur tak rapi
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
            # case memulai sub-blok kecil
            w(f"CASE {val}:")
            # indent satu tingkat untuk isi case
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
            # process umum
            w(f"PROCESS {txt}")

        # Heuristik penutupan blok berbasis kata kunci ujung baris
        if re.search(r"\b(end|endif|end if|endfor|end for|endwhile|end while|break;?)\b", txt, flags=re.IGNORECASE):
            # tutup satu blok
            if ctrl_stack:
                end_one_block(pc, ctrl_stack, lambda s: pc.append("  " * (indent-1) + s))
                indent = max(1, indent - 1)

    # Tutup sisa blok
    while ctrl_stack:
        end_one_block(pc, ctrl_stack, lambda s: pc.append("  " * (indent-1) + s))
        indent = max(1, indent - 1)

    # Tutup sisa procedure
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
    # ambil isi di dalam tanda kurung paling pertama
    m = re.search(r"\((.*)\)", txt)
    if m:
        cond = m.group(1).strip()
        cond = cond.rstrip("{").strip()
        return cond if cond else "<condition>"
    # python style: if cond:
    m2 = re.search(r"\b(if|elif|while)\s+(.+):", txt)
    if m2:
        return m2.group(2).strip()
    # switch key:
    m3 = re.search(r"\bswitch\s*\((.*)\)", txt, flags=re.IGNORECASE)
    if m3:
        return m3.group(1).strip()
    return "<condition>"

def extract_loop_header(txt):
    # C-like for (init; cond; step)
    m = re.search(r"for\s*\((.*)\)", txt)
    if m:
        return m.group(1).strip()
    # Python for x in y:
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
    # ambil potongan yang relevan
    t = re.sub(r"\s+", " ", txt)
    return t.strip()

def to_mermaid(steps):
    """
    Flowchart Mermaid dengan simbol:
    - Start/End: (terminator) => [(text)]
    - Process: [text]
    - Decision: {text}
    - I/O: [/ text /]
    """
    out = []
    out.append("flowchart TD")
    # mapping node id -> label
    def mm_label(node):
        t = node["type"]
        text = node["text"]
        # pendekkan
        if len(text) > 80:
            text = text[:77] + "..."
        if t in ("start", "end"):
            return f"{node['id']}([{text}])"
        if t in ("if", "elif", "else", "while", "switch", "case", "default"):
            return f"{node['id']}{{{escape_mermaid(text)}}}"
        if t in ("io_in", "io_out"):
            return f"{node['id']}[/{escape_mermaid(text)}/]"
        # default process
        return f"{node['id']}[{escape_mermaid(text)}]"

    for n in steps:
        out.append("  " + mm_label(n))

    # Simple linear edges (heuristik). Decision akan diarahkan linear;
    # untuk detail true/false, user bisa refine manual.
    for i in range(len(steps)-1):
        a = steps[i]["id"]
        b = steps[i+1]["id"]
        out.append(f"  {a} --> {b}")

    return "\n".join(out)

def escape_mermaid(s):
    return s.replace("[", "(").replace("]", ")")

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
    (outdir/"flowchart.mmd").write_text(mermaid, encoding="utf-8")

    print("\nSelesai.")
    print("Output:")
    print(f" - {outdir/'pseudocode.txt'}")
    print(f" - {outdir/'flowchart.mmd'}")
    print("\nTips:")
    print("• Buka flowchart.mmd di VS Code (extension Mermaid) atau mermaid.live untuk render.")
    print("• Heuristik sederhana; untuk hasil lebih tajam, rapikan struktur if/for/while di kode sumbernya.")
    print("• Kamu bisa ganti daftar KEYWORDS kalau ingin optimasi bahasa tertentu.")

if __name__ == "__main__":
    main()
