"""
Geração de DANFe NFC-e em PDF. Layout modelo cupom 80mm.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from io import BytesIO

NFE_NS = "{http://www.portalfiscal.inf.br/nfe}"


def _t(e):
    return (e.text or "").strip() if e is not None else ""


def _fmt_cnpj(s):
    if not s or len(s) != 14:
        return s
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


def _fmt_cpf(s):
    if not s or len(s) != 11:
        return s
    return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"


def _fmt_valor(s):
    """Trunca valor monetário para 2 casas decimais."""
    if not s:
        return ""
    try:
        v = float(str(s).replace(",", "."))
        return f"{int(v * 100) / 100:.2f}".replace(".", ",")
    except (ValueError, TypeError):
        return str(s)


def _fmt_fone(s):
    """Máscara de telefone comercial: (XX) XXXX-XXXX ou (XX) XXXXX-XXXX."""
    if not s:
        return ""
    d = "".join(c for c in s if c.isdigit())
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    return s


def extrair_dados_danfe(xml_path: Path) -> dict | None:
    """Extrai dados do XML NFC-e para o DANFe. Retorna None se não for cStat 100/150."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        infprot = root.find(f".//{NFE_NS}protNFe/{NFE_NS}infProt")
        if infprot is None:
            return None
        cstat = _t(infprot.find(f".//{NFE_NS}cStat"))
        if cstat not in ("100", "150"):
            return None

        chave = _t(infprot.find(f".//{NFE_NS}chNFe"))
        if not chave:
            inf = root.find(f".//{NFE_NS}infNFe")
            if inf is not None and inf.get("Id"):
                chave = inf.get("Id", "").replace("NFe", "")

        ide = root.find(f".//{NFE_NS}ide")
        emit = root.find(f".//{NFE_NS}emit")
        ender = root.find(f".//{NFE_NS}emit/{NFE_NS}enderEmit")
        dest = root.find(f".//{NFE_NS}dest")
        total = root.find(f".//{NFE_NS}total/{NFE_NS}ICMSTot")
        infadic = root.find(f".//{NFE_NS}infAdic")
        supl = root.find(f".//{NFE_NS}infNFeSupl")

        dhemi = _t(ide.find(f".//{NFE_NS}dhEmi")) if ide else ""
        if "T" in dhemi:
            try:
                dt = datetime.fromisoformat(dhemi.replace("Z", "+00:00")[:19])
                dhemi = dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                pass

        n_nf = _t(ide.find(f".//{NFE_NS}nNF")) if ide else ""
        serie = _t(ide.find(f".//{NFE_NS}serie")) if ide else ""

        cnpj = _t(emit.find(f".//{NFE_NS}CNPJ")) if emit else ""
        ie = _t(emit.find(f".//{NFE_NS}IE")) if emit else ""
        nome = _t(emit.find(f".//{NFE_NS}xNome")) if emit else ""
        logr = _t(ender.find(f".//{NFE_NS}xLgr")) if ender else ""
        nro = _t(ender.find(f".//{NFE_NS}nro")) if ender else ""
        cpl = _t(ender.find(f".//{NFE_NS}xCpl")) if ender else ""
        bairro = _t(ender.find(f".//{NFE_NS}xBairro")) if ender else ""
        mun = _t(ender.find(f".//{NFE_NS}xMun")) if ender else ""
        uf = _t(ender.find(f".//{NFE_NS}UF")) if ender else ""
        cep = _t(ender.find(f".//{NFE_NS}CEP")) if ender else ""
        fone = _t(ender.find(f".//{NFE_NS}fone")) if ender else ""

        endereco = f"{logr}, {nro}"
        if cpl:
            endereco += f" - {cpl}"
        endereco += f"\n{bairro} - {mun}/{uf}"
        if cep:
            endereco += f" CEP: {cep[:5]}-{cep[5:]}" if len(cep) >= 8 else f" CEP: {cep}"

        dest_cpf = _t(dest.find(f".//{NFE_NS}CPF")) if dest else ""
        dest_cnpj = _t(dest.find(f".//{NFE_NS}CNPJ")) if dest else ""
        dest_nome = _t(dest.find(f".//{NFE_NS}xNome")) if dest else ""

        v_prod = _t(total.find(f".//{NFE_NS}vProd")) if total else "0"
        v_desc = _t(total.find(f".//{NFE_NS}vDesc")) if total else "0"
        v_nf = _t(total.find(f".//{NFE_NS}vNF")) if total else "0"
        v_tot_trib = _t(total.find(f".//{NFE_NS}vTotTrib")) if total else "0"

        infcpl = ""
        if infadic is not None:
            infcpl_elem = infadic.find(f".//{NFE_NS}infCpl")
            if infcpl_elem is not None and infcpl_elem.text:
                infcpl = infcpl_elem.text.strip()

        url_chave = _t(supl.find(f".//{NFE_NS}urlChave")) if supl else ""
        qr_code = ""
        if supl is not None:
            qr_elem = supl.find(f".//{NFE_NS}qrCode")
            if qr_elem is not None and qr_elem.text:
                qr_code = qr_elem.text.strip()

        itens = []
        for det in root.findall(f".//{NFE_NS}det"):
            prod = det.find(f".//{NFE_NS}prod")
            if prod is None:
                continue
            cprod = _t(prod.find(f".//{NFE_NS}cProd"))
            xprod = _t(prod.find(f".//{NFE_NS}xProd"))
            qcom = _t(prod.find(f".//{NFE_NS}qCom"))
            vprod = _t(prod.find(f".//{NFE_NS}vProd"))
            vdesc = _t(prod.find(f".//{NFE_NS}vDesc"))
            ucom = _t(prod.find(f".//{NFE_NS}uCom"))
            vun = _t(prod.find(f".//{NFE_NS}vUnCom"))
            itens.append({"cod": cprod, "desc": xprod, "qtd": qcom, "un": ucom, "vun": vun, "vprod": vprod, "vdesc": vdesc})

        pagamentos = []
        for det in root.findall(f".//{NFE_NS}detPag"):
            tpag = _t(det.find(f".//{NFE_NS}tPag"))
            vpag = _t(det.find(f".//{NFE_NS}vPag"))
            tmap = {"01": "Dinheiro", "02": "Cheque", "03": "Cartao Credito", "04": "Cartao Debito",
                    "05": "Credito Loja", "10": "Vale Alimentacao", "11": "Vale Refeicao",
                    "12": "Vale Presente", "13": "Vale Combustivel", "15": "Boleto",
                    "17": "PIX", "18": "Transferencia", "19": "Programa Fidelidade", "99": "Outros"}
            pagamentos.append((tmap.get(tpag, tpag or "Outros"), vpag))

        return {
            "chave": chave,
            "n_nf": n_nf,
            "serie": serie,
            "dhemi": dhemi,
            "cnpj": cnpj,
            "ie": ie,
            "nome": nome,
            "endereco": endereco,
            "fone": fone,
            "dest_cpf": dest_cpf,
            "dest_cnpj": dest_cnpj,
            "dest_nome": dest_nome,
            "itens": itens,
            "v_prod": v_prod,
            "v_desc": v_desc,
            "v_nf": v_nf,
            "v_tot_trib": v_tot_trib,
            "infcpl": infcpl,
            "url_chave": url_chave,
            "qr_code": qr_code,
            "pagamentos": pagamentos,
        }
    except Exception:
        return None


