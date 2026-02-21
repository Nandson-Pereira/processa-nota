#!/usr/bin/env python3
"""
Servidor HTTP em Python puro (sem frameworks) para processamento de NFC-e.
"""

import http.server
import socketserver
import json
import xml.etree.ElementTree as ET
from datetime import datetime
import shutil
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from io import BytesIO
import re
import traceback
import sys

# Configurações
BASE_DIR = Path(__file__).parent.resolve()
PORT = 5000
FOLDERS = ["AUTORIZADO", "INUTILIZADO", "CANCELADO", "REJEITADO", "DESCARTE"]
UPLOAD_DIR = BASE_DIR / "uploads"

# Mapeamento de cStat para status
STATUS_MAP = {
    "100": "AUTORIZADO",
    "150": "AUTORIZADO",
    "102": "INUTILIZADO",
    "135": "CANCELADO",
}


def parse_multipart(rfile, content_type: str, content_length: int) -> list[tuple[str, str, bytes]]:
    """
    Parse multipart/form-data manualmente (cgi removido no Python 3.13).
    Retorna lista de (nome_campo, filename, conteudo).
    """
    match = re.search(r'boundary=([^;]+)', content_type)
    if not match:
        return []
    boundary = match.group(1).strip().strip('"')
    boundary_bytes = boundary.encode("latin-1")
    data = rfile.read(int(content_length or 0))
    parts = data.split(b"--" + boundary_bytes)
    result = []
    for part in parts:
        if not part or part.strip() in (b"--", b""):
            continue
        header, _, body = part.partition(b"\r\n\r\n")
        if not header:
            continue
        headers = header.decode("latin-1").split("\r\n")
        disp = None
        name = filename = None
        for h in headers:
            if h.lower().startswith("content-disposition:"):
                disp = h
                break
        if disp:
            n = re.search(r'name="([^"]+)"', disp, re.I)
            f = re.search(r'filename="([^"]*)"', disp, re.I)
            if n:
                name = n.group(1)
            if f:
                filename = f.group(1)
        body = body.rstrip(b"\r\n")
        if name and body:
            result.append((name, filename or "", body))
    return result


def get_status_from_cstat(cstat: str) -> str:
    """Retorna o status baseado no código cStat."""
    return STATUS_MAP.get(str(cstat).strip(), "REJEITADO")


def find_cstat_in_xml(root: ET.Element) -> str | None:
    """Busca a tag cStat em qualquer lugar do XML (namespace ou não)."""
    # cStat pode estar em diferentes locais dependendo do tipo de XML
    for elem in root.iter():
        # Remove namespace para comparação
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "cStat" and elem.text:
            return elem.text
    return None