W = 80  # 80mm
H_PAG_CHEIA = 297  # altura da folha inteira (bobina termal)


def _render_conteudo_danfe(pdf, dados: dict) -> None:
    """Renderiza todo o conteúdo do DANFe no objeto PDF."""
    logo_h = 23
    logo_path = Path(__file__).parent / "logo.png"
    x_logo = 3
    x_emitente = x_logo + logo_h + 2
    w_emitente = W - x_emitente - 3

    pdf.set_font("Helvetica", "", 8)

    if logo_path.exists():
        try:
            pdf.image(str(logo_path), x=x_logo, y=3, w=logo_h, h=logo_h)
        except Exception:
            pass

    y_emit = 3
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_xy(x_emitente, y_emit)
    pdf.multi_cell(w_emitente, 4, dados["nome"], border=0, align="C")
    y_emit = pdf.get_y()
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(x_emitente, y_emit)
    pdf.multi_cell(w_emitente, 3, f"CNPJ: {_fmt_cnpj(dados['cnpj'])}", border=0, align="C")
    y_emit = pdf.get_y()
    if dados.get("ie"):
        pdf.set_xy(x_emitente, y_emit)
        pdf.multi_cell(w_emitente, 3, f"IE: {dados['ie']}", border=0, align="C")
        y_emit = pdf.get_y()
    for linha in dados["endereco"].split("\n"):
        if linha.strip():
            pdf.set_xy(x_emitente, y_emit)
            pdf.multi_cell(w_emitente, 3, linha.strip(), border=0, align="C")
            y_emit = pdf.get_y()
    if dados.get("fone"):
        pdf.set_xy(x_emitente, y_emit)
        pdf.multi_cell(w_emitente, 3, f"Fone: {_fmt_fone(dados['fone'])}", border=0, align="C")
        y_emit = pdf.get_y()
    pdf.set_font("Helvetica", "", 8)

    

    # Linha superior
    y_top = pdf.get_y()
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.4)
    pdf.set_dash_pattern(dash=2, gap=2)
    pdf.line(2, y_top, W - 2, y_top)
    pdf.set_dash_pattern()
    pdf.set_line_width(0.2)

    # Cabeçalho
    pdf.set_y(y_top + 1)
    pdf.set_font("Helvetica", "B", 8)
    pdf.multi_cell(W - 6, 4, "DANFE NFC-e: Documento Auxiliar da Nota Fiscal de Consumidor Eletrônica.", border=0, align="C")
    y_after_text = pdf.get_y()
    pdf.set_y(y_after_text + 1)

    # Linha inferior
    y_bottom = pdf.get_y()
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.4)
    pdf.set_dash_pattern(dash=2, gap=2)
    pdf.line(2, y_bottom, W - 2, y_bottom)
    pdf.set_dash_pattern()
    pdf.set_line_width(0.2)
    pdf.set_y(y_bottom + 1)

    # Itens (w_espaco = espaço entre descrição e QTD para evitar sobreposição)
    w_id, w_cod, w_desc = 4, 8, 18
    w_espaco = 3
    w_qtd, w_un, w_vun, w_vtot, w_desc_item = 6, 5, 10, 10, 8
    pdf.set_font("Helvetica", "B", 6)
    h_cell = 4
    pdf.cell(w_id, h_cell, "#", border=0)
    pdf.cell(w_cod, h_cell, "COD", border=0)
    pdf.cell(w_desc, h_cell, "DESCRICAO", border=0)
    pdf.cell(w_espaco, h_cell, "", border=0)
    pdf.cell(w_qtd, h_cell, "QTD", border=0)
    pdf.cell(w_un, h_cell, "UN", border=0)
    pdf.cell(w_vun, h_cell, "V_UNIT", border=0)
    pdf.cell(w_vtot, h_cell, "V_TOTAL", border=0, align="R")
    pdf.cell(w_desc_item, h_cell, "DESC.", border=0, align="R")
    pdf.ln(h_cell + 1)
    pdf.set_font("Helvetica", "", 6)
    for i, it in enumerate(dados["itens"], 1):
        cod = (it.get("cod") or str(i))[:6]
        desc = ((it.get("desc") or "")[:16] + " ")
        pdf.cell(w_id, h_cell, str(i), border=0)
        pdf.cell(w_cod, h_cell, cod, border=0)
        pdf.cell(w_desc, h_cell, desc, border=0)
        pdf.cell(w_espaco, h_cell, "", border=0)
        pdf.cell(w_qtd, h_cell, _fmt_valor(it.get("qtd", "")), border=0)
        pdf.cell(w_un, h_cell, (it.get("un") or "")[:3], border=0)
        pdf.cell(w_vun, h_cell, _fmt_valor(it.get("vun", "")), border=0)
        pdf.cell(w_vtot, h_cell, _fmt_valor(it.get("vprod", "")), border=0, align="R")
        pdf.cell(w_desc_item, h_cell, _fmt_valor(it.get("vdesc", "") or "0"), border=0, align="R")
        pdf.ln(h_cell + 1)
    pdf.set_font("Helvetica", "", 8)
    pdf.ln(0.5)
    pdf.linha()
    
    # Total de itens
    
    pdf.texto(f"QTD TOTAL DE ITENS: {len(dados['itens'])}")
    try:
        vdesc = float(dados["v_desc"].replace(",", "."))
        if vdesc > 0:
            pdf.texto(f" Total Desconto: R$ {vdesc:.2f}")
    except ValueError:
        pass
    pdf.texto(f"TOTAL: R$ {dados['v_nf']}", bold=True)
    pdf.ln(0.5)
    pdf.linha()

    # Destinatário
    if dados["dest_nome"] or dados["dest_cpf"] or dados["dest_cnpj"]:
        pdf.texto("CONSUMIDOR", bold=True)
        if dados["dest_cpf"]:
            pdf.texto(f"CPF: {_fmt_cpf(dados['dest_cpf'])}")
        if dados["dest_cnpj"]:
            pdf.texto(f"CNPJ: {_fmt_cnpj(dados['dest_cnpj'])}")
        if dados["dest_nome"]:
            pdf.texto(dados["dest_nome"][:50])
        pdf.ln(1)
        pdf.linha()

    # Forma de pagamento

    pdf.texto("FORMA DE PAGAMENTO", bold=True)
    for forma, valor in dados["pagamentos"]:
        pdf.texto(f"{forma}: R$ {valor}")
    pdf.ln(0.5)
    pdf.linha()

    # Informações complementares

    if dados["infcpl"]:
        pdf.set_font("Helvetica", "", 6)
        pdf.multi_cell(W - 6, 3, dados["infcpl"][:120], border=0, align="L")
        pdf.set_font("Helvetica", "", 8)
        pdf.ln(0.5)
    pdf.linha()

    # Chave de acesso

    ch = dados["chave"]
    if len(ch) >= 44:
        pdf.texto("CHAVE DE ACESSO:", bold=True)
        pdf.set_font("Helvetica", "", 6)
        for i in range(0, 44, 44):
            pdf.texto(ch[i : i + 44])
        pdf.set_font("Helvetica", "", 8)
    pdf.ln(0.5)
    pdf.texto(f"Serie: {dados['serie']}  Numero: {dados['n_nf']}", bold=True)
    pdf.texto(f"Data Hora Emissao: {dados['dhemi']}")

    # Consulta pela chave de acesso

    if dados["url_chave"]:
        pdf.texto("Consulta pela Chave de Acesso em:")
        pdf.set_font("Helvetica", "", 6)
        pdf.multi_cell(W - 6, 3, dados["url_chave"], border=0, align="L")
        pdf.set_font("Helvetica", "", 8)

    # QR Code

    if dados["qr_code"]:
        try:
            import qrcode
            qr = qrcode.QRCode(version=1, box_size=4, border=2)
            qr.add_data(dados["qr_code"])
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            qr_size = 50
            x = (W - qr_size) / 2
            pdf.ln(3)
            y_pos = pdf.get_y()
            pdf.image(buf, x=x, y=y_pos, w=qr_size, h=qr_size)
            pdf.set_y(y_pos + qr_size + 2)
        except (ImportError, Exception):
            pdf.ln(2)
            pdf.set_font("Helvetica", "", 6)
            pdf.cell(0, 4, "QR Code (instale qrcode[pil]):", ln=1, align="C")
            pdf.set_font("Helvetica", "", 5)
            pdf.multi_cell(W - 6, 3, dados["qr_code"], border=0, align="C")
            pdf.set_font("Helvetica", "", 8)

    pdf.linha()

    # Linha inferior