def parse_xml_status(xml_path: Path) -> str | None:
    """Extrai o cStat do arquivo XML e retorna o status."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        cstat = find_cstat_in_xml(root)
        return get_status_from_cstat(cstat) if cstat else "REJEITADO"
    except ET.ParseError:
        return "REJEITADO"


def move_to_descarte():
    """Move todos os XMLs das pastas de status para DESCARTE."""
    for folder_name in ["AUTORIZADO", "INUTILIZADO", "CANCELADO", "REJEITADO"]:
        folder = BASE_DIR / folder_name
        if not folder.exists():
            continue
        descarte = BASE_DIR / "DESCARTE"
        descarte.mkdir(exist_ok=True)
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() == ".xml":
                dest = descarte / f"{f.stem}_{uuid.uuid4().hex[:8]}{f.suffix}"
                try:
                    shutil.move(str(f), str(dest))
                except Exception:
                    pass


def ensure_folders():
    """Garante que todas as pastas existam."""
    for name in FOLDERS:
        (BASE_DIR / name).mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)


def process_uploads() -> dict:
    """Processa XMLs em uploads, move para pastas por status e retorna contagens."""
    ensure_folders()
    move_to_descarte()

    counts = {"AUTORIZADO": 0, "INUTILIZADO": 0, "CANCELADO": 0, "REJEITADO": 0}

    if not UPLOAD_DIR.exists():
        return counts

    for f in UPLOAD_DIR.iterdir():
        if not f.is_file() or f.suffix.lower() != ".xml":
            continue
        status = parse_xml_status(f)
        if status and status in counts:
            dest_folder = BASE_DIR / status
            dest_file = dest_folder / f.name
            try:
                shutil.move(str(f), str(dest_file))
                counts[status] += 1
            except Exception:
                pass

    return counts


NFE_NAMESPACE = "{http://www.portalfiscal.inf.br/nfe}"

HEADER_AUTORIZADAS = "CNPJ, SERIE, N_NFCE, VALOR_NFCE, TOTAL_ICMS, TOTAL_PIS, TOTAL_COFINS, CHAVE_ACESSO, PROTOCOLO_AUT, COD.AUT_PAGAMENTO, vIBSUF, vIBSMun, vCBS, DATA_EMISSAO"
FORMATO_AUTORIZADAS = "{0}, {1}, {2}, {3}, {4}, {5}, {6}, '{7}', {8}, {9}, {10}, {11}, {12}, {13}"


def _text(elem: ET.Element | None) -> str:
    """Retorna texto do elemento ou vazio."""
    return (elem.text or "").strip() if elem is not None else ""


def ler_xmls_autorizadas(pasta: Path) -> list[tuple]:
    """
    Lê os arquivos XML de NFCe na pasta AUTORIZADO (cStat 100/150) e extrai
    os 14 campos no formato do relatório original.
    Retorna lista de tuplas: (cnpj, serie, nnf, vnf, vicms, vpis, vcofins, chnfe, nprot, caut, vibsuf, vibsmun, vcbs, data_emissao)
    """
    valores_autorizadas = []
    for arquivo in sorted(pasta.iterdir()):
        if not arquivo.is_file() or not arquivo.name.lower().endswith(".xml"):
            continue
        try:
            tree = ET.parse(arquivo)
            root = tree.getroot()
            infprot = root.find(f".//{NFE_NAMESPACE}protNFe/{NFE_NAMESPACE}infProt")
            if infprot is None:
                continue

            cstat_elem = infprot.find(f".//{NFE_NAMESPACE}cStat")
            cstat = cstat_elem.text if cstat_elem is not None else ""

            if cstat not in ("100", "150"):
                continue

            nprot_elem = infprot.find(f".//{NFE_NAMESPACE}nProt")
            nprot = nprot_elem.text if nprot_elem is not None else "0"

            chnfe_elem = infprot.find(f".//{NFE_NAMESPACE}chNFe")
            chnfe = chnfe_elem.text if chnfe_elem is not None else ""

            emit = root.find(f".//{NFE_NAMESPACE}emit/{NFE_NAMESPACE}CNPJ")
            ide_serie = root.find(f".//{NFE_NAMESPACE}ide/{NFE_NAMESPACE}serie")
            ide_nnf = root.find(f".//{NFE_NAMESPACE}ide/{NFE_NAMESPACE}nNF")
            cnpj = emit.text if emit is not None else ""
            serie = ide_serie.text if ide_serie is not None else ""
            nnf = ide_nnf.text if ide_nnf is not None else ""

            dhemi_elem = root.find(f".//{NFE_NAMESPACE}ide/{NFE_NAMESPACE}dhEmi")
            dhemi_full = dhemi_elem.text if dhemi_elem is not None else ""
            data_emissao = dhemi_full[:10] if len(dhemi_full) >= 10 else ""

            icmstot = root.find(f".//{NFE_NAMESPACE}total/{NFE_NAMESPACE}ICMSTot")
            vnf = _text(icmstot.find(f".//{NFE_NAMESPACE}vNF")) if icmstot is not None else "0"
            vicms = _text(icmstot.find(f".//{NFE_NAMESPACE}vICMS")) if icmstot is not None else "0"
            vpis = _text(icmstot.find(f".//{NFE_NAMESPACE}vPIS")) if icmstot is not None else "0"
            vcofins = _text(icmstot.find(f".//{NFE_NAMESPACE}vCOFINS")) if icmstot is not None else "0"

            card = root.find(f".//{NFE_NAMESPACE}pag/{NFE_NAMESPACE}detPag/{NFE_NAMESPACE}card")
            caut_elem = card.find(f".//{NFE_NAMESPACE}cAut") if card is not None else None
            caut = caut_elem.text if caut_elem is not None else "0"

            vibsuf = "0"
            vibsmun = "0"
            vcbs = "0"
            ibscbs_tot = root.find(f".//{NFE_NAMESPACE}total/{NFE_NAMESPACE}IBSCBSTot")
            if ibscbs_tot is not None:
                vibsuf_elem = ibscbs_tot.find(f".//{NFE_NAMESPACE}gIBS/{NFE_NAMESPACE}gIBSUF/{NFE_NAMESPACE}vIBSUF")
                if vibsuf_elem is not None:
                    vibsuf = vibsuf_elem.text or "0"
                vibsmun_elem = ibscbs_tot.find(f".//{NFE_NAMESPACE}gIBS/{NFE_NAMESPACE}gIBSMun/{NFE_NAMESPACE}vIBSMun")
                if vibsmun_elem is not None:
                    vibsmun = vibsmun_elem.text or "0"
                vcbs_elem = ibscbs_tot.find(f".//{NFE_NAMESPACE}gCBS/{NFE_NAMESPACE}vCBS")
                if vcbs_elem is not None:
                    vcbs = vcbs_elem.text or "0"

            valores_autorizadas.append(
                (cnpj, serie, nnf, vnf, vicms, vpis, vcofins, chnfe, nprot, caut, vibsuf, vibsmun, vcbs, data_emissao)
            )
        except (AttributeError, ET.ParseError):
            continue
    return valores_autorizadas


def gerar_relatorio_imposto_txt() -> str:
    """Gera relatório de impostos em .txt conforme layout do script original (valores_nfce.txt)."""
    pasta = BASE_DIR / "AUTORIZADO"
    if not pasta.exists():
        return ""

    autorizadas = ler_xmls_autorizadas(pasta)
    if not autorizadas:
        return ""

    linhas = [HEADER_AUTORIZADAS]
    for linha_dados in autorizadas:
        linhas.append(FORMATO_AUTORIZADAS.format(*linha_dados))

    return "\n".join(linhas)


def gerar_danfe_zip() -> tuple[bytes, str] | None:
    """
    Gera PDF DANFe para cada XML na pasta AUTORIZADO, compacta em .zip e retorna (bytes_zip, nome_arquivo).
    Retorna None se não houver XMLs autorizados ou se fpdf2 não estiver instalado.
    """
    try:
        from danfe import extrair_dados_danfe, gerar_pdf_danfe
    except ImportError as e:
        print(f"[DANFe] ImportError: {e}", file=sys.stderr)
        return None

    pasta = BASE_DIR / "AUTORIZADO"
    if not pasta.exists():
        return None

    buffer = BytesIO()
    try:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            count = 0
            for arq in sorted(pasta.glob("*.xml")):
                dados = extrair_dados_danfe(arq)
                if not dados or not dados.get("chave"):
                    continue
                try:
                    pdf_bytes = gerar_pdf_danfe(dados)
                    filename = f"{dados['chave']}.pdf"
                    zf.writestr(filename, pdf_bytes)
                    count += 1
                except Exception as e:
                    print(f"[DANFe] Erro ao gerar PDF para {arq.name}: {e}", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
                    continue
            if count == 0:
                return None

        buffer.seek(0)
        nome = f"danfe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        return (buffer.getvalue(), nome)
    except Exception as e:
        print(f"[DANFe] Erro ao gerar ZIP: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None


class Handler(http.server.BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Cliente fechou a conexão antes do fim (ex.: download cancelado)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def send_html(self, content: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def send_css(self, content: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def send_js(self, content: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/index.html":
            with open(BASE_DIR / "index.html", "rb") as f:
                self.send_html(f.read())
            return

        if path == "/static/style.css":
            with open(BASE_DIR / "static" / "style.css", "rb") as f:
                self.send_css(f.read())
            return

        if path == "/static/app.js":
            with open(BASE_DIR / "static" / "app.js", "rb") as f:
                self.send_js(f.read())
            return

        if path == "/relatorio-imposto":
            self.handle_relatorio_imposto()
            return

        if path == "/gerar-danfe":
            self.handle_gerar_danfe()
            return

        if path == "/debug-danfe":
            self.handle_debug_danfe()
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/upload":
            self.handle_upload()
            return

        if path == "/processar":
            self.handle_processar()
            return

        self.send_response(404)
        self.end_headers()

    def handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_json({"ok": False, "erro": "Formato inválido"}, 400)
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            parts = parse_multipart(self.rfile, content_type, content_length)
        except Exception as e:
            self.send_json({"ok": False, "erro": str(e)}, 400)
            return

        UPLOAD_DIR.mkdir(exist_ok=True)
        count = 0

        for name, filename, body in parts:
            if name != "xmls":
                continue
            fn = filename or f"arquivo_{count}.xml"
            if not fn.lower().endswith(".xml"):
                fn += ".xml"
            path = UPLOAD_DIR / fn
            with open(path, "wb") as out:
                out.write(body)
            count += 1

        self.send_json({"ok": True, "quantidade": count})

    def handle_processar(self):
        try:
            counts = process_uploads()
            self.send_json({"ok": True, "contagens": counts})
        except Exception as e:
            self.send_json({"ok": False, "erro": str(e)}, 500)

    def handle_relatorio_imposto(self):
        try:
            conteudo = gerar_relatorio_imposto_txt()
            if not conteudo:
                self.send_json({"ok": False, "erro": "Nenhum XML autorizado encontrado"}, 404)
                return
            dados = conteudo.encode("utf-8")
            filename = f"relatorio_impostos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(dados)
        except Exception as e:
            self.send_json({"ok": False, "erro": str(e)}, 500)

    def handle_gerar_danfe(self):
        try:
            resultado = gerar_danfe_zip()
            if not resultado:
                self.send_json({"ok": False, "erro": "Nenhum XML autorizado encontrado ou fpdf2 não instalado. Execute: pip install fpdf2"}, 404)
                return
            dados, filename = resultado
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(dados)
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as e:
            print(f"[DANFe] Erro no handler: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            try:
                if not self.wfile.closed:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "erro": str(e)}).encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def handle_debug_danfe(self):
        """Diagnóstico: testa geração do DANFe e retorna erro em JSON (abrir no navegador)."""
        try:
            resultado = gerar_danfe_zip()
            if resultado:
                dados, nome = resultado
                self.send_json({"ok": True, "msg": f"ZIP gerado com sucesso ({len(dados)} bytes, {nome})"})
            else:
                self.send_json({"ok": False, "erro": "Nenhum PDF gerado (pasta vazia, XMLs inválidos ou fpdf2 não instalado)"})
        except Exception as e:
            self.send_json({
                "ok": False,
                "erro": str(e),
                "tipo": type(e).__name__,
                "traceback": traceback.format_exc(),
            }, 500)


def main():
    ensure_folders()
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Servidor rodando em http://localhost:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