def gerar_pdf_danfe(dados: dict) -> bytes:
    """Gera PDF DANFe. Altura da página: exata se conteúdo < 297mm, folha inteira e continuação em mais páginas se maior."""
    try:
        from fpdf import FPDF
    except ImportError:
        raise ImportError("Instale fpdf2: pip install fpdf2")

    class PDF(FPDF):
        def __init__(self, formato_pagina: tuple):
            super().__init__(orientation="P", unit="mm", format=formato_pagina)
            self.set_margins(3, 3, 3)
            self.set_auto_page_break(False)

        def linha(self):
            self.set_draw_color(0)
            self.line(2, self.get_y(), W - 2, self.get_y())
            self.ln(1)

        def texto(self, txt, bold=False, size=8):
            self.set_font("Helvetica", "B" if bold else "", size)
            self.multi_cell(W - 6, 4, txt or "", border=0, align="L")
            self.ln(0.5)

    # Passagem 1: medir altura total do conteúdo (página muito alta, sem quebra)
    pdf_medir = PDF((W, 9999))
    pdf_medir.add_page()
    _render_conteudo_danfe(pdf_medir, dados)
    alt_total = pdf_medir.get_y() + 10

    # Passagem 2: gerar PDF final
    if alt_total <= H_PAG_CHEIA:
        pdf = PDF((W, alt_total))
        pdf.add_page()
    else:
        pdf = PDF((W, H_PAG_CHEIA))
        pdf.set_auto_page_break(True, 5)
        pdf.add_page()
    _render_conteudo_danfe(pdf, dados)
    return bytes(pdf.output())
