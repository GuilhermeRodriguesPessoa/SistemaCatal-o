import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libs'))

from http.server import SimpleHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse
from html import escape
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
import hashlib
import hmac
import json
import secrets
import threading
import unicodedata
import uuid
from plano_corte import conteudo_plano_corte, ICONE_PLANO, gerar_pdf_plano
import firebase_admin
from firebase_admin import credentials, firestore
import base64

# --- CONEXÃO COM O FIREBASE (VIA SECRET FILE DO RENDER) ---
db = None
try:
    # O Render coloca os Secret Files nesta pasta automaticamente
    caminho_chave = '/etc/secrets/firebase-key.json'
    
    if os.path.exists(caminho_chave):
        cred = credentials.Certificate(caminho_chave)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ SUCESSO: Conectado ao Firebase via Secret File!", flush=True)
    else:
        print("❌ ERRO: Arquivo firebase-key.json NÃO ENCONTRADO em /etc/secrets/", flush=True)
except Exception as e:
    print(f"❌ ERRO AO CONECTAR NO FIREBASE: {e}", flush=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "dados_marmoraria.json")
PDF_DIR = os.path.join(BASE_DIR, "PDF_Orcamentos")
LOGO_FILE = os.path.join(BASE_DIR, "logo.png")
os.makedirs(PDF_DIR, exist_ok=True)

os.makedirs(PDF_DIR, exist_ok=True)

def carregar_dados():
    vazio = {"clientes": [], "materiais": [], "orcamentos": [], "formas_pagamento": [], "recebimentos": [], "usuarios": [], "auditoria": []}
    if not db:
        return vazio
    try:
        print("📥 Lendo dados do Firestore...", flush=True)
        doc = db.collection('sistema').document('dados_gerais').get(timeout=15)
        print("📥 Leitura concluída.", flush=True)
        if doc.exists:
            dados = doc.to_dict()
            for chave in vazio:
                dados.setdefault(chave, [])
            return dados
        return vazio
    except Exception as e:
        print(f"❌ Erro ao carregar do Firebase: {e}", flush=True)
        return vazio

def salvar_dados():
    if not db:
        return
    try:
        db.collection('sistema').document('dados_gerais').set(dados_geral)
        print("Dados salvos no Firebase com sucesso!")
    except Exception as e:
        print(f"Erro ao salvar no Firebase: {e}")
    
dados_geral = carregar_dados()
banco_clientes = dados_geral["clientes"]
banco_materiais = dados_geral["materiais"]
banco_orcamentos = dados_geral["orcamentos"]
banco_formas_pagamento = dados_geral["formas_pagamento"]
banco_recebimentos = dados_geral["recebimentos"]
banco_usuarios = dados_geral["usuarios"]
banco_auditoria = dados_geral["auditoria"]
SESSOES = {}
NUMEROS_ORCAMENTO_RESERVADOS = set()
BLOQUEIO_NUMEROS_ORCAMENTO = threading.Lock()

ABAS = {
    '/orcamentos': 'Orçamentos',
    '/clientes': 'Clientes',
    '/historico': 'Histórico',
    '/materiais': 'Materiais',
    '/financeiro': 'Financeiro',
    '/funcionarios': 'Funcionários',
    '/gerencial': 'Modelo do PDF',
    '/plano': 'Plano de corte',
}

MODELO_PDF_PADRAO = {
    'cor_principal': '#101a2b',
    'cor_total': '#d8eaf5',
    'titulo_orcamento': 'ORÇAMENTO',
    'titulo_pedido': 'PEDIDO',
    'texto_liberacao': 'Liberação do pedido mediante a confirmação do pagamento.',
    'condicoes': [
        '1 - Mármores e granitos estão sujeitos a variações naturais de tonalidades e cores.',
        '2 - Pedidos mediante projeto podem sofrer alterações após medição local.',
        '3 - A conferência deve ser feita no ato da entrega; reclamações posteriores não serão aceitas.',
        '4 - A instalação dos materiais não está inclusa, sendo responsabilidade do comprador.',
        '5 - A marmoraria não faz rejuntamento.',
        '6 - Algumas peças deverão ser ajustadas no local pelo responsável instalador.',
        '7 - A empresa não trabalha com instalação de pedras.',
        '8 - Frete por conta do cliente - não incluso no valor da marmoraria.',
    ],
    'acessorios': [
        'Cubas, lixeiras, calha úmida, torre de tomadas e manual de churrasqueiras ou cooktop.',
        'Porcelanatos deverão ser entregues na marmoraria pelo cliente ou responsável pela obra.',
    ],
    'obra': ['Caso a obra necessite de acabamento em esquadria na bancada ou fechamentos, deverá ser agendado.'],
    'confirmacao': 'Confirmo que li as informações acima e concordo com a execução do serviço.',
    'empresa': 'CATALÃO MÁRMORES E GRANITOS',
    'cnpj': 'CNPJ: 10.446.296/0001-22',
}

def modelo_pdf():
    salvo = dados_geral.get('modelo_pdf') or {}
    return {**MODELO_PDF_PADRAO, **{chave: valor for chave, valor in salvo.items() if chave in MODELO_PDF_PADRAO and valor not in ('', [])}}

def cor_hex_rgb(cor):
    return tuple(int(cor[posicao:posicao + 2], 16) / 255 for posicao in (1, 3, 5))

def novo_id(prefixo):
    return f'{prefixo}-{uuid.uuid4().hex[:10].upper()}'

def novo_numero_orcamento(data=None):
    sufixo = (data or datetime.now()).strftime('.%d.%m.%y')
    with BLOQUEIO_NUMEROS_ORCAMENTO:
        existentes = [str(item.get('numero', '')) for item in banco_orcamentos]
        existentes.extend(NUMEROS_ORCAMENTO_RESERVADOS)
        partes = [numero.split('.') for numero in existentes]
        sequencias = [int(partes_numero[0]) for partes_numero in partes if len(partes_numero) == 4 and len(partes_numero[0]) >= 4 and partes_numero[0].isdigit() and all(len(parte) == 2 and parte.isdigit() for parte in partes_numero[1:])]
        numero = f'{max(sequencias, default=0) + 1:04d}{sufixo}'
        NUMEROS_ORCAMENTO_RESERVADOS.add(numero)
        return numero

def numero_orcamento_exibicao(orcamento):
    numero = str(orcamento.get('numero') or '')
    revisao = int(orcamento.get('revisao', 0) or 0)
    return f'{numero}.R{revisao}' if revisao > 0 else numero

def nome_pdf_orcamento(orcamento):
    nome = str(orcamento.get('cliente_nome') or 'Cliente')
    nome = ''.join(caractere if caractere.isalnum() or caractere in ' -_.' else ' ' for caractere in nome)
    nome = ' '.join(nome.split()).strip(' .')[:100] or 'Cliente'
    numero = ''.join(caractere for caractere in numero_orcamento_exibicao(orcamento) if caractere.isalnum() or caractere in '-_.')
    return f'{nome} - {numero}.pdf'

def criar_hash_senha(senha, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), bytes.fromhex(salt), 310000)
    return f'{salt}${digest.hex()}'

def validar_senha(senha, senha_hash):
    try:
        salt, digest = senha_hash.split('$', 1)
    except (AttributeError, ValueError):
        return False
    calculado = criar_hash_senha(senha, salt).split('$', 1)[1]
    return hmac.compare_digest(calculado, digest)

def registrar_auditoria(usuario, acao, entidade, entidade_id, detalhes=''):
    banco_auditoria.append({
        'id': novo_id('AUD'),
        'data_hora': datetime.now().isoformat(timespec='seconds'),
        'usuario_id': usuario.get('id') if usuario else None,
        'usuario_nome': usuario.get('nome', 'Sistema') if usuario else 'Sistema',
        'acao': acao,
        'entidade': entidade,
        'entidade_id': str(entidade_id),
        'detalhes': str(detalhes)[:500],
    })
    salvar_dados()

def usuario_da_requisicao(handler):
    cookies = SimpleCookie()
    try:
        cookies.load(handler.headers.get('Cookie', ''))
    except Exception:
        return None
    cookie = cookies.get('sessao')
    usuario_id = SESSOES.get(cookie.value) if cookie else None
    return next((usuario for usuario in banco_usuarios if usuario.get('id') == usuario_id), None)

def pode_acessar(usuario, rota, escrever=False):
    if not usuario:
        return False
    if rota == '/inicio':
        return not escrever
    if usuario.get('administrador'):
        return True
    nivel = usuario.get('permissoes', {}).get(rota, 'nenhum')
    return nivel == 'editar' if escrever else nivel in ('visualizar', 'editar')

def redirecionar(handler, local, limpar_sessao=False):
    handler.send_response(303)
    handler.send_header('Location', local)
    if limpar_sessao:
        handler.send_header('Set-Cookie', 'sessao=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')
    handler.end_headers()

def moeda(valor):
    return f"R$ {float(valor):,.2f}"

def preco_m2_acabamento(acabamento):
    if acabamento.get('unidade') == 'm² + linear':
        base = next((m for m in banco_materiais if m.get('id') == acabamento.get('material_base_id') and m.get('ativo', True)), None)
        if base:
            return float(base.get('preco_unitario', 0))
    return float(acabamento.get('preco_unitario', 0))

def preco_material_exibicao(material):
    unidade = material.get('unidade', 'm²')
    preco = moeda(preco_m2_acabamento(material))
    if unidade == 'm² + linear':
        return f"{preco}/m² (faixa {float(material.get('largura_m', 0)):.2f} m) + {moeda(material.get('preco_linear', 0))}/m"
    sufixo = {'m²': '/m²', 'metro linear': '/m', 'unidade': '/un.'}.get(unidade, '')
    return f'{preco}{sufixo}'

def carregar_logo_pdf():
    if not os.path.isfile(LOGO_FILE):
        return None
    import struct
    import zlib

    with open(LOGO_FILE, 'rb') as arquivo:
        dados = arquivo.read()
    if not dados.startswith(b'\x89PNG\r\n\x1a\n'):
        return None
    posicao = 8
    partes_idat = []
    largura = altura = profundidade = tipo_cor = None
    while posicao + 12 <= len(dados):
        tamanho = struct.unpack('>I', dados[posicao:posicao + 4])[0]
        tipo = dados[posicao + 4:posicao + 8]
        conteudo = dados[posicao + 8:posicao + 8 + tamanho]
        posicao += tamanho + 12
        if tipo == b'IHDR':
            largura, altura, profundidade, tipo_cor, _, _, _ = struct.unpack('>IIBBBBB', conteudo)
        elif tipo == b'IDAT':
            partes_idat.append(conteudo)
        elif tipo == b'IEND':
            break
    if profundidade != 8 or tipo_cor not in (2, 6) or not partes_idat:
        return None

    canais = 3 if tipo_cor == 2 else 4
    bytes_linha = largura * canais
    descomprimido = zlib.decompress(b''.join(partes_idat))
    linhas = []
    anterior = bytearray(bytes_linha)
    deslocamento = 0
    for _ in range(altura):
        filtro = descomprimido[deslocamento]
        deslocamento += 1
        linha = bytearray(descomprimido[deslocamento:deslocamento + bytes_linha])
        deslocamento += bytes_linha
        for indice in range(bytes_linha):
            esquerda = linha[indice - canais] if indice >= canais else 0
            acima = anterior[indice]
            acima_esquerda = anterior[indice - canais] if indice >= canais else 0
            if filtro == 1:
                linha[indice] = (linha[indice] + esquerda) & 255
            elif filtro == 2:
                linha[indice] = (linha[indice] + acima) & 255
            elif filtro == 3:
                linha[indice] = (linha[indice] + (esquerda + acima) // 2) & 255
            elif filtro == 4:
                estimativa = esquerda + acima - acima_esquerda
                distancia = [abs(estimativa - valor) for valor in (esquerda, acima, acima_esquerda)]
                preditor = (esquerda, acima, acima_esquerda)[distancia.index(min(distancia))]
                linha[indice] = (linha[indice] + preditor) & 255
            elif filtro != 0:
                return None
        linhas.append(linha)
        anterior = linha

    esquerda = round(largura * 0.04)
    direita = round(largura * 0.98)
    topo = round(altura * 0.24)
    base = round(altura * 0.69)
    largura_corte = direita - esquerda
    altura_corte = base - topo
    rgb = bytearray()
    for linha in linhas[topo:base]:
        for x in range(esquerda, direita):
            inicio = x * canais
            pixel = linha[inicio:inicio + canais]
            if canais == 4:
                alfa = pixel[3]
                rgb.extend((canal * alfa + 255 * (255 - alfa)) // 255 for canal in pixel[:3])
            else:
                rgb.extend(pixel)

    def bloco_png(nome, conteudo):
        return struct.pack('>I', len(conteudo)) + nome + conteudo + struct.pack('>I', zlib.crc32(nome + conteudo) & 0xffffffff)

    dados_png = b'\x89PNG\r\n\x1a\n'
    dados_png += bloco_png(b'IHDR', struct.pack('>IIBBBBB', largura_corte, altura_corte, 8, 2, 0, 0, 0))
    linhas_png = b''.join(b'\x00' + rgb[indice * largura_corte * 3:(indice + 1) * largura_corte * 3] for indice in range(altura_corte))
    dados_png += bloco_png(b'IDAT', zlib.compress(linhas_png)) + bloco_png(b'IEND', b'')
    return largura_corte, altura_corte, bytes(rgb), dados_png

def gerar_pdf_orcamento(orcamento):
    nome_arquivo = nome_pdf_orcamento(orcamento)
    caminho = os.path.join(PDF_DIR, nome_arquivo)

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from io import BytesIO

    largura_pagina, altura_pagina = A4
    margem = 35
    largura_tabela = largura_pagina - margem * 2
    modelo = modelo_pdf()
    azul_escuro = colors.HexColor(modelo['cor_principal'])
    azul_total = colors.HexColor(modelo['cor_total'])
    cinza_linha = colors.HexColor('#9da7b1')
    cinza_claro = colors.HexColor('#f5f7f9')
    p_styles = getSampleStyleSheet()
    logo_pdf = carregar_logo_pdf()
    texto = ParagraphStyle('TextoOrcamento', parent=p_styles['BodyText'], fontName='Helvetica', fontSize=8.5, leading=11, textColor=colors.black, spaceAfter=0)
    texto_centro = ParagraphStyle('TextoCentro', parent=texto, alignment=TA_CENTER)
    texto_direita = ParagraphStyle('TextoDireita', parent=texto, alignment=TA_RIGHT)
    valor_negrito = ParagraphStyle('ValorNegrito', parent=texto_direita, fontName='Helvetica-Bold', fontSize=9.5)
    titulo_secao = ParagraphStyle('TituloSecao', parent=texto_centro, fontName='Helvetica-Bold', fontSize=8.5, leading=10, textColor=colors.white)
    texto_condicao = ParagraphStyle('TextoCondicao', parent=texto, fontSize=7.6, leading=9.2)
    texto_assinatura = ParagraphStyle('TextoAssinatura', parent=texto_centro, fontName='Helvetica-Bold', fontSize=9)

    cliente = next((item for item in banco_clientes if item.get('id') == orcamento.get('cliente_id')), {})
    telefone = cliente.get('telefone') or orcamento.get('cliente_telefone') or '-'
    endereco = cliente.get('cidade') or orcamento.get('cliente_endereco') or '-'
    data_pedido = orcamento.get('data', '')
    try:
        data_pedido = datetime.strptime(data_pedido, '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        pass

    def paragrafo(valor, estilo=texto):
        return Paragraph(escape(str(valor or '-')).replace('\n', '<br/>'), estilo)

    def desenhar_cabecalho(can, doc):
        can.saveState()
        x = margem
        topo = altura_pagina - 28
        can.setStrokeColor(azul_escuro)
        can.setLineWidth(1)
        if logo_pdf:
            can.drawImage(ImageReader(BytesIO(logo_pdf[3])), x, topo - 42, width=139, height=40, preserveAspectRatio=True, anchor='sw')
        else:
            can.rect(x, topo - 31, largura_tabela, 31, stroke=1, fill=0)
            can.setStrokeColor(colors.HexColor('#d9ae32'))
            can.setLineWidth(2.5)
            simbolo_x = largura_pagina / 2 - 27
            for deslocamento in range(4):
                can.line(simbolo_x + deslocamento * 7, topo - 23, simbolo_x + 13 + deslocamento * 7, topo - 5)
        can.setFillColor(azul_escuro)
        can.rect(x, topo - 59, largura_tabela, 15, stroke=1, fill=1)
        can.setFillColor(colors.white)
        can.setFont('Helvetica-Bold', 9)
        titulo_documento = modelo['titulo_pedido'] if orcamento.get('aprovado') or orcamento.get('status') in ('Aprovado', 'Em produção', 'Concluído', 'Vendido') else modelo['titulo_orcamento']
        can.drawCentredString(largura_pagina / 2, topo - 55, titulo_documento)
        can.setFillColor(colors.black)
        can.setFont('Helvetica', 7)
        can.drawRightString(largura_pagina - margem, 18, f'Página {doc.page}')
        can.restoreState()

    story = [Spacer(1, 1 * mm)]
    rotulo_numero = 'Nº PEDIDO:' if orcamento.get('aprovado') or orcamento.get('status') in ('Aprovado', 'Em produção', 'Concluído', 'Vendido') else 'Nº ORÇAMENTO:'
    dados_cliente = [
        ['Cliente:', paragrafo(orcamento.get('cliente_nome'), texto), 'Telefone:', paragrafo(telefone, texto)],
        ['Endereço:', paragrafo(endereco, texto), rotulo_numero, Paragraph(f"<b>{escape(numero_orcamento_exibicao(orcamento) or '-')}</b>", texto)],
        ['Vendedor:', paragrafo(orcamento.get('vendedor') or '-', texto), 'Data:', paragrafo(data_pedido, texto)],
    ]
    tabela_cliente = Table(dados_cliente, colWidths=[58, 215, 75, largura_tabela - 348])
    tabela_cliente.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), azul_escuro),
        ('BACKGROUND', (2, 0), (2, -1), azul_escuro),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.white),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.white),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.7, azul_escuro),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.extend([tabela_cliente, Spacer(1, 5 * mm)])

    itens = orcamento.get('itens') or [{
        'descricao': orcamento.get('material_nome', 'Material'),
        'material_nome': orcamento.get('material_nome', 'Material'),
        'comprimento': orcamento.get('largura', 0),
        'largura': orcamento.get('altura', 0),
        'area_m2': float(orcamento.get('quantidade', 0)) if orcamento.get('unidade') == 'm²' else 0,
        'preco_material_m2': float(orcamento.get('valor_total', 0)) / max(float(orcamento.get('quantidade', 1)), 1),
        'valor_material': float(orcamento.get('valor_total', 0)),
        'acabamentos': [],
        'valor_total': float(orcamento.get('valor_total', 0)),
    }]
    linhas_itens = [[
        paragrafo('QUANT.', titulo_secao),
        paragrafo('DESCRIÇÃO / COMPOSIÇÃO', titulo_secao),
        paragrafo('MATERIAL / ACABAMENTO', titulo_secao),
        paragrafo('VALOR', titulo_secao),
    ]]
    for item in itens:
        comprimento = float(item.get('comprimento', 0) or 0)
        largura = float(item.get('largura', 0) or 0)
        area = float(item.get('area_m2', comprimento * largura) or 0)
        quantidade_pecas = int(item.get('quantidade_pecas', 1) or 1)
        descricao = f"<b>{escape(str(item.get('descricao', 'Item')))}</b>"
        descricao += f"<br/>Quantidade de peças iguais: {quantidade_pecas}"
        descricao += f"<br/>Área: {area:.2f} m² x {quantidade_pecas} = {area * quantidade_pecas:.2f} m²"
        if comprimento and largura:
            descricao += f"<br/>Medidas: {comprimento:.2f} m x {largura:.2f} m"
        if item.get('observacao_item'):
            descricao += f"<br/>Obs. da peça: {escape(str(item['observacao_item']))}"

        componentes = [
            f"<b>Material:</b> {escape(str(item.get('material_nome', 'Material')))}",
            f"<b>Valor m²:</b> {moeda(item.get('preco_material_m2', 0))}",
        ]
        if item.get('unidade_principal') == 'm² + linear':
            componentes = [f"<b>Acabamento principal:</b> {escape(str(item.get('material_nome', 'Acabamento')))}"]
            if item.get('material_base_nome'):
                componentes.append(f"<b>Material base:</b> {escape(str(item['material_base_nome']))}")
            componentes.extend([
                f"Área: {area:.2f} m² por peça x {quantidade_pecas} = {area * quantidade_pecas:.2f} m² x {moeda(item.get('preco_material_m2', 0))}/m² = {moeda(item.get('valor_material', 0))}",
                f"Linear: {comprimento:.2f} m por peça x {quantidade_pecas} = {comprimento * quantidade_pecas:.2f} m x {moeda(item.get('preco_linear_principal', 0))}/m = {moeda(item.get('valor_linear_principal', 0))}",
            ])
        acabamento_principal = ''
        for acabamento in item.get('acabamentos', []):
            unidade = acabamento.get('unidade', 'metro linear')
            nome_acabamento = str(acabamento.get('nome', 'Serviço'))
            if acabamento.get('auxiliar') and acabamento_principal:
                rotulo = f"Auxiliar de {acabamento_principal}: {nome_acabamento}"
            else:
                acabamento_principal = nome_acabamento
                rotulo = f"Acabamento: {nome_acabamento}"
            if unidade == 'm² + linear':
                area_acabamento = float(acabamento.get('quantidade_m2', 0))
                linear_acabamento = float(acabamento.get('quantidade_linear', 0))
                componentes.extend([
                    f"<b>{escape(rotulo)}</b> - {escape(str(acabamento.get('descricao', '')))}",
                    f"Área: {area_acabamento:.2f} m² por peça x {quantidade_pecas} = {area_acabamento * quantidade_pecas:.2f} m² ({moeda(acabamento.get('valor_m2', 0))})",
                    f"Linear: {linear_acabamento:.2f} m por peça x {quantidade_pecas} = {linear_acabamento * quantidade_pecas:.2f} m ({moeda(acabamento.get('valor_linear', 0))})",
                ])
            else:
                unidade_curta = {'m²': 'm²', 'metro linear': 'm', 'unidade': 'un.'}.get(unidade, unidade)
                medida_acabamento = float(acabamento.get('quantidade', 0))
                componentes.append(
                    f"<b>{escape(rotulo)}</b> - {escape(str(acabamento.get('descricao', '')))} "
                    f"({medida_acabamento:.2f} {escape(unidade_curta)} por peça x {quantidade_pecas} = {medida_acabamento * quantidade_pecas:.2f} {escape(unidade_curta)}) - {moeda(acabamento.get('valor_total', 0))}"
                )
        linhas_itens.append([
            paragrafo(str(quantidade_pecas), texto_centro),
            Paragraph(descricao, texto),
            Paragraph('<br/>'.join(componentes), texto),
            paragrafo(moeda(item.get('valor_total_com_gordura', item.get('valor_total', 0))), valor_negrito),
        ])

    larguras_coluna = [40, 142, 260, largura_tabela - 442]
    tabela_itens = Table(linhas_itens, colWidths=larguras_coluna, repeatRows=1, hAlign='LEFT')
    tabela_itens.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), azul_escuro),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.6, cinza_linha),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([tabela_itens, Spacer(1, 2 * mm)])

    linhas_totais = []
    if float(orcamento.get('desconto_valor', 0)) > 0:
        subtotal_pdf = orcamento.get('subtotal_com_gordura', orcamento.get('subtotal_itens', orcamento['valor_total']))
        linhas_totais.append([Paragraph('<b>SUBTOTAL:</b>', texto_direita), paragrafo(moeda(subtotal_pdf), valor_negrito)])
        linhas_totais.append([Paragraph(f"<b>DESCONTO {float(orcamento.get('desconto_percentual', 0)):g}%:</b>", texto_direita), paragrafo(f"-{moeda(orcamento['desconto_valor'])}", valor_negrito)])
    linhas_totais.append([Paragraph('<b>TOTAL:</b>', texto_direita), paragrafo(moeda(orcamento['valor_total']), valor_negrito)])
    total = Table(linhas_totais, colWidths=[largura_tabela - larguras_coluna[-1], larguras_coluna[-1]], hAlign='LEFT')
    estilo_totais = [
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f5f7f8')),
        ('BACKGROUND', (0, -1), (-1, -1), azul_total),
        ('BOX', (0, 0), (-1, -1), 0.5, cinza_linha),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('RIGHTPADDING', (0, 0), (0, -1), 16),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]
    if len(linhas_totais) > 1:
        estilo_totais.append(('LINEABOVE', (0, -1), (-1, -1), 0.5, cinza_linha))
    total.setStyle(TableStyle(estilo_totais))
    story.append(total)
    if str(orcamento.get('observacoes') or '').strip():
        observacoes = Table([[paragrafo(f"Observações gerais: {orcamento['observacoes']}", texto)]], colWidths=[largura_tabela], hAlign='LEFT')
        observacoes.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.7, azul_escuro), ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
        story.append(observacoes)
    story.append(Spacer(1, 5 * mm))

    def secao(texto_secao, linhas_secao):
        tabela = Table([[paragrafo(texto_secao, titulo_secao)]] + [[paragrafo(linha, texto_condicao)] for linha in linhas_secao], colWidths=[largura_tabela], repeatRows=1, hAlign='LEFT')
        tabela.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), azul_escuro),
            ('BACKGROUND', (0, 1), (-1, -1), cinza_claro),
            ('BOX', (0, 0), (-1, -1), 0.7, azul_escuro),
            ('INNERGRID', (0, 1), (-1, -1), 0.45, cinza_linha),
            ('ALIGN', (0, 0), (0, 0), 'CENTER'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        return tabela

    story.extend([
        Table([[Paragraph(f"Prazo de entrega: {int(orcamento.get('prazo_entrega_dias', 6))} dias", titulo_secao)], [paragrafo(modelo['texto_liberacao'], texto_condicao)]], colWidths=[largura_tabela], hAlign='LEFT', style=TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), azul_escuro), ('BOX', (0, 0), (-1, -1), 0.7, azul_escuro),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'), ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ])),
        Spacer(1, 5 * mm),
        secao('CONDIÇÕES DE VENDA', modelo['condicoes']),
        Spacer(1, 4 * mm),
        secao('ACESSÓRIOS A SEREM ENTREGUES', modelo['acessorios']),
        Spacer(1, 4 * mm),
        secao('ACABAMENTO EM OBRA', modelo['obra']),
        KeepTogether([
            Spacer(1, 9 * mm),
            paragrafo(modelo['confirmacao'], texto_centro),
            Spacer(1, 17 * mm),
            Table([[paragrafo(f"Cliente: {orcamento.get('cliente_nome', '')}", texto_assinatura), '', Paragraph(f"{escape(modelo['empresa'])}<br/>{escape(modelo['cnpj'])}", texto_assinatura)]], colWidths=[(largura_tabela - 24) / 2, 24, (largura_tabela - 24) / 2], hAlign='LEFT', style=TableStyle([
                ('LINEABOVE', (0, 0), (0, 0), 0.7, azul_escuro),
                ('LINEABOVE', (2, 0), (2, 0), 0.7, azul_escuro),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
            ])),
        ]),
    ])

    documento = SimpleDocTemplate(
        caminho,
        pagesize=A4,
        leftMargin=margem - 6,
        rightMargin=margem - 6,
        topMargin=altura_pagina - (altura_pagina - 28 - 59) + 12,
        bottomMargin=32,
        title=f"{orcamento.get('cliente_nome') or 'Cliente'} - {numero_orcamento_exibicao(orcamento)}",
        author='Catalão Mármores e Granitos Ltda',
    )
    documento.build(story, onFirstPage=desenhar_cabecalho, onLaterPages=desenhar_cabecalho)
    return caminho

ICONES = {
    '/inicio': '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    '/orcamentos': '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
    '/clientes': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.5 3-6 6.5-6s6.5 2.5 6.5 6"/><path d="M16 5a3.5 3.5 0 010 7M18 14c2.200.6 3.500 2.500 3.500 5"/>',
    '/historico': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    '/materiais': '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    '/financeiro': '<circle cx="12" cy="12" r="9"/><path d="M14.500 9.500c-.5-1-1.500-1.500-2.500-1.500-1.500 0-2.500.8-2.500 2s1 1.700 2.500 2 2.500.8 2.500 2-1 2-2.500 2c-1 0-2-.5-2.500-1.500M12 6v2M12 16v2"/>',
    '/funcionarios': '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.500-7 8-7s8 3 8 7"/>',
    '/gerencial': '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.500 6.500l4 4"/>',
}

ICONES['/plano'] = ICONE_PLANO

def icone_svg(rota):
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{ICONES.get(rota, "")}</svg>'

def pagina_base(aba_ativa, conteudo, usuario=None):
    itens_menu = [('/inicio', 'Início')] + [
        (rota, titulo) for rota, titulo in ABAS.items()
        if pode_acessar(usuario, rota) and (rota != '/funcionarios' or usuario.get('administrador'))
    ]
    menu = "".join(
        f'<a href="{rota}" class="aba {"ativa" if aba_ativa == rota else ""}">{icone_svg(rota)}<span>{titulo}</span></a>'
        for rota, titulo in itens_menu
    )
    sessao_usuario = ''
    if usuario:
        sessao_usuario = f'<span>{escape(usuario["nome"])}</span><form method="POST" action="/sair"><button class="sair" type="submit">Sair</button></form>'
    return f"""<!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="utf-8" />
        <title>Catalão Mármores e Granitos</title>
        <style>
            :root {{ color-scheme: light; --ink: #202b29; --muted: #71807c; --line: #e1e8e4; --canvas: #f4f6f5; --paper: #fff; --green: #276b58; --green-dark: #1d5143; --green-soft: #e8f2ed; --amber: #b77936; --shadow-soft: 0 8px 24px #1d342811; }}
            * {{ box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; min-height: 100vh; background: var(--canvas); color: var(--ink); -webkit-font-smoothing: antialiased; }}
            .app {{ min-height: 100vh; }}
            .sidebar {{ position: fixed; inset: 0 auto 0 0; z-index: 2; display: flex; flex-direction: column; width: 248px; padding: 26px 16px 18px; background: linear-gradient(155deg, #243a33, #1d302a 72%); color: #f6faf7; box-shadow: 8px 0 30px #15251e12; }}
            .marca {{ display: flex; align-items: center; gap: 12px; padding: 0 10px 28px; color: inherit; text-decoration: none; }}
            .marca-simbolo {{ display: grid; place-items: center; width: 42px; height: 42px; border: 1px solid #6b8c7f88; border-radius: 12px; background: #ffffff0a; color: #dce9e2; font-size: 13px; font-weight: 750; letter-spacing: 0; }}
            .marca-texto {{ display: grid; gap: 3px; }}
            .marca-texto strong {{ font-size: 14px; font-weight: 700; }}
            .marca-texto span {{ color: #a9beb4; font-size: 11px; }}
            .nav-titulo {{ padding: 0 11px 10px; color: #91a99d; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
            .menu-abas {{ display: grid; gap: 6px; }}
            .aba {{ display: flex; align-items: center; gap: 12px; min-height: 46px; padding: 0 14px; border-radius: 10px; color: #d5e1da; text-decoration: none; font-size: 13.5px; font-weight: 600; transition: background .15s ease, color .15s ease, transform .15s ease; }}
            .aba svg {{ width: 20px; height: 20px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }}
            .aba:hover {{ background: #2c473d; color: #fff; transform: translateX(3px); }}
            .aba.ativa {{ background: #f1f6f3; color: var(--green-dark); box-shadow: inset 3px 0 0 #d2ab66, 0 3px 10px #10201918; }}
            .sidebar-rodape {{ margin-top: auto; padding: 16px 10px 0; border-top: 1px solid #ffffff20; color: #a9beb4; font-size: 11px; line-height: 1.55; }}
            .sidebar-rodape span {{ display: block; margin-bottom: 5px; color: #dce9e2; font-weight: 700; }}
            .assinatura-marmorify {{ display: grid; gap: 1px; margin-top: 16px; opacity: .72; }}
            .assinatura-marmorify strong {{ color: #e4ece7; font-size: 11px; font-weight: 600; letter-spacing: .2px; }}
            .assinatura-marmorify small {{ color: #a9beb4; font-size: 9px; font-weight: 400; }}
            .principal {{ min-height: 100vh; margin-left: 248px; }}
            .topo {{ position: sticky; top: 0; z-index: 1; display: flex; align-items: center; justify-content: space-between; min-height: 78px; padding: 14px 34px; border-bottom: 1px solid #dfe6e2cc; background: #ffffffed; backdrop-filter: blur(16px); }}
            .topo-titulo {{ display: grid; gap: 4px; }}
            .logo-topo {{ display: block; width: 220px; height: 65px; object-fit: contain; object-position: left center; mix-blend-mode: multiply; }}
            .logo-login {{ display: block; width: min(100%, 320px); height: auto; margin: 0 auto 16px; object-fit: contain; mix-blend-mode: multiply; }}
            .login-panel {{ max-width: 480px; margin: 0 auto; }}
            .topo-titulo span {{ color: var(--muted); font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
            .topo-titulo strong {{ font-size: 15px; font-weight: 650; }}
            .topo-meta {{ display: flex; align-items: center; gap: 18px; color: var(--muted); font-size: 12px; }}
            .topo-meta form {{ display: inline; }}
            .topo-meta .sair {{ width: auto; min-height: 30px; padding: 5px 10px; border: 1px solid var(--line); background: #fff; color: var(--ink); font-size: 12px; }}
            .indicador {{ display: flex; align-items: center; gap: 7px; color: #47735d; font-weight: 600; }}
            .indicador::before {{ width: 7px; height: 7px; border-radius: 50%; background: #54a477; content: ''; }}
            .conteudo {{ max-width: 1500px; margin: 0 auto; padding: 32px 34px 48px; }}
            h1, h2, h3, h4 {{ margin-top: 0; color: var(--ink); }}
            h2 {{ margin-bottom: 22px; font-size: 24px; font-weight: 650; }}
            h3 {{ margin-bottom: 16px; font-size: 15px; font-weight: 650; }}
            .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin: 20px 0 24px; }}
            .card {{ min-width: 0; padding: 18px; border: 1px solid #e4eae7; border-top: 2px solid var(--green); border-radius: 12px; background: var(--paper); box-shadow: 0 3px 12px #1d342808; }}
            .card strong {{ display: block; margin-top: 10px; color: var(--green-dark); font-size: 22px; font-weight: 700; }}
            .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
            .panel {{ min-width: 0; overflow-x: auto; padding: 20px; border: 1px solid #e5ebe8; border-radius: 12px; background: var(--paper); box-shadow: 0 3px 14px #1d342808; }}
            .busca-cadastro {{ display: grid; grid-template-columns: minmax(0, 480px); align-items: end; gap: 10px; margin: 0 0 16px; }}
            .busca-cadastro [data-resultado-filtro] {{ grid-column: 1 / -1; }}
            .busca-cadastro button {{ width: auto; min-width: 110px; }}
            .ordem-historico {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 16px; }}
            .ordem-historico label {{ margin: 0; }}
            .ordem-historico select, .ordem-historico button {{ width: auto; max-width: 100%; }}
            .auditoria {{ margin-top: 18px; }}
            .auditoria > summary {{ color: var(--ink); cursor: pointer; font-size: 15px; font-weight: 650; list-style-position: inside; }}
            .auditoria[open] > summary {{ margin-bottom: 10px; }}
            form {{ display: grid; gap: 12px; }}
            .linha {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
            label {{ display: block; margin-bottom: 6px; color: #455550; font-size: 12px; font-weight: 650; }}
            input, select, textarea, button {{ width: 100%; padding: 10px 12px; border: 1px solid #d8e0dc; border-radius: 8px; background: #fff; color: var(--ink); font: inherit; font-size: 14px; }}
            input, select, textarea {{ min-height: 42px; transition: border-color .16s ease, box-shadow .16s ease, background .16s ease; }}
            input:focus, select:focus, textarea:focus {{ outline: none; border-color: #6da58a; box-shadow: 0 0 0 3px #276b581c; }}
            textarea {{ min-height: 100px; resize: vertical; }}
            button {{ min-height: 40px; border: 0; border-radius: 9px; background: var(--green); color: #fff; font-weight: 650; cursor: pointer; transition: background .15s ease, transform .15s ease, box-shadow .15s ease; }}
            button:hover {{ background: var(--green-dark); box-shadow: 0 4px 12px #1d514322; }}
            button:active {{ transform: scale(.985); }}
            button:focus-visible, a:focus-visible, summary:focus-visible {{ outline: 3px solid #78ad91; outline-offset: 2px; }}
            button.secondary {{ background: #537b69; }}
            button.warning {{ background: var(--amber); }}
            table {{ width: 100%; min-width: 520px; margin-top: 10px; border-collapse: collapse; font-size: 13px; }}
            th, td {{ padding: 12px 11px; border-bottom: 1px solid #e8eeeb; text-align: left; vertical-align: top; }}
            th {{ background: #f5f7f6; color: #5d6c66; font-size: 11px; font-weight: 700; white-space: nowrap; }}
            tbody tr:hover td {{ background: #f8faf9; }}
            tr:last-child td {{ border-bottom: 0; }}
            a.link {{ color: var(--green); text-decoration: none; font-weight: 650; }}
            a.link:hover {{ text-decoration: underline; }}
            .status {{ display: inline-block; padding: 4px 9px; border-radius: 4px; font-size: 11px; font-weight: 700; white-space: nowrap; }}
            .status-em-analise {{ background: #fff1d8; color: #91601d; }}
            .status-aprovado {{ background: #e5f2e9; color: #376a49; }}
            .status-vendido {{ background: #e6eef2; color: #426577; }}
            .status-recusado {{ background: #f8e8e5; color: #9a4c40; }}
            .muted {{ color: var(--muted); }}
            @media (max-width: 900px) {{
                .sidebar {{ width: 210px; }}
                .principal {{ margin-left: 210px; }}
                .topo {{ padding-right: 24px; padding-left: 24px; }}
                .conteudo {{ padding: 26px 24px 40px; }}
                .grid {{ grid-template-columns: 1fr; }}
            }}
            @media (max-width: 640px) {{
                .sidebar {{ position: static; width: auto; padding: 14px 14px 12px; }}
                .marca {{ padding: 0 4px 14px; }}
                .nav-titulo {{ display: none; }}
                .sidebar-rodape {{ display: block; margin-top: 8px; padding: 8px 6px 0; border-top: 1px solid #ffffff20; }}
                .assinatura-marmorify {{ display: inline-grid; margin: 6px 0 0 10px; vertical-align: top; }}
                .menu-abas {{ display: flex; gap: 4px; overflow-x: auto; padding-bottom: 2px; }}
                .aba {{ min-height: 36px; padding: 0 10px; white-space: nowrap; font-size: 12px; }}
                .principal {{ margin-left: 0; }}
                .topo {{ min-height: 64px; padding: 12px 18px; }}
                .topo-meta {{ gap: 0; }}
                .indicador {{ display: none; }}
                .conteudo {{ padding: 24px 16px 36px; }}
                h2 {{ font-size: 21px; }}
                .panel {{ padding: 15px; }}
                .busca-cadastro {{ grid-template-columns: 1fr auto; }}
                .cards {{ grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 10px; }}
                .card {{ padding: 14px; }}
                .card strong {{ font-size: 19px; }}
            }}
        </style>
    </head>
    <body>
        <div class="app">
            <aside class="sidebar">
                <a class="marca" href="/inicio">
                    <span class="marca-simbolo">CMG</span>
                    <span class="marca-texto"><strong>Catalão Mármores e Granitos</strong><span>Sistema de gestão</span></span>
                </a>
                <div class="nav-titulo">GESTÃO</div>
                <nav class="menu-abas" aria-label="Navegação principal">{menu}</nav>
                <div class="assinatura-marmorify"><strong>Marmorify</strong><small>by Guilherme R. Pessoa</small></div>
            </aside>
            <main class="principal">
                <header class="topo">
                    <div class="topo-titulo"><img src="/logo.png" alt="Catalão Mármores e Granitos" class="logo-topo"><strong>Gestão de operações</strong></div>
                    <div class="topo-meta"><span class="indicador">Sistema ativo</span>{sessao_usuario}<time>{datetime.now().strftime('%d/%m/%Y')}</time></div>
                </header>
                <section class="conteudo">{conteudo}</section>
            </main>
        </div>
        <style>
            .action-backdrop {{ display:none; position:fixed; inset:0; z-index:90; background:#18231e88; backdrop-filter:blur(2px); }}
            .action-backdrop.visible {{ display:block; }}
            details > .acoes-menu {{ display:none !important; }}
            details[open] > .acoes-menu {{ display:block !important; position:fixed !important; z-index:91 !important; top:50% !important; left:50% !important; right:auto !important; transform:translate(-50%,-50%) !important; width:min(520px,calc(100vw - 28px)) !important; max-height:84vh !important; overflow:auto !important; padding:0 16px 16px !important; border:1px solid #d4ded9; border-radius:10px; background:#fff; box-shadow:0 24px 70px #10201955; }}
            .action-menu-head {{ position:sticky; top:0; z-index:2; display:flex; align-items:center; justify-content:space-between; gap:16px; margin:0 -16px 14px; padding:16px; border-bottom:1px solid var(--line); background:#fff; }}
            .action-menu-head strong {{ overflow-wrap:anywhere; color:var(--ink); font-size:15px; }}
            .action-menu-close {{ flex:none; width:36px; min-height:36px; padding:0; border-radius:8px; background:#edf2ef; color:var(--ink); font-size:23px; line-height:1; }}
            .action-menu-close:hover {{ background:#dfe9e3; color:var(--ink); }}
            .action-menu-head + form {{ margin-top:0; }}
        </style>
        <script>
            (() => {{
                const fundo = document.createElement('div');
                fundo.className = 'action-backdrop';
                document.body.append(fundo);
                const fecharTudo = () => {{
                    document.querySelectorAll('details[open] > .acoes-menu').forEach(menu => {{ menu.parentElement.open = false; }});
                    fundo.classList.remove('visible');
                    document.body.style.overflow = '';
                }};
                document.querySelectorAll('details > .acoes-menu').forEach(menu => {{
                    const details = menu.parentElement;
                    const linha = details.closest('tr');
                    const celulas = linha ? linha.querySelectorAll(':scope > td') : [];
                    const nomeEdicao = menu.querySelector('input[name="nome"]')?.value;
                    const nomeHistorico = linha?.querySelector('td:nth-child(6) .status') ? `${{celulas[0]?.textContent.trim()}} · ${{celulas[1]?.textContent.trim()}}` : '';
                    const nome = details.dataset.titulo || nomeEdicao || nomeHistorico || (details.closest('.grupo-cadastro') ? celulas[2]?.textContent : celulas[0]?.textContent) || '';
                    const titulo = details.querySelector(':scope > summary')?.textContent.trim() || 'Ações';
                    const cabecalho = document.createElement('div');
                    cabecalho.className = 'action-menu-head';
                    const texto = document.createElement('strong');
                    texto.textContent = titulo.startsWith('Orçamentos') ? `Orçamentos de ${{nome.trim()}}` : `${{titulo}}${{nome.trim() ? `: ${{nome.trim()}}` : ''}}`;
                    const fechar = document.createElement('button');
                    fechar.type = 'button';
                    fechar.className = 'action-menu-close';
                    fechar.title = 'Fechar';
                    fechar.setAttribute('aria-label', 'Fechar ações');
                    fechar.textContent = '×';
                    fechar.addEventListener('click', fecharTudo);
                    cabecalho.append(texto, fechar);
                    menu.prepend(cabecalho);
                    details.addEventListener('toggle', () => {{
                        if (details.open) {{
                            document.querySelectorAll('details[open] > .acoes-menu').forEach(outro => {{ if (outro !== menu) outro.parentElement.open = false; }});
                            fundo.classList.add('visible');
                            document.body.style.overflow = 'hidden';
                            fechar.focus();
                        }} else if (!document.querySelector('details[open] > .acoes-menu')) {{
                            fundo.classList.remove('visible');
                            document.body.style.overflow = '';
                        }}
                    }});
                }});
                fundo.addEventListener('click', fecharTudo);
                document.addEventListener('keydown', evento => {{ if (evento.key === 'Escape') fecharTudo(); }});
            }})();
            (() => {{
                const normalizar = texto => texto.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLocaleLowerCase('pt-BR');
                document.querySelectorAll('[data-filtro-local]').forEach(campo => {{
                    const alvos = [...document.querySelectorAll(campo.dataset.filtroLocal)];
                    if (!alvos.length) return;
                    let resultado = campo.parentElement.querySelector('[data-resultado-filtro]');
                    if (!resultado) {{
                        resultado = document.createElement('small');
                        resultado.className = 'muted';
                        resultado.setAttribute('data-resultado-filtro', '');
                        resultado.setAttribute('aria-live', 'polite');
                        campo.parentElement.append(resultado);
                    }}
                    const filtrar = () => {{
                        const termo = normalizar(campo.value.trim());
                        let visiveis = 0;
                        alvos.forEach(alvo => {{
                            [...alvo.querySelectorAll('tr')].forEach(linha => {{
                                if (!linha.querySelector(':scope > td') || linha.querySelector(':scope > td[colspan]')) return;
                                const texto = [...linha.cells].filter(celula => !celula.querySelector('details')).map(celula => celula.innerText).join(' ');
                                linha.hidden = termo !== '' && !normalizar(texto).includes(termo);
                                if (!linha.hidden) visiveis++;
                            }});
                        }});
                        resultado.textContent = termo && visiveis === 0 ? 'Nenhum resultado encontrado' : `${{visiveis}} resultado(s)`;
                    }};
                    campo.addEventListener('input', filtrar);
                    filtrar();
                }});
            }})();
        </script>
    </body>
    </html>
    """

def orcamentos_do_cliente_html(cliente):
    lista = [o for o in banco_orcamentos if o.get('cliente_id') == cliente['id'] and o.get('ativo', True)]
    itens = ''.join(
        f"<div><a class='link' href='/emitir_orcamento?id={escape(o['numero'])}'>{escape(o['numero'])}</a> - {moeda(o.get('valor_total', 0))} - {escape(o.get('status', 'Em análise'))}</div>"
        for o in sorted(lista, key=lambda o: o.get('data', ''), reverse=True)
    ) or "<div class='muted'>Nenhum orçamento.</div>"
    return f"<details data-titulo='{escape(cliente['nome'])}'><summary>Orçamentos ({len(lista)})</summary><div class='acoes-menu'>{itens}<p><a class='link' href='/orcamentos?cliente={escape(cliente['id'])}'>+ Novo orçamento</a></p></div></details>"

def renderizar_clientes(usuario=None, busca=''):
    linhas = "".join(
        f"<tr><td>{escape(cliente['nome'])}</td><td>{escape(cliente.get('telefone', '-'))}</td><td>{escape(cliente.get('endereco', cliente.get('cidade', '-')))}</td><td>{escape(cliente.get('observacoes', '-'))}</td><td>{orcamentos_do_cliente_html(cliente)}</td><td><details><summary>Ações</summary><div class='acoes-menu'><form method='POST' action='/alterar_cliente'><input type='hidden' name='id' value='{escape(cliente['id'])}'><label>Nome</label><input name='nome' value='{escape(cliente['nome'])}' required><label>Telefone</label><input name='telefone' value='{escape(cliente.get('telefone', ''))}'><label>Endereço</label><input name='endereco' value='{escape(cliente.get('endereco', cliente.get('cidade', '')))}'><label>Observações</label><input name='observacoes' value='{escape(cliente.get('observacoes', ''))}'><button type='submit'>Salvar alterações</button></form><form method='POST' action='/excluir_cliente' onsubmit='return confirm(\"Excluir este cliente?\")'><input type='hidden' name='id' value='{escape(cliente['id'])}'><button class='warning' type='submit'>Excluir cliente</button></form></div></details></td></tr>"
        for cliente in banco_clientes if cliente.get('ativo', True) and busca.casefold() in cliente.get('nome', '').casefold()
    ) or '<tr><td colspan="6" class="muted">Nenhum cliente cadastrado.</td></tr>'

    if not pode_acessar(usuario, '/clientes', escrever=True):
        linhas_leitura = ''.join(
            f"<tr><td>{escape(cliente.get('nome', ''))}</td><td>{escape(cliente.get('telefone', '-'))}</td><td>{escape(cliente.get('endereco', cliente.get('cidade', '-')))}</td><td>{escape(cliente.get('observacoes', '-'))}</td></tr>"
            for cliente in banco_clientes if cliente.get('ativo', True) and busca.casefold() in cliente.get('nome', '').casefold()
        ) or '<tr><td colspan="4" class="muted">Nenhum cliente cadastrado.</td></tr>'
        return pagina_base('/clientes', f"<h2>Clientes</h2><div class='busca-cadastro'><input type='search' data-filtro-local='#lista-clientes' value='{escape(busca)}' placeholder='Buscar por nome, telefone ou endereço'></div><div class='panel'><table id='lista-clientes'><tr><th>Nome</th><th>Telefone</th><th>Endereço</th><th>Observações</th></tr>{linhas_leitura}</table></div>", usuario)

    return pagina_base(
        "/clientes",
        f"""
        <style>.acoes-menu {{ position:absolute; z-index:3; right:0; min-width:260px; padding:12px; border:1px solid #d4ded9; border-radius:6px; background:#fff; box-shadow:0 8px 24px #18231e22; }} details {{ position:relative; }} .acoes-menu form {{ margin-bottom:10px; }} .acoes-menu form:last-child {{ margin-bottom:0; }}</style>
        <h2>Cadastro de clientes</h2>
        <div class="busca-cadastro"><input type="search" data-filtro-local="#lista-clientes" value="{escape(busca)}" placeholder="Buscar por nome, telefone ou endereço"></div>
        <div class="grid">
            <div class="panel">
                <form method="POST" action="/salvar_cliente">
                    <div class="linha">
                        <div><label>Nome</label><input type="text" name="nome" required></div>
                        <div><label>Telefone</label><input type="text" name="telefone"></div>
                    </div>
                    <div class="linha">
                        <div><label>Endereço</label><input type="text" name="endereco"></div>
                        <div><label>Observações</label><input type="text" name="observacoes"></div>
                    </div>
                    <button type="submit">Salvar cliente</button>
                </form>
            </div>
            <div class="panel">
                <h3>Lista de clientes</h3>
                <table id="lista-clientes">
                    <tr><th>Nome</th><th>Telefone</th><th>Endereço</th><th>Observações</th><th>Orçamentos</th><th>Ações</th></tr>
                    {linhas}
                </table>
            </div>
        </div>
        """,
        usuario,
    )

def renderizar_materiais(usuario=None, busca=''):
    def opcoes_base(selecionado=''):
        return "<option value=''>Selecione o material...</option>" + ''.join(
            f"<option value='{escape(m['id'])}' {'selected' if m['id'] == selecionado else ''}>{escape(m['nome'])} - {moeda(m['preco_unitario'])}/m²</option>"
            for m in banco_materiais if m.get('ativo', True) and m.get('tipo', 'material') == 'material'
        )

    ativos = [
        item for item in banco_materiais
        if item.get('ativo', True) and busca.casefold() in item.get('nome', '').casefold()
    ]
    linhas = {'material': [], 'acabamento': [], 'servico': []}
    for material in ativos:
        unidade_atual = material.get('unidade', 'm²')
        opcoes_unidade = ''.join(
            f"<option value='{unidade}' {'selected' if unidade_atual == unidade else ''}>{rotulo}</option>"
            for unidade, rotulo in [('m²', 'm²'), ('metro linear', 'Metro linear'), ('unidade', 'Unidade'), ('m² + linear', 'm² + metro linear')]
        )
        opcoes_tipo = ''.join(
            f"<option value='{tipo}' {'selected' if material.get('tipo', 'material') == tipo else ''}>{rotulo}</option>"
            for tipo, rotulo in [('material', 'Material'), ('acabamento', 'Acabamento'), ('servico', 'Serviço')]
        )
        tipo_texto = {'acabamento': 'Acabamento', 'servico': 'Serviço'}.get(material.get('tipo'), 'Material')
        tipo_key = material.get('tipo', 'material') if material.get('tipo') in linhas else 'material'
        linhas[tipo_key].append(f"""
            <tr><td>{tipo_texto}</td><td>{escape(material.get('codigo', ''))}</td><td>{escape(material.get('nome', ''))}</td>
            <td>{escape(material.get('categoria', ''))}</td><td>{escape(unidade_atual)}</td><td>{preco_material_exibicao(material)}</td>
            <td><details><summary>Ações</summary><div class='acoes-menu'>
                <form method='POST' action='/alterar_material'>
                    <input type='hidden' name='id' value='{escape(material['id'])}'>
                    <label>Tipo</label><select name='tipo'>{opcoes_tipo}</select>
                    <label>Código</label><input name='codigo' value='{escape(material.get('codigo', ''))}' required>
                    <label>Nome</label><input name='nome' value='{escape(material.get('nome', ''))}' required>
                    <label>Categoria</label><input name='categoria' value='{escape(material.get('categoria', ''))}' required>
                    <label>Unidade</label><select name='unidade'>{opcoes_unidade}</select>
                    <div class='so-simples'><label>Preço por m²/unidade principal</label><input type='number' min='0' step='0.01' name='preco_unitario' value='{float(material.get('preco_unitario', 0)):.2f}'></div>
                    <div class='so-combinado' hidden>
                        <label>Material base (usa o valor do m² dele)</label><select name='material_base_id'>{opcoes_base(material.get('material_base_id', ''))}</select>
                        <label>Largura da faixa (m) - ex.: 0,10</label><input type='number' min='0' step='0.01' name='largura_m' value='{float(material.get('largura_m', 0)):.2f}'>
                        <label>Preço por metro linear</label><input type='number' min='0' step='0.01' name='preco_linear' value='{float(material.get('preco_linear', 0)):.2f}'>
                    </div>
                    <label><input type='checkbox' name='permite_auxiliar' value='1' style='width:auto' {'checked' if material.get('permite_auxiliar') else ''}> Permite acabamento auxiliar no orçamento</label>
                    <button type='submit'>Salvar alterações</button>
                </form>
                <form method='POST' action='/excluir_material' onsubmit='return confirm(\"Excluir este cadastro?\")'>
                    <input type='hidden' name='id' value='{escape(material['id'])}'><button class='warning' type='submit'>Excluir</button>
                </form>
            </div></details></td></tr>
        """)
    def tabela_tipo(chave, titulo, detalhe):
        linhas_tipo = ''.join(linhas[chave]) or '<tr><td colspan="7" class="muted">Nenhum cadastro neste grupo.</td></tr>'
        return f"<section class='grupo-cadastro grupo-{chave}'><header><span>{titulo}</span><small>{detalhe}</small></header><table><tr><th>Tipo</th><th>Código</th><th>Nome</th><th>Categoria</th><th>Unidade</th><th>Preço</th><th>Ações</th></tr>{linhas_tipo}</table></section>"

    if not pode_acessar(usuario, '/materiais', escrever=True):
        linhas_leitura = ''.join(
            f"<tr><td>{escape(item.get('codigo', ''))}</td><td>{escape(item.get('nome', ''))}</td><td>{escape(item.get('categoria', ''))}</td><td>{escape(item.get('unidade', 'm²'))}</td><td>{preco_material_exibicao(item)}</td></tr>"
            for item in ativos
        ) or '<tr><td colspan="5" class="muted">Nenhum material cadastrado.</td></tr>'
        return pagina_base('/materiais', f"<h2>Materiais</h2><div class='busca-cadastro'><input type='search' data-filtro-local='#lista-materiais' value='{escape(busca)}' placeholder='Buscar por código, nome ou categoria'></div><div class='panel'><table id='lista-materiais'><tr><th>Código</th><th>Nome</th><th>Categoria</th><th>Unidade</th><th>Preço</th></tr>{linhas_leitura}</table></div>", usuario)

    opcoes_unidade_novo = ''.join(
        f"<option value='{unidade}'>{rotulo}</option>"
        for unidade, rotulo in [('m²', 'Metro quadrado (m²)'), ('metro linear', 'Metro linear (m)'), ('unidade', 'Unidade'), ('m² + linear', 'm² + metro linear')]
    )
    return pagina_base('/materiais', f"""
        <style>
            .materiais-layout {{ display:grid; grid-template-columns:minmax(300px,.8fr) minmax(500px,1.5fr); gap:18px; align-items:start; }}
            .cadastro-form {{ padding:20px; border-top:4px solid var(--green); }}
            .cadastro-form h3 {{ margin:0 0 16px; }}
            .grupo-cadastro {{ margin-bottom:16px; overflow:hidden; border:1px solid var(--line); border-radius:8px; background:#fff; }}
            .grupo-cadastro header {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:12px 14px; background:#edf3ef; border-bottom:1px solid var(--line); }}
            .grupo-cadastro header span {{ font-weight:700; }} .grupo-cadastro header small {{ color:var(--muted); }}
            .grupo-acabamento header {{ background:#fff3e2; }} .grupo-servico header {{ background:#eaf2f8; }}
            .grupo-cadastro table {{ margin:0; }}
            .tipo-cadastro {{ display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin:8px 0 16px; padding:5px; border:1px solid var(--line); border-radius:8px; background:#f3f6f4; }}
            .tipo-cadastro label {{ margin:0; padding:9px 5px; border-radius:6px; text-align:center; cursor:pointer; font-weight:700; }}
            .tipo-cadastro input {{ width:auto; margin:0 4px 0 0; }}
            .campos-tipo {{ padding:14px; margin:12px 0; border-radius:7px; background:#f7f9f8; border-left:4px solid var(--green); }}
            .campos-tipo[hidden] {{ display:none; }}
            .campos-acabamento {{ border-left-color:var(--amber); background:#fff9ef; }} .campos-servico {{ border-left-color:#3b7ea1; background:#f1f7fb; }}
            .acoes-menu {{ position:absolute; z-index:3; right:0; min-width:280px; max-height:70vh; overflow:auto; padding:12px; border:1px solid #d4ded9; border-radius:6px; background:#fff; box-shadow:0 8px 24px #18231e22; }} .grupo-cadastro .acoes-menu {{ position:fixed; z-index:50; top:12vh; right:20px; width:min(420px, calc(100vw - 32px)); max-height:76vh; }} details {{ position:relative; }} .acoes-menu form {{ margin-bottom:10px; }} .acoes-menu form:last-child {{ margin-bottom:0; }}
            @media(max-width:1000px) {{ .materiais-layout {{ grid-template-columns:1fr; }} }}
        </style>
        <h2>Cadastro de materiais e acabamentos</h2>
        <div class='busca-cadastro'><input type='search' data-filtro-local='.grupo-cadastro table' value='{escape(busca)}' placeholder='Buscar por código, nome ou categoria'></div>
        <div class='materiais-layout'><div class='panel cadastro-form'><h3>Novo cadastro</h3><form method='POST' action='/salvar_material'>
            <label>Tipo de cadastro</label><div class='tipo-cadastro'><label><input type='radio' name='tipo' value='material' checked>Material</label><label><input type='radio' name='tipo' value='acabamento'>Acabamento</label><label><input type='radio' name='tipo' value='servico'>Serviço</label></div>
            <div class='linha'><div><label>Código</label><input name='codigo' required></div><div><label>Nome</label><input name='nome' required></div></div>
            <div><label>Categoria</label><input name='categoria' required></div>
            <div class='campos-tipo campos-material'><h4>Material</h4><label>Unidade de cobrança</label><input value='Metro quadrado (m²)' readonly><input type='hidden' name='unidade_material' value='m²'><label>Preço por m²</label><input type='number' min='0' step='0.01' name='preco_material' value='0'></div>
            <div class='campos-tipo campos-acabamento' hidden><h4>Acabamento</h4><label>Unidade de cobrança</label><select name='unidade_acabamento'>{opcoes_unidade_novo}</select><div class='so-simples'><label>Preço principal</label><input type='number' min='0' step='0.01' name='preco_unitario' value='0'></div><div class='so-combinado' hidden>
                <label>Material base (usa o valor do m² dele)</label><select name='material_base_id'>{opcoes_base()}</select>
                <label>Largura da faixa (m) - ex.: 0,10</label><input type='number' min='0' step='0.01' name='largura_m' value='0'>
                <div><label>Preço por metro linear</label><input type='number' min='0' step='0.01' name='preco_linear' value='0'></div>
            </div></div>
            <div class='campos-tipo campos-servico' hidden><h4>Serviço</h4><label>Unidade de cobrança</label><select name='unidade_servico'>{opcoes_unidade_novo}</select><label>Preço do serviço</label><input type='number' min='0' step='0.01' name='preco_servico' value='0'></div>
            <label><input type='checkbox' name='permite_auxiliar' value='1' style='width:auto'> Permite acabamento auxiliar no orçamento (botão "+ Outro acabamento")</label>
            <button type='submit'>Salvar cadastro</button>
        </form></div><div><h3>Cadastros existentes</h3>{tabela_tipo('material', 'Materiais', 'Pedras e chapas')}{tabela_tipo('acabamento', 'Acabamentos', 'Rodopias, saias e perfis')}{tabela_tipo('servico', 'Serviços', 'Serviços adicionais')}</div></div>
        <script>
            (() => {{
                const alternar = form => {{
                    const tipo = form.querySelector('[name="tipo"]:checked')?.value || form.querySelector('[name="tipo"]')?.value || 'material';
                    form.querySelectorAll('.campos-tipo').forEach(e => e.hidden = !e.classList.contains(`campos-${{tipo}}`));
                    const unidade = form.querySelector('[name="unidade_acabamento"], [name="unidade"]');
                    const combinado = tipo === 'acabamento' && unidade?.value === 'm² + linear';
                    form.querySelectorAll('.so-combinado').forEach(e => e.hidden = !combinado);
                    form.querySelectorAll('.so-simples').forEach(e => e.hidden = combinado);
                    form.querySelectorAll('[name="unidade"], [name="unidade_material"], [name="unidade_acabamento"], [name="unidade_servico"]').forEach(e => e.disabled = e.closest('.campos-tipo')?.hidden || false);
                    form.querySelectorAll('[name="preco_unitario"], [name="preco_material"], [name="preco_servico"], [name="material_base_id"], [name="largura_m"], [name="preco_linear"]').forEach(e => e.disabled = e.closest('[hidden]') !== null);
                }};
                document.querySelectorAll('form').forEach(form => {{
                    if (!form.querySelector('[name="tipo"]')) return;
                    form.addEventListener('change', () => alternar(form));
                    alternar(form);
                }});
            }})();
        </script>
    """, usuario)

def renderizar_historico(usuario=None, ordem='recentes'):
    linhas = []
    ordem = 'antigos' if ordem == 'antigos' else 'recentes'
    orcamentos_ordenados = [item for _, item in sorted(enumerate(banco_orcamentos), key=lambda par: (par[1].get('data', ''), par[0]), reverse=ordem == 'recentes') if item.get('ativo', True)]
    filtro_ordem = f"<form method='GET' action='/historico' class='ordem-historico'><label for='ordem-historico'>Ordenar por data</label><select id='ordem-historico' name='ordem' onchange='this.form.submit()'><option value='recentes' {'selected' if ordem == 'recentes' else ''}>Mais recentes primeiro</option><option value='antigos' {'selected' if ordem == 'antigos' else ''}>Mais antigos primeiro</option></select><noscript><button type='submit'>Aplicar</button></noscript></form>"
    formas_recebimento_opcoes = ''.join(
        f"<option value='{escape(forma['id'])}'>{escape(forma['nome'])}</option>"
        for forma in banco_formas_pagamento if forma.get('ativo', True)
    ) or '<option value="">Cadastre uma forma de pagamento</option>'
    for orcamento in orcamentos_ordenados:
        if not orcamento.get('ativo', True):
            continue
        numero = escape(orcamento['numero'])
        status = orcamento.get('status', 'Em análise')
        status_exibicao = 'Aprovado / Em produção' if status == 'Em produção' else status
        revisao = f".R{int(orcamento.get('revisao', 0))}" if orcamento.get('revisao', 0) else ''
        revisado_por = f"<br><small>Revisado por {escape(orcamento.get('revisado_por', ''))} em {escape(orcamento.get('revisado_em', ''))}</small>" if orcamento.get('revisao', 0) else ''
        parcelas = orcamento.get('parcelas_previstas', [])
        entrada = parcelas[0] if parcelas else {}
        entrada_valor_atual = float(orcamento.get('entrada_valor', entrada.get('valor', 0)))
        saldo_recebimento = max(0, round(float(orcamento.get('valor_total', 0)) - recebido_orcamento(orcamento['numero']), 2))
        registro_recebimento = ''
        pode_registrar_recebimento = pode_acessar(usuario, '/financeiro', escrever=True)
        status_recebivel = status in ('Aprovado', 'Em produção', 'Concluído', 'Vendido')
        if pode_registrar_recebimento and status_recebivel and saldo_recebimento > 0:
            registro_recebimento = f"""
                <form method='POST' action='/registrar_recebimento' class='recebimento-historico'>
                    <input type='hidden' name='orcamento_numero' value='{numero}'>
                    <strong>Registrar recebimento</strong>
                    <small>Saldo atual: {moeda(saldo_recebimento)}</small>
                    <label>Valor recebido</label><input type='number' name='valor' min='0.01' max='{saldo_recebimento:.2f}' step='0.01' value='{saldo_recebimento:.2f}' required>
                    <label>Etapa</label><select name='etapa'><option>Entrada</option><option>Entrega do material</option><option>Pagamento parcial</option><option>Outro</option></select>
                    <label>Forma de pagamento</label><select name='forma_pagamento_id' required>{formas_recebimento_opcoes}</select>
                    <label>Data</label><input type='date' name='data' value='{datetime.now().date().isoformat()}' required>
                    <button type='submit'>Confirmar recebimento</button>
                </form>
            """
        acoes_status = ''
        if status == 'Em análise':
            acoes_status = f"<form method='POST' action='/aprovar_orcamento'><input type='hidden' name='numero' value='{numero}'><button class='secondary' type='submit'>Aprovar e iniciar produção</button></form>"
        elif status == 'Em produção':
            acoes_status = f"<form method='POST' action='/concluir_orcamento'><input type='hidden' name='numero' value='{numero}'><button type='submit'>Marcar como concluído</button></form>"
        linhas.append(f"""
            <tr><td>{escape(orcamento['cliente_nome'])}</td><td>{numero}{revisao}</td><td>{escape(orcamento.get('material_nome', '-'))}</td>
            <td>{len(orcamento.get('itens', [])) or 1}</td><td>{moeda(orcamento['valor_total'])}</td>
            <td><span class='status'>{escape(status_exibicao)}</span>{revisado_por}</td>
            <td><a class='link' href='/emitir_orcamento?id={numero}' target='_blank'>PDF</a></td>
            <td><details><summary>Ações</summary><div class='acoes-menu'>
                <form method='POST' action='/alterar_orcamento'>
                    <input type='hidden' name='numero' value='{numero}'>
                    <label>Observações</label><textarea name='observacoes'>{escape(orcamento.get('observacoes', ''))}</textarea>
                    <label>Entrada (R$)</label><input type='number' name='entrada_valor' min='0' max='{float(orcamento.get('valor_total', 0)):.2f}' step='0.01' value='{entrada_valor_atual:.2f}'>
                    <label>Prazo de entrega (dias)</label><input type='number' name='prazo_entrega_dias' min='1' step='1' value='{int(orcamento.get('prazo_entrega_dias', 6))}'>
                    <a class='link' href='/orcamentos?editar={numero}'>Revisar orçamento e itens</a>
                </form>
                {registro_recebimento}
                {acoes_status}
                <form method='POST' action='/excluir_orcamento' onsubmit='return confirm(\"Arquivar este orçamento?\")'>
                    <input type='hidden' name='numero' value='{numero}'><button class='warning' type='submit'>Excluir orçamento</button>
                </form>
            </div></details></td></tr>
        """)
    linhas = ''.join(linhas) or '<tr><td colspan="8" class="muted">Nenhum orçamento registrado.</td></tr>'

    if not pode_acessar(usuario, '/historico', escrever=True):
        linhas_leitura = ''.join(
            f"<tr><td>{escape(item.get('cliente_nome', ''))}</td><td>{escape(numero_orcamento_exibicao(item))}</td><td>{escape(item.get('material_nome', '-'))}</td><td>{len(item.get('itens', [])) or 1}</td><td>{moeda(item.get('valor_total', 0))}</td><td>{escape(item.get('status', 'Em análise'))}</td><td><a class='link' href='/emitir_orcamento?id={escape(item.get('numero', ''))}'>PDF</a></td></tr>"
            for item in orcamentos_ordenados
        ) or '<tr><td colspan="7" class="muted">Nenhum orçamento registrado.</td></tr>'
        return pagina_base('/historico', f"<h2>Histórico de orçamentos</h2>{filtro_ordem}<div class='busca-cadastro'><input type='search' data-filtro-local='#lista-historico' placeholder='Buscar cliente, número, material ou status'></div><div class='panel'><table id='lista-historico'><tr><th>Cliente</th><th>Número</th><th>Materiais</th><th>Itens</th><th>Valor</th><th>Status</th><th>PDF</th></tr>{linhas_leitura}</table></div>", usuario)
    auditoria = ''.join(
        f"<tr><td>{escape(item.get('data_hora', ''))}</td><td>{escape(item.get('usuario_nome', ''))}</td><td>{escape(item.get('acao', ''))}</td><td>{escape(item.get('entidade', ''))} {escape(item.get('entidade_id', ''))}</td><td>{escape(item.get('detalhes', ''))}</td></tr>"
        for item in reversed(banco_auditoria[-30:])
    ) or '<tr><td colspan="5" class="muted">Nenhuma alteração registrada.</td></tr>'

    return pagina_base(
        "/historico",
        f"""
        <style>.acoes-menu {{ position:absolute; z-index:3; right:0; min-width:280px; max-height:70vh; overflow:auto; padding:12px; border:1px solid #d4ded9; border-radius:6px; background:#fff; box-shadow:0 8px 24px #18231e22; }} details {{ position:relative; }} .acoes-menu form {{ margin-bottom:10px; }} .acoes-menu form:last-child {{ margin-bottom:0; }} .recebimento-historico {{ margin:12px 0; padding:14px; border:1px solid #d5e4dc; border-left:4px solid var(--green); border-radius:9px; background:#f4f8f5; }} .recebimento-historico strong,.recebimento-historico small {{ display:block; margin-bottom:8px; }} .recebimento-historico small {{ color:var(--green-dark); font-weight:700; }}</style>
        <h2>Histórico de orçamentos</h2>
        {filtro_ordem}
        <div class="busca-cadastro"><input type="search" data-filtro-local="#lista-historico" placeholder="Buscar cliente, número, material ou status"></div>
        <div class="panel">
            <table id="lista-historico">
                <tr><th>Cliente</th><th>Número</th><th>Materiais</th><th>Itens</th><th>Valor</th><th>Status</th><th>PDF</th><th>Ações</th></tr>
                {linhas}
            </table>
        </div>
        <details class="panel auditoria"><summary>Alterações recentes e responsáveis</summary><table><tr><th>Data/hora</th><th>Usuário</th><th>Ação</th><th>Registro</th><th>Detalhes</th></tr>{auditoria}</table></details>
        """,
        usuario,
    )

def renderizar_orcamentos(usuario=None, cliente_selecionado='', baixar='', editar='', sucesso=False):
    orcamento_edicao = next((o for o in banco_orcamentos if o.get('numero') == editar and o.get('ativo', True)), None)
    if orcamento_edicao:
        cliente_selecionado = orcamento_edicao.get('cliente_id', cliente_selecionado)
    dados_edicao_js = json.dumps(orcamento_edicao, ensure_ascii=False).replace('</', '<\\/') if orcamento_edicao else 'null'
    download_auto = ''
    if baixar and any(o.get('numero') == baixar for o in banco_orcamentos):
        download_auto = f"<iframe src='/emitir_orcamento?id={escape(baixar)}' hidden></iframe><script>history.replaceState(null, '', '/orcamentos');</script>"
    orcamento_gerado = next((o for o in banco_orcamentos if o.get('numero') == baixar), None) if sucesso and baixar else None
    confirmacao_sucesso = f"""
        <div class="modal-sucesso" id="modal-sucesso" role="dialog" aria-modal="true" aria-labelledby="titulo-sucesso">
            <div class="modal-sucesso-conteudo">
                <div class="sucesso-icone" aria-hidden="true">✓</div>
                <h2 id="titulo-sucesso">Orçamento gerado com sucesso</h2>
                <p>Orçamento <strong>{escape(numero_orcamento_exibicao(orcamento_gerado))}</strong> salvo e pronto para consulta.</p>
                <div class="modal-sucesso-acoes"><button type="button" class="secondary" id="fechar-sucesso">Fechar</button><a class="button" href="/orcamentos?novo=1">Novo orçamento</a></div>
            </div>
        </div>
        <script>sessionStorage.removeItem('orcamento-rascunho-v1');document.getElementById('fechar-sucesso').addEventListener('click', () => document.getElementById('modal-sucesso').remove());</script>
    """ if orcamento_gerado else ''
    clientes_opcoes = "".join(
        f"<option value='{escape(cliente['id'])}' {'selected' if cliente['id'] == cliente_selecionado else ''}>{escape(cliente['nome'])}</option>" for cliente in banco_clientes if cliente.get('ativo', True)
    ) or '<option value="">Cadastre um cliente primeiro</option>'

    materiais_opcoes = "".join(
        f"<option value='{escape(material['id'])}' data-unidade='{escape(material.get('unidade', 'm²'))}' data-largura='{float(material.get('largura_m', 0) or 0):.4f}' data-preco='{preco_m2_acabamento(material):.2f}' data-preco-linear='{float(material.get('preco_linear', 0) or 0):.2f}'>{escape(material['nome'])} - {preco_material_exibicao(material)}</option>"
        for material in banco_materiais if material.get('ativo', True) and (material.get('tipo', 'material') == 'material' or (material.get('tipo') == 'acabamento' and material.get('unidade') == 'm² + linear'))
    ) or '<option value="">Cadastre um material ou acabamento primeiro</option>'

    acabamentos_opcoes = "".join(
        f"<option value='{escape(acabamento['id'])}' data-largura='{float(acabamento.get('largura_m', 0)):.4f}' data-auxiliar='{1 if acabamento.get('permite_auxiliar') else 0}' data-preco='{preco_m2_acabamento(acabamento):.2f}' data-preco-linear='{float(acabamento.get('preco_linear', 0)):.2f}' data-unidade='{escape(acabamento.get('unidade', 'metro linear'))}'>{escape(acabamento['nome'])} - {preco_material_exibicao(acabamento)}</option>"
        for acabamento in banco_materiais if acabamento.get('ativo', True) and acabamento.get('tipo') in ('acabamento', 'servico')
    ) or '<option value="">Cadastre um acabamento primeiro</option>'

    formas_opcoes = ''.join(
        f"<option value='{escape(forma['id'])}'>{escape(forma['nome'])}</option>"
        for forma in banco_formas_pagamento if forma.get('ativo', True)
    ) or '<option value="">Cadastre uma forma de pagamento no Financeiro</option>'

    if not pode_acessar(usuario, '/orcamentos', escrever=True):
        return pagina_base('/orcamentos', "<h2>Orçamentos</h2><div class='panel'>Acesso somente para consulta. Use a aba Histórico para visualizar pedidos.</div>", usuario)

    return pagina_base(
        "/orcamentos",
        f"""
        <style>
            .form-orcamento {{ display: grid; gap: 20px; }}
            .campo-medida {{ min-width: 0; }}
            .medida-ajuda {{ display: block; margin-top: 6px; padding: 7px 10px; border: 1px solid #cfe2d7; border-radius: 6px; background: #edf6f0; color: #285d46; font-size: 12px; line-height: 1.4; }}
            .medida-ajuda[hidden] {{ display: none; }}
            #itens-orcamento {{ display: grid; gap: 16px; }}
            .item-orcamento {{ min-width: 0; margin: 0; padding: 18px; border: 1px solid #dbe4df; border-left: 4px solid #276b58; border-radius: 8px; background: #fff; box-shadow: 0 3px 12px #1d342808; }}
            .item-cabecalho {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid #e7ece9; }}
            .item-cabecalho h3 {{ min-width: 0; margin: 0; color: var(--green-dark); overflow-wrap: anywhere; }}
            .item-cabecalho-acoes {{ display: flex; align-items: center; gap: 12px; }}
            .controle-quantidade {{ display: inline-flex; align-items: center; background: #f4f6f5; border: 1px solid #dbe4df; border-radius: 6px; overflow: hidden; height: 32px; }}
            .controle-quantidade button {{ width: 32px; height: 100%; min-height: unset; padding: 0; background: transparent; color: var(--green); border: none; border-radius: 0; font-size: 18px; font-weight: bold; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background .15s; }}
            .controle-quantidade button:hover {{ background: #e8f2ed; }}
            .controle-quantidade span {{ width: 32px; text-align: center; font-weight: 700; font-size: 14px; color: var(--ink); border-left: 1px solid #dbe4df; border-right: 1px solid #dbe4df; line-height: 30px; }}
            .item-cabecalho button.warning, .acabamento-cabecalho button.warning {{ width: auto; padding: 7px 10px; height: 32px; display: flex; align-items: center; }}
            .acabamentos {{ margin-top: 16px; padding-top: 14px; border-top: 1px solid #e7ece9; }}
            .acabamento-extra {{ grid-column: 1 / -1; }}
            .acabamento-linha.acabamento-aux {{ margin-left: 28px; padding: 10px; background: #fff6e6; border: 1px solid #e8c98f; border-left: 5px solid #b77936; border-radius: 6px; }}
            .aux-titulo {{ grid-column: 1 / -1; font-size: 12px; font-weight: 700; color: #8a5a1f; }}
            .acabamento-linha {{ display: grid; grid-template-columns: minmax(120px, 1.2fr) minmax(120px, 1fr) minmax(90px, .7fr) minmax(90px, .7fr) minmax(85px, .65fr) auto; align-items: end; gap: 8px; margin: 10px 0; }}
            .acabamento-linha button {{ width: auto; min-width: 40px; padding: 9px; }}
            .item-calculo {{ display: flex; justify-content: space-between; gap: 12px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #e7ece9; color: #53645c; font-size: 13px; }}
            .total-orcamento {{ padding: 16px 18px; border: 1px solid #cbded3; border-radius: 6px; background: #edf4ef; text-align: right; font-size: 19px; font-weight: 700; }}
            .total-orcamento strong {{ color: var(--green); }}
            .secao-orcamento {{ padding: 18px; border: 1px solid #e1e8e4; border-radius: 6px; background: #fff; }}
            .pagamento-grid {{ display: grid; grid-template-columns: minmax(220px, 1.4fr) minmax(180px, .8fr) minmax(180px, .8fr); gap: 14px; align-items: end; }}
            .resumo-pagamento {{ display: flex; justify-content: flex-end; gap: 32px; padding-top: 14px; color: #53645c; }}
            .resumo-pagamento strong {{ color: var(--green); }}
            .desconto-gordura {{ display: grid; grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr); gap: 14px; align-items: end; margin-top: 14px; }}
            .gordura-interna {{ margin-top: 12px; }}
            .gordura-interna summary {{ color: #66756f; cursor: pointer; font-size: 12px; font-weight: 600; }}
            .desconto-resumo {{ margin-top: 10px; text-align: right; color: #53645c; font-size: 13px; }}
            .acoes-orcamento {{ display: flex; justify-content: flex-end; align-items: center; gap: 16px; }}
            .acoes-orcamento button {{ width: auto; min-width: 190px; }}
            .orcamento-topo {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
            .orcamento-topo h2 {{ margin: 0; }}
            .orcamento-topo a.button, .modal-sucesso-acoes a.button {{ display: inline-flex; align-items: center; justify-content: center; min-height: 40px; padding: 10px 12px; border: 0; border-radius: 9px; background: #537b69; color: #fff; font: inherit; font-size: 14px; font-weight: 650; line-height: 20px; text-decoration: none; white-space: nowrap; cursor: pointer; transition: background .15s ease, transform .15s ease, box-shadow .15s ease; }}
            .orcamento-topo a.button:hover, .modal-sucesso-acoes a.button:hover {{ background: var(--green-dark); box-shadow: 0 4px 12px #1d514322; }}
            .orcamento-topo a.button:active, .modal-sucesso-acoes a.button:active {{ transform: scale(.985); }}
            .orcamento-topo a.button:focus-visible, .modal-sucesso-acoes a.button:focus-visible {{ outline: 3px solid #78ad91; outline-offset: 2px; }}
            .modal-sucesso {{ position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 20px; background: #10251dcc; animation: aparecer .18s ease-out; }}
            .modal-sucesso-conteudo {{ width: min(100%, 430px); padding: 30px; border-radius: 8px; background: #fff; box-shadow: 0 20px 70px #0005; text-align: center; }}
            .sucesso-icone {{ display: grid; place-items: center; width: 52px; height: 52px; margin: 0 auto 14px; border-radius: 50%; background: #e6f3eb; color: #276b58; font-size: 30px; font-weight: 700; }}
            .modal-sucesso-conteudo h2 {{ margin: 0 0 8px; font-size: 21px; }}
            .modal-sucesso-conteudo p {{ margin: 0; color: #596961; }}
            .modal-sucesso-acoes {{ display: flex; justify-content: center; gap: 10px; margin-top: 24px; }}
            .modal-sucesso-acoes button, .modal-sucesso-acoes a {{ width: auto; min-width: 130px; }}
            @keyframes aparecer {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
            @media (max-width: 700px) {{ .acabamento-linha, .pagamento-grid {{ grid-template-columns: 1fr 1fr; }} .acabamento-linha button {{ width: 100%; }} .resumo-pagamento {{ justify-content: space-between; gap: 12px; }} .acoes-orcamento button {{ width: 100%; }} }}
        </style>
        <div class="orcamento-topo"><h2>{'Revisão de orçamento ' + escape(editar) if orcamento_edicao else 'Criação de orçamento'}</h2>{'' if orcamento_edicao else '<a class="button secondary" href="/orcamentos?novo=1">+ Novo orçamento</a>'}</div>
        <div class="panel">
            <form method="POST" action="/salvar_orcamento" id="form-orcamento" class="form-orcamento">
                <input type="hidden" name="orcamento_numero" value="{escape(editar) if orcamento_edicao else ''}">
                    <div><label>1. Cliente</label><input type="search" class="busca-select" id="busca-cliente" placeholder="Pesquisar cliente..."><select name="cliente_id" required>{clientes_opcoes}</select></div>
                    <div class="item-cabecalho"><h3>2. Peças e serviços</h3><button type="button" class="secondary" id="adicionar-item">+ Adicionar peça</button></div>
                    <div id="itens-orcamento"></div>
                    <div class="total-orcamento">Subtotal dos itens: <strong id="subtotal-orcamento">R$ 0,00</strong></div>
                    <section class="secao-orcamento">
                    <h3>3. Pagamento</h3>
                    <div class="pagamento-grid">
                        <div><label>Forma de pagamento</label><select name="forma_pagamento_id" required>{formas_opcoes}</select></div>
                        <div><label>Entrada (R$)</label><input type="number" name="entrada_valor" min="0" step="0.01" value="{float(orcamento_edicao.get('entrada_valor', 0)) if orcamento_edicao else 0:.2f}" required></div>
                        <div><label>Prazo de entrega (dias)</label><input type="number" name="prazo_entrega_dias" min="1" step="1" value="{int(orcamento_edicao.get('prazo_entrega_dias', 6)) if orcamento_edicao else 6}" required></div>
                    </div>
                    <div class="desconto-gordura">
                        <div><label>Desconto (%)</label><input type="number" name="desconto_percentual" min="0" max="100" step="0.01" value="{float(orcamento_edicao.get('desconto_percentual', 0)) if orcamento_edicao else 0}"></div>
                        <div class="desconto-resumo">Desconto: <strong id="valor-desconto">R$ 0,00</strong></div>
                    </div>
                    <details class="gordura-interna" {'open' if orcamento_edicao and orcamento_edicao.get('gordura_percentual', 0) else ''}><summary>Gordura interna</summary><div><label>Margem adicional (%)</label><input type="number" name="gordura_percentual" min="0" max="100" step="0.01" value="{float(orcamento_edicao.get('gordura_percentual', 0)) if orcamento_edicao else 0}"></div></details>
                    <div class="total-orcamento">Total do orçamento: <strong id="total-orcamento">R$ 0,00</strong></div>
                    <div class="resumo-pagamento"><span>Entrada: <strong id="entrada-prevista">R$ 0,00</strong></span><span>Saldo na entrega: <strong id="saldo-entrega">R$ 0,00</strong></span></div>
                    </section>
                    <section class="secao-orcamento"><label>Observações gerais (opcional)</label><textarea name="observacoes" placeholder="Prazo, condições ou detalhes do pedido">{escape(orcamento_edicao.get('observacoes', '')) if orcamento_edicao else ''}</textarea></section>
                    <div class="acoes-orcamento">{"<a class='link' href='/historico'>Cancelar revisão</a>" if orcamento_edicao else ''}<button type="submit">{'Salvar revisão e baixar PDF' if orcamento_edicao else 'Gerar orçamento'}</button></div>
                </form>
        </div>
        {download_auto}
        {confirmacao_sucesso}
        <script>const dadosEdicao = {dados_edicao_js};</script>
        <template id="item-template">
            <div class="item-orcamento">
                <div class="item-cabecalho">
                    <h3>Item</h3>
                    <div class="item-cabecalho-acoes">
                        <div class="controle-quantidade" title="Quantidade de peças idênticas">
                            <button type="button" class="qtd-menos">−</button>
                            <span class="qtd-valor">1</span>
                            <button type="button" class="qtd-mais">+</button>
                        </div>
                        <input type="hidden" name="item_quantidade_pecas" class="item-quantidade-pecas" value="1">
                        <button type="button" class="warning remover-item" title="Remover item">Remover</button>
                    </div>
                </div>
                <div class="linha">
                    <div><label>Nome da peça</label><input type="text" name="item_descricao" placeholder="Ex.: Bancada da cozinha ou rodapé" required></div>
                    <div><label>Pedra ou rodapé</label><input type="search" class="busca-select busca-material" placeholder="Pesquisar pedra ou rodapé..."><select name="item_material_id" required>{materiais_opcoes}</select></div>
                </div>
                <div class="linha">
                    <div class="campo-medida"><label>Comprimento total (m)</label><input type="number" name="item_comprimento" min="0.0001" step="0.0001" placeholder="Ex.: 2,40" value="1.00" required><small class="medida-ajuda" role="status" aria-live="polite" hidden></small></div>
                    <div class="campo-medida"><label class="item-largura-label">Largura (m)</label><input type="number" name="item_largura" min="0.0001" step="0.0001" placeholder="Ex.: 0,60" value="1.00" required><small class="medida-ajuda" role="status" aria-live="polite" hidden></small></div>
                </div>
                <div class="linha">
                    <div style="flex: 1;"><label>Detalhes da peça (opcional)</label><input type="text" name="item_observacao" placeholder="Ex.: Recorte para cuba"></div>
                </div>
                <div class="acabamentos">
                    <div class="acabamento-cabecalho"><h4>Acabamentos adicionais (opcional)</h4><button type="button" class="secondary adicionar-acabamento">+ Adicionar acabamento</button></div>
                    <div class="lista-acabamentos"></div>
                </div>
                <div class="item-calculo"><span class="area-item">Área: 1,00 m²</span><strong class="total-item">Total do item: R$ 0,00</strong></div>
            </div>
        </template>
        <template id="acabamento-template">
            <div class="acabamento-linha">
                <div><label>Acabamento/serviço</label><input type="search" class="busca-select busca-acabamento" placeholder="Pesquisar..."><select class="acabamento-select" required>{acabamentos_opcoes}</select></div>
                <div><label>Descrição / local</label><input type="text" class="acabamento-descricao" placeholder="Ex.: lateral esquerda" required></div>
                    <div class="campo-medida"><label class="acabamento-medida-label">Medida (m)</label><input type="number" class="acabamento-quantidade" min="0.0001" step="0.0001" value="1.00" required><small class="medida-ajuda" role="status" aria-live="polite" hidden></small></div>
                    <div class="acabamento-largura-wrap campo-medida" hidden><label class="acabamento-largura-label">Largura (m)</label><input type="number" class="acabamento-largura" min="0.0001" step="0.0001" value="1.00"><small class="medida-ajuda" role="status" aria-live="polite" hidden></small></div>
                <div><label>Subtotal por peça</label><input type="text" class="acabamento-subtotal" value="R$ 0,00" readonly></div>
                <input type="hidden" class="acabamento-aux-flag" value="0">
                <button type="button" class="warning remover-acabamento" title="Remover acabamento">X</button>
                <div class="acabamento-extra" hidden><button type="button" class="secondary adicionar-sub-acabamento">+ Outro acabamento nesta peça</button></div>
            </div>
        </template>
        <script>
            (() => {{
                const itens = document.getElementById('itens-orcamento');
                const modeloItem = document.getElementById('item-template');
                const modeloAcabamento = document.getElementById('acabamento-template');
                const chaveRascunho = 'orcamento-rascunho-v1';
                const formulario = document.getElementById('form-orcamento');
                let restaurandoRascunho = false;
                const formatarMoeda = valor => new Intl.NumberFormat('pt-BR', {{ style: 'currency', currency: 'BRL' }}).format(valor || 0);
                const formatarMedida = valor => Number(valor).toFixed(2).replace('.', ',');
                const formatarMedidaPrecisa = valor => new Intl.NumberFormat('pt-BR', {{ maximumFractionDigits: 4 }}).format(valor);
                const atualizarAjudaMedida = (campo, mostrar = false, usarMetro = true) => {{
                    const ajuda = campo.parentElement.querySelector('.medida-ajuda');
                    if (!usarMetro || (!mostrar && document.activeElement !== campo)) {{ ajuda.hidden = true; return; }}
                    const metros = Number(campo.value);
                    ajuda.hidden = false;
                    if (!campo.value || !Number.isFinite(metros) || metros <= 0) {{ ajuda.textContent = 'Digite a medida em metros (m).'; return; }}
                    let equivalencia = `${{formatarMedidaPrecisa(metros * 100)}} cm`;
                    if (metros < 0.01) equivalencia += ` (${{formatarMedidaPrecisa(metros * 1000)}} mm)`;
                    ajuda.textContent = `${{formatarMedidaPrecisa(metros)}} m = ${{equivalencia}}. Você está preenchendo em metros.`;
                }};
                const conectarAjudaMedida = (campo, usarMetro = () => true) => {{
                    campo.addEventListener('focus', () => atualizarAjudaMedida(campo, true, usarMetro()));
                    campo.addEventListener('input', () => atualizarAjudaMedida(campo, true, usarMetro()));
                    campo.addEventListener('blur', () => atualizarAjudaMedida(campo, false, usarMetro()));
                }};
                const salvarRascunho = () => {{
                    if (dadosEdicao || restaurandoRascunho) return;
                    const campo = nome => formulario.querySelector(`[name="${{nome}}"]`);
                    const rascunho = {{
                        cliente_id: campo('cliente_id').value,
                        busca_cliente: document.getElementById('busca-cliente').value,
                        forma_pagamento_id: campo('forma_pagamento_id').value,
                        entrada_valor: campo('entrada_valor').value,
                        prazo_entrega_dias: campo('prazo_entrega_dias').value,
                        desconto_percentual: campo('desconto_percentual').value,
                        gordura_percentual: campo('gordura_percentual').value,
                        observacoes: campo('observacoes').value,
                        itens: [...itens.querySelectorAll('.item-orcamento')].map(item => ({{
                            descricao: item.querySelector('[name="item_descricao"]').value,
                            material_id: item.querySelector('[name="item_material_id"]').value,
                            comprimento: item.querySelector('[name="item_comprimento"]').value,
                            largura: item.querySelector('[name="item_largura"]').value,
                            observacao_item: item.querySelector('[name="item_observacao"]').value,
                            quantidade_pecas: item.querySelector('.qtd-valor').textContent,
                            acabamentos: [...item.querySelectorAll('.acabamento-linha')].map(linha => ({{
                                acabamento_id: linha.querySelector('.acabamento-select').value,
                                descricao: linha.querySelector('.acabamento-descricao').value,
                                medida: linha.querySelector('.acabamento-quantidade').value,
                                largura_m: linha.querySelector('.acabamento-largura').value,
                                auxiliar: linha.querySelector('.acabamento-aux-flag').value === '1'
                            }}))
                        }}))
                    }};
                    try {{ sessionStorage.setItem(chaveRascunho, JSON.stringify(rascunho)); }} catch {{}}
                }};
                const ligarBusca = (campo, select) => {{
                    campo.addEventListener('input', () => {{
                        const termo = campo.value.trim().toLowerCase();
                        [...select.options].forEach(opcao => {{ opcao.hidden = termo !== '' && !opcao.textContent.toLowerCase().includes(termo); }});
                        const visivel = [...select.options].find(opcao => !opcao.hidden);
                        if (visivel && (select.selectedOptions[0]?.hidden)) select.value = visivel.value;
                        select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }});
                }};
                const atualizar = () => {{
                    let totalGeral = 0;
                    [...itens.querySelectorAll('.item-orcamento')].forEach((item, indice) => {{
                        const nomeItem = item.querySelector('[name="item_descricao"]').value.trim();
                        item.querySelector('h3').textContent = nomeItem ? `Item ${{indice + 1}} - ${{nomeItem}}` : `Item ${{indice + 1}}`;
                        
                        // Lógica do Stepper (Quantidade)
                        const btnMais = item.querySelector('.qtd-mais');
                        const btnMenos = item.querySelector('.qtd-menos');
                        const spanQtd = item.querySelector('.qtd-valor');
                        
                        btnMais.replaceWith(btnMais.cloneNode(true));
                        btnMenos.replaceWith(btnMenos.cloneNode(true));
                        
                        item.querySelector('.qtd-mais').addEventListener('click', () => {{
                            let qtd = parseInt(spanQtd.textContent) || 1;
                            spanQtd.textContent = qtd + 1;
                            atualizar();
                        }});
                        
                        item.querySelector('.qtd-menos').addEventListener('click', () => {{
                            let qtd = parseInt(spanQtd.textContent) || 1;
                            if (qtd > 1) {{
                                spanQtd.textContent = qtd - 1;
                                atualizar();
                            }}
                        }});
                        
                        const quantidadePecas = parseInt(spanQtd.textContent) || 1;
                        item.querySelector('.item-quantidade-pecas').value = quantidadePecas;

                        item.querySelectorAll('.acabamento-linha').forEach(linha => {{
                            linha.querySelector('.acabamento-select').name = `acabamento_id_${{indice}}`;
                            linha.querySelector('.acabamento-descricao').name = `acabamento_descricao_${{indice}}`;
                            linha.querySelector('.acabamento-quantidade').name = `acabamento_quantidade_${{indice}}`;
                            linha.querySelector('.acabamento-largura').name = `acabamento_largura_${{indice}}`;
                            linha.querySelector('.acabamento-aux-flag').name = `acabamento_aux_${{indice}}`;
                            const opcao = linha.querySelector('.acabamento-select').selectedOptions[0];
                            const medida = Number(linha.querySelector('.acabamento-quantidade').value) || 0;
                            const preco = Number(opcao?.dataset.preco) || 0;
                            const precoLinear = Number(opcao?.dataset.precoLinear) || 0;
                            const unidade = opcao?.dataset.unidade || 'metro linear';
                            const combinado = unidade === 'm² + linear';
                            const acabamentoPorArea = unidade === 'm²';
                            const campoLargura = linha.querySelector('.acabamento-largura');
                            const larguraAcabamento = combinado ? (Number(opcao?.dataset.largura) || 0) : (Number(campoLargura.value) || 0);
                            atualizarAjudaMedida(linha.querySelector('.acabamento-quantidade'), false, unidade !== 'unidade');
                            atualizarAjudaMedida(campoLargura, false, acabamentoPorArea);
                            linha.querySelector('.acabamento-medida-label').textContent = unidade === 'unidade' ? 'Quantidade (un.)' : 'Comprimento (m)';
                            linha.querySelector('.acabamento-largura-label').textContent = 'Largura (m)';
                            linha.querySelector('.acabamento-largura-wrap').hidden = !acabamentoPorArea;
                            linha.querySelector('.acabamento-largura').required = acabamentoPorArea;
                            const areaAcabamento = medida * larguraAcabamento;
                            const subtotal = combinado ? areaAcabamento * preco + medida * precoLinear : acabamentoPorArea ? areaAcabamento * preco : medida * preco;
                            linha.querySelector('.acabamento-subtotal').title = combinado ? `${{medida.toFixed(2)}} m x ${{larguraAcabamento.toFixed(2)}} m = ${{areaAcabamento.toFixed(2)}} m²` : '';
                            linha.querySelector('.acabamento-subtotal').value = formatarMoeda(subtotal);
                            linha.dataset.quantidadeResumo = combinado
                                ? `${{formatarMedida(areaAcabamento)}} m² x ${{quantidadePecas}} = ${{formatarMedida(areaAcabamento * quantidadePecas)}} m²; ${{formatarMedida(medida)}} m x ${{quantidadePecas}} = ${{formatarMedida(medida * quantidadePecas)}} m`
                                : unidade === 'm²'
                                    ? `${{formatarMedida(areaAcabamento)}} m² x ${{quantidadePecas}} = ${{formatarMedida(areaAcabamento * quantidadePecas)}} m²`
                                    : unidade === 'unidade'
                                        ? `${{formatarMedida(medida)}} un. x ${{quantidadePecas}} = ${{formatarMedida(medida * quantidadePecas)}} un.`
                                        : `${{formatarMedida(medida)}} m x ${{quantidadePecas}} = ${{formatarMedida(medida * quantidadePecas)}} m`;
                            linha.dataset.subtotal = subtotal;
                            const rotuloResumo = linha.querySelector('.acabamento-descricao').value.trim() || (opcao?.textContent || 'Acabamento').split(' - ')[0];
                            linha.dataset.quantidadeResumo = `${{rotuloResumo}}: ${{linha.dataset.quantidadeResumo}}`;
                            linha.querySelector('.acabamento-extra').hidden = opcao?.dataset.auxiliar !== '1';
                        }});
                        const comprimento = Number(item.querySelector('[name="item_comprimento"]').value) || 0;
                        const opcaoPrincipal = item.querySelector('[name="item_material_id"]').selectedOptions[0];
                        const principalCombinado = opcaoPrincipal?.dataset.unidade === 'm² + linear';
                        const campoLarguraItem = item.querySelector('[name="item_largura"]');
                        if (principalCombinado) {{
                            if (!campoLarguraItem.readOnly) campoLarguraItem.dataset.larguraAnterior = campoLarguraItem.value;
                            campoLarguraItem.value = opcaoPrincipal.dataset.largura || '';
                        }} else if (campoLarguraItem.readOnly) {{
                            campoLarguraItem.value = campoLarguraItem.dataset.larguraAnterior || '1.00';
                        }}
                        campoLarguraItem.readOnly = principalCombinado;
                        item.querySelector('.item-largura-label').textContent = principalCombinado ? 'Largura cadastrada (m)' : 'Largura (m)';
                        atualizarAjudaMedida(campoLarguraItem, false);
                        const largura = Number(campoLarguraItem.value) || 0;
                        const area = comprimento * largura;
                        const precoMaterial = Number(opcaoPrincipal?.dataset.preco) || 0;
                        const precoLinearPrincipal = principalCombinado ? Number(opcaoPrincipal.dataset.precoLinear) || 0 : 0;
                        const totalItem = (area * precoMaterial + comprimento * precoLinearPrincipal + [...item.querySelectorAll('.acabamento-linha')].reduce((soma, linha) => soma + Number(linha.dataset.subtotal || 0), 0)) * quantidadePecas;
                        const quantidadesAcabamento = [...item.querySelectorAll('.acabamento-linha')].map(linha => linha.dataset.quantidadeResumo).filter(Boolean);
                        const nomeResumo = nomeItem || `Item ${{indice + 1}}`;
                        const resumoPrincipal = [`${{nomeResumo}}: ${{formatarMedida(area)}} m² x ${{quantidadePecas}} = ${{formatarMedida(area * quantidadePecas)}} m²`];
                        if (principalCombinado) resumoPrincipal.push(`Linear: ${{formatarMedida(comprimento)}} m x ${{quantidadePecas}} = ${{formatarMedida(comprimento * quantidadePecas)}} m`);
                        item.querySelector('.area-item').textContent = [...resumoPrincipal, ...quantidadesAcabamento].join(' | ');
                        item.querySelector('.total-item').textContent = `Total do item: ${{formatarMoeda(totalItem)}}`;
                        totalGeral += totalItem;
                    }});
                    const gorduraPercentual = Math.max(0, Math.min(100, Number(document.querySelector('[name="gordura_percentual"]').value) || 0));
                    const descontoPercentual = Math.max(0, Math.min(100, Number(document.querySelector('[name="desconto_percentual"]').value) || 0));
                    const subtotalComGordura = totalGeral * (1 + gorduraPercentual / 100);
                    const valorDesconto = subtotalComGordura * descontoPercentual / 100;
                    const totalFinal = subtotalComGordura - valorDesconto;
                    document.getElementById('subtotal-orcamento').textContent = formatarMoeda(subtotalComGordura);
                    document.getElementById('valor-desconto').textContent = formatarMoeda(valorDesconto);
                    document.getElementById('total-orcamento').textContent = formatarMoeda(totalFinal);
                    const entrada = Math.max(0, Math.min(totalFinal, Number(document.querySelector('[name="entrada_valor"]').value) || 0));
                    document.getElementById('entrada-prevista').textContent = formatarMoeda(entrada);
                    document.getElementById('saldo-entrega').textContent = formatarMoeda(totalFinal - entrada);
                    salvarRascunho();
                }};
                const adicionarItem = (dadosItem = null) => {{
                    const fragmento = modeloItem.content.cloneNode(true);
                    const item = fragmento.querySelector('.item-orcamento');
                    item.querySelector('.remover-item').addEventListener('click', () => {{ item.remove(); atualizar(); }});
                    ligarBusca(item.querySelector('.busca-material'), item.querySelector('[name="item_material_id"]'));
                    const criarAcabamento = (origem, dadosAcabamento = null) => {{
                        const acabamento = modeloAcabamento.content.cloneNode(true).querySelector('.acabamento-linha');
                        conectarAjudaMedida(acabamento.querySelector('.acabamento-quantidade'), () => acabamento.querySelector('.acabamento-select').selectedOptions[0]?.dataset.unidade !== 'unidade');
                        conectarAjudaMedida(acabamento.querySelector('.acabamento-largura'), () => acabamento.querySelector('.acabamento-select').selectedOptions[0]?.dataset.unidade === 'm²');
                        acabamento.querySelector('.remover-acabamento').addEventListener('click', () => {{ acabamento.remove(); atualizar(); }});
                        ligarBusca(acabamento.querySelector('.busca-acabamento'), acabamento.querySelector('.acabamento-select'));
                        acabamento.querySelector('.adicionar-sub-acabamento').addEventListener('click', () => criarAcabamento(acabamento));
                        acabamento.addEventListener('input', atualizar);
                        acabamento.addEventListener('change', atualizar);
                        if (dadosAcabamento) {{
                            acabamento.querySelector('.acabamento-select').value = dadosAcabamento.acabamento_id || '';
                            acabamento.querySelector('.acabamento-descricao').value = dadosAcabamento.descricao || '';
                            acabamento.querySelector('.acabamento-quantidade').value = dadosAcabamento.medida ?? dadosAcabamento.quantidade ?? 1;
                            acabamento.querySelector('.acabamento-largura').value = dadosAcabamento.largura_m ?? 1;
                            acabamento.querySelector('.acabamento-aux-flag').value = dadosAcabamento.auxiliar ? '1' : '0';
                            if (dadosAcabamento.auxiliar && origem) {{
                                acabamento.classList.add('acabamento-aux');
                                const titulo = document.createElement('div');
                                titulo.className = 'aux-titulo';
                                titulo.textContent = `Acabamento auxiliar de: {{origem.querySelector('.acabamento-select').selectedOptions[0]?.textContent.split(' - ')[0] || 'acabamento acima'}}`;
                                acabamento.prepend(titulo);
                            }}
                            origem ? origem.after(acabamento) : item.querySelector('.lista-acabamentos').append(acabamento);
                        }} else if (origem) {{
                            const select = acabamento.querySelector('.acabamento-select');
                            const simples = [...select.options].find(opcao => opcao.dataset.unidade !== 'm² + linear');
                            if (simples) select.value = simples.value;
                            acabamento.querySelector('.acabamento-descricao').value = origem.querySelector('.acabamento-descricao').value;
                            acabamento.querySelector('.acabamento-quantidade').value = origem.querySelector('.acabamento-quantidade').value;
                            acabamento.style.marginLeft = '';
                            acabamento.classList.add('acabamento-aux');
                            acabamento.querySelector('.acabamento-aux-flag').value = '1';
                            const titulo = document.createElement('div');
                            titulo.className = 'aux-titulo';
                            titulo.textContent = `Acabamento auxiliar de: {{origem.querySelector('.acabamento-select').selectedOptions[0]?.textContent.split(' - ')[0] || 'acabamento acima'}}`;
                            acabamento.prepend(titulo);
                            origem.after(acabamento);
                        }} else {{
                            item.querySelector('.lista-acabamentos').append(acabamento);
                        }}
                        atualizar();
                        return acabamento;
                    }};
                    item.querySelector('.adicionar-acabamento').addEventListener('click', () => criarAcabamento(null));
                    conectarAjudaMedida(item.querySelector('[name="item_comprimento"]'));
                    conectarAjudaMedida(item.querySelector('[name="item_largura"]'));
                    item.addEventListener('input', atualizar);
                    item.addEventListener('change', atualizar);
                    itens.append(item);
                    if (dadosItem) {{
                        item.querySelector('[name="item_descricao"]').value = dadosItem.descricao || '';
                        item.querySelector('[name="item_material_id"]').value = dadosItem.material_id || '';
                        item.querySelector('[name="item_comprimento"]').value = dadosItem.comprimento || 1;
                        item.querySelector('[name="item_largura"]').value = dadosItem.largura || 1;
                        // Se houver quantidade salva, restaura no stepper
                        const qtdSalva = dadosItem.quantidade_pecas || 1;
                        item.querySelector('.qtd-valor').textContent = qtdSalva;
                        if (dadosItem.observacao_item) item.querySelector('[name="item_observacao"]').value = dadosItem.observacao_item;
                        
                        let acabamentoPrincipal = null;
                        (dadosItem.acabamentos || []).forEach(dadosAcabamento => {{
                            const origem = dadosAcabamento.auxiliar ? acabamentoPrincipal : null;
                            const linha = criarAcabamento(origem, dadosAcabamento);
                            if (!dadosAcabamento.auxiliar) acabamentoPrincipal = linha;
                        }});
                    }}
                    atualizar();
                    return item;
                }};
                document.getElementById('adicionar-item').addEventListener('click', () => adicionarItem());
                ligarBusca(document.getElementById('busca-cliente'), document.querySelector('[name="cliente_id"]'));
                document.querySelector('[name="entrada_valor"]').addEventListener('input', atualizar);
                document.querySelector('[name="desconto_percentual"]').addEventListener('input', atualizar);
                document.querySelector('[name="gordura_percentual"]').addEventListener('input', atualizar);
                formulario.addEventListener('input', salvarRascunho);
                formulario.addEventListener('change', salvarRascunho);
                formulario.addEventListener('submit', salvarRascunho);
                if (dadosEdicao) {{
                    document.querySelector('[name="cliente_id"]').value = dadosEdicao.cliente_id || '';
                    document.querySelector('[name="forma_pagamento_id"]').value = dadosEdicao.forma_pagamento_id || '';
                    document.querySelector('[name="entrada_valor"]').value = dadosEdicao.entrada_valor || 0;
                    document.querySelector('[name="observacoes"]').value = dadosEdicao.observacoes || '';
                    (dadosEdicao.itens || []).forEach(adicionarItem);
                }} else {{
                    const parametros = new URLSearchParams(window.location.search);
                    if (parametros.get('novo') === '1') {{
                        sessionStorage.removeItem(chaveRascunho);
                        history.replaceState(null, '', '/orcamentos');
                    }}
                    let rascunho = null;
                    try {{ rascunho = JSON.parse(sessionStorage.getItem(chaveRascunho) || 'null'); }} catch {{}}
                    if (rascunho && Array.isArray(rascunho.itens) && rascunho.itens.length) {{
                        restaurandoRascunho = true;
                        document.querySelector('[name="cliente_id"]').value = rascunho.cliente_id || '';
                        document.getElementById('busca-cliente').value = rascunho.busca_cliente || '';
                        document.querySelector('[name="forma_pagamento_id"]').value = rascunho.forma_pagamento_id || '';
                        document.querySelector('[name="entrada_valor"]').value = rascunho.entrada_valor || '0';
                        document.querySelector('[name="prazo_entrega_dias"]').value = rascunho.prazo_entrega_dias || '6';
                        document.querySelector('[name="desconto_percentual"]').value = rascunho.desconto_percentual || '0';
                        document.querySelector('[name="gordura_percentual"]').value = rascunho.gordura_percentual || '0';
                        document.querySelector('[name="observacoes"]').value = rascunho.observacoes || '';
                        rascunho.itens.forEach(adicionarItem);
                        restaurandoRascunho = false;
                        atualizar();
                    }} else {{
                        adicionarItem();
                    }}
                }}

            }})();
        </script>
        """,
        usuario,
    )

def renderizar_modelo_pdf(usuario=None):
    m = modelo_pdf()

    def lista(nome, rotulo):
        return f"<label>{rotulo} (um item por linha)</label><textarea name='{nome}' rows='{len(m[nome]) + 2}'>{escape(chr(10).join(m[nome]))}</textarea>"

    def campo(nome, rotulo):
        return f"<div><label>{rotulo}</label><input name='{nome}' value='{escape(m[nome])}'></div>"

    return pagina_base(
        "/gerencial",
        f"""
        <h2>Modelo do PDF do orçamento</h2>
        <div class="panel"><form method="POST" action="/salvar_modelo_pdf">
            <div class="linha"><div><label>Cor principal (faixas e títulos)</label><input type="color" name="cor_principal" value="{m['cor_principal']}"></div><div><label>Cor da linha TOTAL</label><input type="color" name="cor_total" value="{m['cor_total']}"></div></div>
            <div class="linha">{campo('titulo_orcamento', 'Título do orçamento')}{campo('titulo_pedido', 'Título do pedido aprovado')}</div>
            {campo('texto_liberacao', 'Texto abaixo do prazo de entrega')}
            {lista('condicoes', 'Condições de venda')}
            {lista('acessorios', 'Acessórios a serem entregues')}
            {lista('obra', 'Acabamento em obra')}
            {campo('confirmacao', 'Frase de confirmação')}
            <div class="linha">{campo('empresa', 'Empresa (assinatura)')}{campo('cnpj', 'CNPJ (assinatura)')}</div>
            <button type="submit">Salvar modelo</button>
        </form></div>
        """,
        usuario,
    )

def recebido_orcamento(numero):
    return sum(float(item.get('valor', 0)) for item in banco_recebimentos if item.get('orcamento_numero') == numero)

def renderizar_financeiro(usuario=None, inicio='', fim=''):
    hoje = datetime.now().date()
    previsao_entrega_padrao = (hoje + timedelta(days=6)).isoformat()
    inicio = inicio or hoje.replace(day=1).isoformat()
    fim = fim or hoje.isoformat()
    try:
        data_inicio = datetime.strptime(inicio, '%Y-%m-%d').date()
        data_fim = datetime.strptime(fim, '%Y-%m-%d').date()
    except ValueError:
        data_inicio = hoje.replace(day=1)
        data_fim = hoje
        inicio, fim = data_inicio.isoformat(), data_fim.isoformat()

    orcamentos_periodo = []
    for orcamento in banco_orcamentos:
        try:
            data_orcamento = datetime.strptime(orcamento.get('data', ''), '%Y-%m-%d').date()
        except ValueError:
            continue
        if data_inicio <= data_orcamento <= data_fim and orcamento.get('ativo', True):
            orcamentos_periodo.append(orcamento)

    recebimentos_periodo = [
        recebimento for recebimento in banco_recebimentos
        if inicio <= recebimento.get('data', '')[:10] <= fim
    ]
    vendas = []
    for item in banco_orcamentos:
        if not item.get('ativo', True) or item.get('status') not in ('Aprovado', 'Em produção', 'Concluído', 'Vendido'):
            continue
        data_venda = (item.get('aprovado_em') or item.get('data', ''))[:10]
        if inicio <= data_venda <= fim:
            vendas.append(item)
    total_vendido = sum(float(item.get('valor_total', 0)) for item in vendas)
    total_recebido = sum(float(item.get('valor', 0)) for item in recebimentos_periodo)
    saldos_abertos = {
        item.get('numero'): max(0, float(item.get('valor_total', 0)) - recebido_orcamento(item.get('numero')))
        for item in vendas
    }
    total_aberto = sum(saldos_abertos.values())
    classe_aberto = ' alerta' if total_aberto > 0 else ' zerado'
    total_orcado_periodo = sum(float(item['valor_total']) for item in orcamentos_periodo)

    por_vendedor = {}
    por_cliente = {}
    por_forma_pagamento = {}
    for orcamento in vendas:
        vendedor = orcamento.get('vendedor') or 'Não informado'
        cliente = orcamento.get('cliente_nome') or 'Não informado'
        valor_total = float(orcamento.get('valor_total', 0))
        por_vendedor[vendedor] = por_vendedor.get(vendedor, 0) + valor_total
        por_cliente[cliente] = por_cliente.get(cliente, 0) + valor_total
        forma = orcamento.get('forma_pagamento_nome') or 'Não informado'
        por_forma_pagamento[forma] = por_forma_pagamento.get(forma, 0) + valor_total
    linhas_vendedor = ''.join(f'<tr><td>{escape(nome)}</td><td>{moeda(valor_total)}</td></tr>' for nome, valor_total in sorted(por_vendedor.items(), key=lambda item: item[1], reverse=True)) or '<tr><td colspan="2" class="muted">Sem vendas aprovadas neste período.</td></tr>'
    linhas_cliente = ''.join(f'<tr><td>{escape(nome)}</td><td>{moeda(valor_total)}</td></tr>' for nome, valor_total in sorted(por_cliente.items(), key=lambda item: item[1], reverse=True)[:10]) or '<tr><td colspan="2" class="muted">Sem compras no período.</td></tr>'
    linhas_formas_ranking = ''.join(f'<tr><td>{escape(nome)}</td><td>{moeda(valor_total)}</td></tr>' for nome, valor_total in sorted(por_forma_pagamento.items(), key=lambda item: item[1], reverse=True)) or '<tr><td colspan="2" class="muted">Sem vendas confirmadas no período.</td></tr>'

    abertos = []
    for orcamento in vendas:
        saldo = saldos_abertos.get(orcamento.get('numero'), 0)
        if saldo > 0:
            abertos.append(f"<tr><td>{escape(orcamento['numero'])}</td><td>{escape(orcamento['cliente_nome'])}</td><td>{moeda(orcamento['valor_total'])}</td><td>{moeda(recebido_orcamento(orcamento['numero']))}</td><td>{moeda(saldo)}</td></tr>")
    linhas_abertos = ''.join(abertos) or '<tr><td colspan="5" class="muted">Nenhum saldo em aberto no período.</td></tr>'

    def tag_etapa_html(etapa):
        etapa_texto = str(etapa or 'Outro')
        etapa_normalizada = etapa_texto.casefold()
        classe, icone = ('entrada', '📥') if etapa_normalizada == 'entrada' else ('entrega', '🚚') if 'entrega' in etapa_normalizada else ('medicao', '📐') if 'medi' in etapa_normalizada else ('outra', '•')
        return f"<span class='tag-etapa {classe}'>{icone} {escape(etapa_texto)}</span>"

    linhas_parcelas = []
    for orcamento in vendas:
        parcelas = orcamento.get('parcelas_previstas') or [
            {'etapa': 'Pagamento', 'valor': float(orcamento.get('valor_total', 0)), 'data_prevista': ''}
        ]
        recebimentos = [item for item in banco_recebimentos if item.get('orcamento_numero') == orcamento.get('numero')]
        nomes_etapas = {parcela.get('etapa', '') for parcela in parcelas}
        recebido_etapa = {
            etapa: sum(float(item.get('valor', 0)) for item in recebimentos if item.get('descricao') == etapa)
            for etapa in nomes_etapas
        }
        parcial = sum(
            float(item.get('valor', 0)) for item in recebimentos
            if item.get('descricao') not in nomes_etapas
        )
        for parcela in parcelas:
            etapa = parcela.get('etapa', 'Pagamento')
            previsto = float(parcela.get('valor', 0))
            pago = min(previsto, recebido_etapa.get(etapa, 0))
            aberto_parcial = max(0, previsto - pago)
            aplicado = min(aberto_parcial, parcial)
            pago += aplicado
            parcial -= aplicado
            restante = max(0, previsto - pago)
            if restante > 0:
                etapa_html = tag_etapa_html(etapa)
                linhas_parcelas.append(
                    f"<tr><td>{escape(orcamento['numero'])}</td><td>{escape(orcamento['cliente_nome'])}</td>"
                    f"<td>{etapa_html}</td><td>{escape(parcela.get('data_prevista', '-'))}</td>"
                    f"<td>{moeda(previsto)}</td><td>{moeda(pago)}</td><td>{moeda(restante)}</td></tr>"
                )
    linhas_parcelas_html = ''.join(linhas_parcelas) or '<tr><td colspan="7" class="muted">Nenhuma parcela pendente no período.</td></tr>'

    cards_indicadores = f"""
        <div class='cards'>
            <div class='card'><span class='muted'>Vendido/aprovado</span><strong class='indicador-vendido'>{moeda(total_vendido)}</strong></div>
            <div class='card'><span class='muted'>Recebido no período</span><strong class='indicador-recebido'>{moeda(total_recebido)}</strong></div>
            <div class='card'><span class='muted'>Em aberto</span><strong class='indicador-aberto{classe_aberto}'>{moeda(total_aberto)}</strong></div>
            <div class='card'><span class='muted'>Orçado no período</span><strong class='indicador-orcado'>{moeda(total_orcado_periodo)}</strong></div>
        </div>
    """
    filtro_periodo = f"""<form method='GET' action='/financeiro' class='linha filtro-periodo'><div><label>De</label><input type='date' name='inicio' value='{escape(inicio)}'></div><div><label>Até</label><input type='date' name='fim' value='{escape(fim)}'></div><div><button type='submit'>Aplicar período</button></div></form>"""
    def pagina_com_abas_financeiras(lancamentos_html):
        return pagina_base('/financeiro', f"""
            <style>
                .financeiro-tabs {{ display:grid; grid-template-columns:repeat(2,minmax(220px,300px)); gap:10px; margin:0 0 22px; padding:0 0 14px; border-bottom:1px solid var(--line); background:transparent; }}
                .financeiro-tabs button {{ width:100%; min-height:46px; padding:10px 16px; border:1px solid #dce5e0; border-radius:10px; background:#fff; color:#53645c; text-align:left; box-shadow:0 2px 7px #20342e08; }}
                .financeiro-tabs button.ativa {{ border-color:var(--green); background:var(--green); color:#fff; box-shadow:0 5px 14px #276b5828; }}
                .financeiro-pane[hidden] {{ display:none; }}
                .financeiro-pane {{ display:grid; gap:16px; }}
                .financeiro-pane#financeiro-lancamentos {{ max-width:1080px; align-content:start; }}
                .financeiro-pane > .panel {{ padding:22px; border-radius:14px; }}
                .indicador-vendido {{ color:#24496b !important; }} .indicador-recebido {{ color:#268052 !important; }}
                .indicador-aberto.zerado {{ color:#77827d !important; }} .indicador-aberto.alerta {{ color:#bd5d32 !important; }}
                .indicador-orcado {{ color:#7654a6 !important; }}
                .ranking-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; align-items:stretch; }}
                .ranking-card {{ height:100%; }} .tag-etapa {{ display:inline-flex; align-items:center; gap:5px; padding:4px 9px; border-radius:999px; font-size:12px; font-weight:650; white-space:nowrap; }}
                .tag-etapa.entrada {{ background:#e4f3e9; color:#286845; }} .tag-etapa.entrega {{ background:#e5f0fb; color:#315f8d; }}
                .tag-etapa.medicao {{ background:#fff2d5; color:#91621b; }} .tag-etapa.outra {{ background:#f0f1f0; color:#58635d; }}
                .financeiro-form {{ grid-template-columns:minmax(190px,1.5fr) minmax(130px,1fr) minmax(120px,.9fr) minmax(140px,1.1fr) minmax(140px,1fr) auto; align-items:end; margin:14px 0 0; }}
                .financeiro-form button {{ min-height:42px; width:auto; white-space:nowrap; }}
                .forma-pagamento-form {{ grid-template-columns:minmax(180px,1fr) minmax(220px,1.4fr) auto; align-items:end; }}
                @media(max-width:900px) {{ .financeiro-form {{ grid-template-columns:repeat(3,minmax(140px,1fr)); }} .financeiro-form button {{ width:100%; }} }}
                @media(max-width:700px) {{ .financeiro-tabs {{ grid-template-columns:1fr; }} .ranking-grid {{ grid-template-columns:1fr; }} .forma-pagamento-form {{ grid-template-columns:1fr; }} }}
            </style>
            <h2>Financeiro</h2>
            {filtro_periodo}
            <nav class='financeiro-tabs' aria-label='Seções do financeiro' role='tablist'>
                <button type='button' class='ativa' role='tab' aria-selected='true' data-pane='financeiro-visao'>📊 Visão Geral e Relatórios</button>
                <button type='button' role='tab' aria-selected='false' data-pane='financeiro-lancamentos'>💸 Lançamentos e Configurações</button>
            </nav>
            <section class='financeiro-pane' id='financeiro-visao' role='tabpanel'>{relatorios_html}</section>
            <section class='financeiro-pane' id='financeiro-lancamentos' role='tabpanel' hidden>{lancamentos_html}</section>
            <script>
                document.querySelectorAll('.financeiro-tabs [role="tab"]').forEach(botao => botao.addEventListener('click', () => {{
                    document.querySelectorAll('.financeiro-tabs [role="tab"]').forEach(aba => {{ const ativa = aba === botao; aba.classList.toggle('ativa', ativa); aba.setAttribute('aria-selected', ativa); }});
                    document.querySelectorAll('.financeiro-pane').forEach(painel => painel.hidden = painel.id !== botao.dataset.pane);
                }}));
            </script>
        """, usuario)

    formas = ''.join(
        f"<tr><td>{escape(forma['nome'])}</td><td>{escape(forma.get('descricao', ''))}</td><td><details><summary>Ações</summary><div class='acoes-menu'><form method='POST' action='/alterar_forma_pagamento'><input type='hidden' name='id' value='{escape(forma['id'])}'><label>Nome</label><input name='nome' value='{escape(forma['nome'])}' required><label>Descrição</label><input name='descricao' value='{escape(forma.get('descricao', ''))}'><button type='submit'>Salvar</button></form><form method='POST' action='/excluir_forma_pagamento'><input type='hidden' name='id' value='{escape(forma['id'])}'><button class='warning' type='submit'>Excluir forma</button></form></div></details></td></tr>"
        for forma in banco_formas_pagamento if forma.get('ativo', True)
    ) or '<tr><td colspan="3" class="muted">Nenhuma forma cadastrada.</td></tr>'
    recebimentos = ''.join(
        f"<tr><td>{escape(item.get('data', '')[:10])}</td><td>{escape(item.get('orcamento_numero', ''))}</td><td>{escape(item.get('cliente_nome', ''))}</td><td>{tag_etapa_html(item.get('descricao', ''))}</td><td>{moeda(item.get('valor', 0))}</td><td>{escape(item.get('usuario_nome', ''))}</td></tr>"
        for item in sorted(recebimentos_periodo, key=lambda item: item.get('data', ''), reverse=True)
    ) or '<tr><td colspan="6" class="muted">Sem recebimentos baixados no período.</td></tr>'
    auditoria = ''.join(
        f"<tr><td>{escape(item.get('data_hora', ''))}</td><td>{escape(item.get('usuario_nome', ''))}</td><td>{escape(item.get('acao', ''))}</td><td>{escape(item.get('entidade', ''))} {escape(item.get('entidade_id', ''))}</td><td>{escape(item.get('detalhes', ''))}</td></tr>"
        for item in reversed(banco_auditoria[-30:])
    ) or '<tr><td colspan="5" class="muted">Nenhuma alteração registrada.</td></tr>'
    relatorios_html = f"""
        {cards_indicadores}
        <div class='ranking-grid'>
            <div class='panel ranking-card'><h3>Formas de pagamento</h3><table><tr><th>Forma</th><th>Vendido</th></tr>{linhas_formas_ranking}</table></div>
            <div class='panel ranking-card'><h3>Clientes que mais compraram</h3><table><tr><th>Cliente</th><th>Compras</th></tr>{linhas_cliente}</table></div>
        </div>
        <div class='panel'><h3>Vendas por vendedor</h3><table><tr><th>Vendedor</th><th>Vendido</th></tr>{linhas_vendedor}</table></div>
        <div class='panel'><h3>Orçamentos com saldo em aberto</h3><table><tr><th>Orçamento</th><th>Cliente</th><th>Total</th><th>Recebido</th><th>Em aberto</th></tr>{linhas_abertos}</table><h3>Parcelas previstas pendentes</h3><table><tr><th>Orçamento</th><th>Cliente</th><th>Etapa</th><th>Previsão</th><th>Parcela</th><th>Recebido</th><th>Restante</th></tr>{linhas_parcelas_html}</table></div>
        <div class='panel'><h3>Recebimentos no período</h3><table><tr><th>Data</th><th>Orçamento</th><th>Cliente</th><th>Etapa</th><th>Valor</th><th>Responsável</th></tr>{recebimentos}</table></div>
        <details class='panel auditoria'><summary>Auditoria recente</summary><table><tr><th>Data/hora</th><th>Usuário</th><th>Ação</th><th>Registro</th><th>Detalhes</th></tr>{auditoria}</table></details>
    """

    if not pode_acessar(usuario, '/financeiro', escrever=True):
        formas_leitura = ''.join(
            f"<tr><td>{escape(forma.get('nome', ''))}</td><td>{escape(forma.get('descricao', ''))}</td></tr>"
            for forma in banco_formas_pagamento if forma.get('ativo', True)
        ) or '<tr><td colspan="2" class="muted">Nenhuma forma cadastrada.</td></tr>'
        lancamentos_html = f"<div class='panel'><h3>Formas de pagamento</h3><table><tr><th>Forma</th><th>Descrição</th></tr>{formas_leitura}</table></div>"
        return pagina_com_abas_financeiras(lancamentos_html)

    lancamentos_html = f"""
        <div class="panel"><h3>Formas de pagamento</h3><form method="POST" action="/salvar_forma_pagamento" class="forma-pagamento-form"><div><label>Nome</label><input name="nome" placeholder="Pix, cartão, transferência..." required></div><div><label>Descrição</label><input name="descricao"></div><button type="submit">Adicionar forma</button></form><table><tr><th>Forma</th><th>Descrição</th><th>Ações</th></tr>{formas}</table></div>
    """
    return pagina_com_abas_financeiras(lancamentos_html)

def campos_permissoes(permissoes=None):
    permissoes = permissoes or {}
    campos = []
    for rota, titulo in ABAS.items():
        nivel = permissoes.get(rota, 'nenhum')
        opcoes = ''.join(
            f"<option value='{valor}' {'selected' if nivel == valor else ''}>{rotulo}</option>"
            for valor, rotulo in [('nenhum', 'Sem acesso'), ('visualizar', 'Visualizar'), ('editar', 'Editar')]
        )
        campos.append(f"<div><label>{escape(titulo)}</label><select name='permissao_{escape(rota)}'>{opcoes}</select></div>")
    return ''.join(campos)

def renderizar_funcionarios(usuario=None):
    permissoes_opcoes = campos_permissoes()
    linhas_funcionarios = []
    for item in banco_usuarios:
        status = 'Administrador' if item.get('administrador') else 'Ativo' if item.get('ativo', True) else 'Inativo'
        permissoes_item = campos_permissoes(item.get('permissoes', {}))
        linhas_funcionarios.append(f"""
            <tr><td>{escape(item.get('nome', ''))}</td><td>{escape(item.get('login', ''))}</td><td>{status}</td>
            <td><details><summary>Alterar</summary><div class='acoes-menu'>
                <form method='POST' action='/alterar_funcionario'>
                    <input type='hidden' name='id' value='{escape(item['id'])}'>
                    <label>Nome</label><input name='nome' value='{escape(item.get('nome', ''))}' required>
                    <label>Login</label><input name='login' value='{escape(item.get('login', ''))}' required>
                    <label>Nova senha (deixe vazia para manter)</label><input name='senha' type='password' minlength='10'>
                    <div class='permissoes-grid'>{permissoes_item}</div>
                    <button type='submit'>Salvar permissões</button>
                </form>
                <form method='POST' action='/excluir_funcionario'><input type='hidden' name='id' value='{escape(item['id'])}'><button class='warning' type='submit'>Desativar funcionário</button></form>
            </div></details></td></tr>
        """)
    funcionarios = ''.join(linhas_funcionarios) or '<tr><td colspan="4" class="muted">Nenhum funcionário cadastrado.</td></tr>'
    return pagina_base('/funcionarios', f"""
        <style>.permissoes-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; }} .acoes-menu {{ position:absolute; z-index:3; right:0; width:min(600px,80vw); max-height:70vh; overflow:auto; padding:12px; border:1px solid #d4ded9; border-radius:6px; background:#fff; box-shadow:0 8px 24px #18231e22; }} details {{ position:relative; }}</style>
        <h2>Funcionários e permissões</h2>
        <div class="panel"><h3>Cadastrar funcionário</h3><form method="POST" action="/salvar_funcionario"><div class="linha"><div><label>Nome</label><input name="nome" required></div><div><label>Login</label><input name="login" autocomplete="off" required></div><div><label>Senha (mínimo 10 caracteres)</label><input name="senha" type="password" minlength="10" required></div></div><div class="permissoes-grid">{permissoes_opcoes}</div><button type="submit">Cadastrar funcionário</button></form></div>
        <div class="panel"><h3>Equipe cadastrada</h3><table><tr><th>Nome</th><th>Login</th><th>Status</th><th>Permissões</th></tr>{funcionarios}</table></div>
    """, usuario)

def renderizar_inicio(usuario=None):
    ativos = [o for o in banco_orcamentos if o.get('ativo', True)]
    em_analise = sum(1 for o in ativos if o.get('status', 'Em análise') == 'Em análise')
    em_producao = sum(1 for o in ativos if o.get('status') in ('Aprovado', 'Em produção'))
    total_aprovado = sum(float(o.get('valor_total', 0)) for o in ativos if o.get('status') in ('Aprovado', 'Em produção', 'Concluído', 'Vendido'))
    total_clientes = sum(1 for c in banco_clientes if c.get('ativo', True))
    descricoes = {
        '/orcamentos': 'Criar novo orçamento',
        '/clientes': 'Cadastro e orçamentos por cliente',
        '/historico': 'Pedidos, aprovações e revisões',
        '/materiais': 'Materiais, acabamentos e preços',
        '/financeiro': 'Recebimentos e formas de pagamento',
        '/funcionarios': 'Equipe e permissões',
        '/gerencial': 'Cores, textos e condições do PDF',
    }
    cores = {'/orcamentos': '#276b58', '/clientes': '#3b7ea1', '/historico': '#8a6fb0', '/materiais': '#b77936', '/financeiro': '#2f8f6b', '/funcionarios': '#c0576b', '/gerencial': '#5c6f82'}
    tiles = ''.join(
        f"<a class='tile' href='{rota}' style='--cor:{cores.get(rota, '#276b58')}'><span class='tile-icone'>{icone_svg(rota)}</span><strong>{titulo}</strong><small>{descricoes.get(rota, '')}</small></a>"
        for rota, titulo in ABAS.items()
        if pode_acessar(usuario, rota) and (rota != '/funcionarios' or usuario.get('administrador'))
    )
    primeiro_nome = escape((usuario or {}).get('nome', '').split(' ')[0])
    return pagina_base('/inicio', f"""
        <style>
            .inicio-saudacao {{ margin: 0 0 4px; font-size: 26px; }}
            .inicio-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; margin: 18px 0 26px; }}
            .kpi {{ padding: 16px 18px; border-radius: 12px; background: #fff; border: 1px solid var(--line); }}
            .kpi span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
            .kpi strong {{ font-size: 22px; color: var(--green-dark); }}
            .tiles {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 18px; }}
            .tile {{ display: flex; flex-direction: column; gap: 8px; padding: 22px; border-radius: 16px; background: #fff; border: 1px solid var(--line); text-decoration: none; color: var(--ink); transition: transform .15s ease, box-shadow .15s ease; }}
            .tile:hover {{ transform: translateY(-4px); box-shadow: 0 14px 28px #18231e1f; }}
            .tile-icone {{ display: grid; place-items: center; width: 56px; height: 56px; border-radius: 14px; background: color-mix(in srgb, var(--cor) 14%, white); color: var(--cor); }}
            .tile-icone svg {{ width: 30px; height: 30px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }}
            .tile strong {{ font-size: 16px; }}
            .tile small {{ color: var(--muted); font-size: 12.5px; }}
        </style>
        <h2 class="inicio-saudacao">Olá, {primeiro_nome}</h2>
        <p class="muted">Escolha um módulo para começar.</p>
        <div class="inicio-kpis">
            <div class="kpi"><span>Orçamentos em análise</span><strong>{em_analise}</strong></div>
            <div class="kpi"><span>Pedidos em produção</span><strong>{em_producao}</strong></div>
            <div class="kpi"><span>Total aprovado</span><strong>{moeda(total_aprovado)}</strong></div>
            <div class="kpi"><span>Clientes</span><strong>{total_clientes}</strong></div>
        </div>
        <div class="tiles">{tiles}</div>
    """, usuario)

def renderizar_pagina(caminho, usuario=None, parametros=None):
    rota = caminho if caminho in ABAS or caminho == '/inicio' else '/inicio'
    if rota == '/inicio':
        return renderizar_inicio(usuario)
    if rota == '/orcamentos':
        return renderizar_orcamentos(usuario, (parametros or {}).get('cliente', [''])[0], (parametros or {}).get('baixar', [''])[0], (parametros or {}).get('editar', [''])[0], (parametros or {}).get('sucesso', [''])[0] == '1')
    if rota == '/clientes':
        return renderizar_clientes(usuario)
    if rota == '/historico':
        return renderizar_historico(usuario, (parametros or {}).get('ordem', ['recentes'])[0])
    if rota == '/materiais':
        return renderizar_materiais(usuario)
    if rota == '/gerencial':
        return renderizar_modelo_pdf(usuario)
    if rota == '/financeiro':
        return renderizar_financeiro(usuario)
    if rota == '/funcionarios':
        return renderizar_funcionarios(usuario)
    if rota == '/plano':
        return pagina_base('/plano', conteudo_plano_corte(banco_materiais, banco_orcamentos), usuario)
    return renderizar_orcamentos(usuario)

def renderizar_login():
    if not banco_usuarios:
        conteudo = """
        <h2>Configuração inicial</h2>
        <div class="panel login-panel">
            <img src="/logo.png" alt="Catalão Mármores e Granitos" class="logo-login">
            <p>Cadastre o primeiro administrador para começar a usar o sistema.</p>
            <form method="POST" action="/configurar_administrador">
                <div><label>Nome</label><input name="nome" required></div>
                <div><label>Login</label><input name="login" autocomplete="username" required></div>
                <div><label>Senha (mínimo 10 caracteres)</label><input name="senha" type="password" autocomplete="new-password" minlength="10" required></div>
                <button type="submit">Criar administrador</button>
            </form>
        </div>
        """
    else:
        conteudo = """
        <h2>Acessar sistema</h2>
        <div class="panel login-panel">
            <img src="/logo.png" alt="Catalão Mármores e Granitos" class="logo-login">
            <form method="POST" action="/entrar">
                <div><label>Login</label><input name="login" autocomplete="username" required></div>
                <div><label>Senha</label><input name="senha" type="password" autocomplete="current-password" required></div>
                <button type="submit">Entrar</button>
            </form>
        </div>
        """
    return pagina_base('', conteudo)

class MeuServidor(SimpleHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        caminho = url.path or '/orcamentos'
        parametros = parse_qs(url.query)
        usuario = usuario_da_requisicao(self)

        if caminho == '/logo.png':
            if not os.path.isfile(LOGO_FILE):
                self.send_error(404)
                return
            with open(LOGO_FILE, 'rb') as imagem:
                conteudo_logo = imagem.read()
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(conteudo_logo)))
            self.end_headers()
            self.wfile.write(conteudo_logo)
            return

        if caminho in ('/', '/login'):
            if usuario:
                redirecionar(self, '/inicio')
                return
            pagina = renderizar_login()
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(pagina.encode('utf-8'))
            return

        if not banco_usuarios:
            redirecionar(self, '/login')
            return
        if not usuario:
            redirecionar(self, '/login')
            return

        if caminho == '/emitir_orcamento':
            if not (pode_acessar(usuario, '/historico') or pode_acessar(usuario, '/orcamentos')):
                self.send_error(403, 'Sem permissão para visualizar orçamentos')
                return
            numero = parametros.get('id', [''])[0]
            orcamento = next((item for item in banco_orcamentos if item['numero'] == numero), None)
            if not orcamento:
                self.send_response(404)
                self.end_headers()
                return

            arquivo_pdf = gerar_pdf_orcamento(orcamento)
            with open(arquivo_pdf, 'rb') as arquivo:
                conteudo = arquivo.read()

            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            nome_download = os.path.basename(arquivo_pdf)
            nome_ascii = unicodedata.normalize('NFKD', nome_download).encode('ascii', 'ignore').decode('ascii') or 'orcamento.pdf'
            self.send_header('Content-Disposition', f"attachment; filename=\"{nome_ascii}\"; filename*=UTF-8''{quote(nome_download)}")
            self.send_header('Content-Length', str(len(conteudo)))
            self.end_headers()
            self.wfile.write(conteudo)
            return

        if caminho not in ABAS and caminho != '/inicio':
            self.send_error(404)
            return
        if caminho == '/funcionarios' and not usuario.get('administrador'):
            self.send_error(403, 'Apenas administradores podem gerenciar funcionários')
            return
        if not pode_acessar(usuario, caminho):
            self.send_error(403, 'Você não tem permissão para acessar esta aba')
            return

        if caminho == '/clientes':
            pagina = renderizar_clientes(usuario, parametros.get('q', [''])[0].strip())
        elif caminho == '/materiais':
            pagina = renderizar_materiais(usuario, parametros.get('q', [''])[0].strip())
        elif caminho == '/financeiro':
            pagina = renderizar_financeiro(usuario, parametros.get('inicio', [''])[0], parametros.get('fim', [''])[0])
        elif caminho == '/funcionarios':
            pagina = renderizar_funcionarios(usuario)
        else:
            pagina = renderizar_pagina(caminho, usuario, parametros)
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(pagina.encode("utf-8"))

    def do_POST(self):
        tamanho_dados = int(self.headers.get('Content-Length', 0))
        dados_brutos = self.rfile.read(tamanho_dados).decode('utf-8')
        dados = parse_qs(dados_brutos, keep_blank_values=True)

        def valor(chave, padrao=''):
            return dados.get(chave, [padrao])[0]

        caminho = urlparse(self.path).path
        if caminho == '/configurar_administrador':
            if banco_usuarios:
                redirecionar(self, '/login')
                return
            nome = valor('nome').strip()
            login = valor('login').strip().casefold()
            senha = valor('senha')
            if not nome or not login or len(senha) < 10:
                redirecionar(self, '/login?erro=validacao')
                return
            administrador = {
                'id': novo_id('USR'),
                'nome': nome,
                'login': login,
                'senha_hash': criar_hash_senha(senha),
                'administrador': True,
                'permissoes': {rota: 'editar' for rota in ABAS},
                'ativo': True,
            }
            banco_usuarios.append(administrador)
            registrar_auditoria(administrador, 'criou', 'administrador', administrador['id'], 'Configuração inicial')
            token = secrets.token_urlsafe(32)
            SESSOES[token] = administrador['id']
            self.send_response(303)
            self.send_header('Location', '/inicio')
            self.send_header('Set-Cookie', f'sessao={token}; HttpOnly; SameSite=Lax; Path=/')
            self.end_headers()
            return

        if caminho == '/entrar':
            login = valor('login').strip().casefold()
            senha = valor('senha')
            usuario = next((item for item in banco_usuarios if item.get('login', '').casefold() == login and item.get('ativo', True)), None)
            if not usuario or not validar_senha(senha, usuario.get('senha_hash')):
                redirecionar(self, '/login?erro=credenciais')
                return
            token = secrets.token_urlsafe(32)
            SESSOES[token] = usuario['id']
            registrar_auditoria(usuario, 'entrou', 'sessao', usuario['id'])
            self.send_response(303)
            self.send_header('Location', '/inicio')
            self.send_header('Set-Cookie', f'sessao={token}; HttpOnly; SameSite=Lax; Path=/')
            self.end_headers()
            return

        if caminho == '/sair':
            usuario = usuario_da_requisicao(self)
            if usuario:
                registrar_auditoria(usuario, 'saiu', 'sessao', usuario['id'])
            cookie_header = self.headers.get('Cookie', '')
            cookies = SimpleCookie()
            cookies.load(cookie_header)
            cookie = cookies.get('sessao')
            if cookie:
                SESSOES.pop(cookie.value, None)
            redirecionar(self, '/login', limpar_sessao=True)
            return

        usuario = usuario_da_requisicao(self)
        if not usuario:
            redirecionar(self, '/login')
            return

        if caminho == '/sair':
            registrar_auditoria(usuario, 'saiu', 'sessao', usuario['id'])
            cookies = SimpleCookie()
            cookies.load(self.headers.get('Cookie', ''))
            cookie = cookies.get('sessao')
            if cookie:
                SESSOES.pop(cookie.value, None)
            redirecionar(self, '/login', limpar_sessao=True)
            return
        if caminho == '/plano_pdf':
            if not pode_acessar(usuario, '/plano'):
                self.send_error(403, 'Sem permissão')
                return
            projeto_json = valor('projeto', '')
            try:
                projeto = json.loads(projeto_json)
            except (ValueError, TypeError):
                self.send_error(400, 'JSON inválido')
                return
            nome_pdf = f'plano_{datetime.now().strftime("%Y%m%d%H%M%S")}.pdf'
            caminho_pdf = os.path.join(PDF_DIR, nome_pdf)
            try:
                gerar_pdf_plano(projeto, caminho_pdf, LOGO_FILE)
                with open(caminho_pdf, 'rb') as arq:
                    conteudo_pdf = arq.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Disposition', f'attachment; filename="{nome_pdf}"')
                self.send_header('Content-Length', str(len(conteudo_pdf)))
                self.end_headers()
                self.wfile.write(conteudo_pdf)
            except Exception as erro:
                self.send_error(500, f'Erro ao gerar PDF: {erro}')
            return

        rotas_post = {
            '/salvar_cliente': '/clientes',
            '/alterar_cliente': '/clientes',
            '/excluir_cliente': '/clientes',
            '/salvar_material': '/materiais',
            '/alterar_material': '/materiais',
            '/excluir_material': '/materiais',
            '/salvar_orcamento': '/orcamentos',
            '/salvar_forma_pagamento': '/financeiro',
            '/salvar_modelo_pdf': '/gerencial',
            '/alterar_forma_pagamento': '/financeiro',
            '/excluir_forma_pagamento': '/financeiro',
            '/registrar_recebimento': '/financeiro',
            '/alterar_orcamento': '/historico',
            '/aprovar_orcamento': '/historico',
            '/concluir_orcamento': '/historico',
            '/excluir_orcamento': '/historico',
            '/salvar_funcionario': '/funcionarios',
            '/alterar_funcionario': '/funcionarios',
            '/excluir_funcionario': '/funcionarios',
        }
        rota_permitida = rotas_post.get(caminho)
        if not rota_permitida or not pode_acessar(usuario, rota_permitida, escrever=True):
            self.send_error(403, 'Você não tem permissão para realizar esta alteração')
            return
        if rota_permitida == '/funcionarios' and not usuario.get('administrador'):
            self.send_error(403, 'Apenas administradores podem gerenciar funcionários')
            return

        if caminho == '/salvar_cliente':
            nome = valor('nome').strip()
            if nome:
                cliente_id = novo_id('CLI')
                banco_clientes.append({
                    "id": cliente_id,
                    "nome": nome,
                    "telefone": valor('telefone', ''),
                    "endereco": valor('endereco', valor('cidade', '')),
                    "observacoes": valor('observacoes', ''),
                    "ativo": True,
                })
                registrar_auditoria(usuario, 'criou', 'cliente', cliente_id, nome)
            self.send_response(303)
            self.send_header('Location', '/clientes')
            self.end_headers()
            return

        if caminho == '/alterar_cliente':
            cliente = next((item for item in banco_clientes if item.get('id') == valor('id') and item.get('ativo', True)), None)
            nome = valor('nome').strip()
            if cliente and nome:
                cliente.update({
                    'nome': nome,
                    'telefone': valor('telefone', ''),
                    'endereco': valor('endereco', ''),
                    'observacoes': valor('observacoes', ''),
                })
                registrar_auditoria(usuario, 'alterou', 'cliente', cliente['id'], nome)
            redirecionar(self, '/clientes')
            return

        if caminho == '/excluir_cliente':
            cliente = next((item for item in banco_clientes if item.get('id') == valor('id') and item.get('ativo', True)), None)
            if cliente:
                cliente['ativo'] = False
                registrar_auditoria(usuario, 'excluiu', 'cliente', cliente['id'], cliente.get('nome', ''))
            redirecionar(self, '/clientes')
            return

        if caminho == '/salvar_material':
            codigo = valor('codigo').strip()
            nome = valor('nome').strip()
            if codigo and nome:
                tipo = valor('tipo', 'material')
                unidade = {
                    'material': valor('unidade_material', 'm²'),
                    'acabamento': valor('unidade_acabamento', 'm²'),
                    'servico': valor('unidade_servico', 'unidade'),
                }.get(tipo, 'm²')
                preco_linear = float(valor('preco_linear', '0') or '0')
                preco_formulario = {
                    'material': valor('preco_material', '0'),
                    'acabamento': valor('preco_unitario', '0'),
                    'servico': valor('preco_servico', '0'),
                }.get(tipo, '0')
                if tipo not in ('material', 'acabamento', 'servico'):
                    tipo = 'material'
                if tipo == 'material':
                    unidade = 'm²'
                elif unidade not in ('m²', 'metro linear', 'unidade', 'm² + linear'):
                    unidade = 'm²'
                material_id = novo_id('MAT')
                base = next((m for m in banco_materiais if m.get('id') == valor('material_base_id') and m.get('ativo', True)), None)
                preco_principal = float(base['preco_unitario']) if base and unidade == 'm² + linear' else float(preco_formulario or '0')
                banco_materiais.append({
                    "id": material_id,
                    "tipo": tipo,
                    "codigo": codigo,
                    "nome": nome,
                    "categoria": valor('categoria', 'Geral'),
                    "unidade": unidade,
                    "preco_unitario": preco_principal,
                    "preco_linear": preco_linear,
                    "material_base_id": base['id'] if base else '',
                    "largura_m": float(valor('largura_m', '0') or '0'),
                    "permite_auxiliar": valor('permite_auxiliar') == '1',
                    "ativo": True,
                })
                registrar_auditoria(usuario, 'criou', 'material', material_id, nome)
            self.send_response(303)
            self.send_header('Location', '/materiais')
            self.end_headers()
            return

        if caminho == '/alterar_material':
            material = next((item for item in banco_materiais if item.get('id') == valor('id') and item.get('ativo', True)), None)
            nome = valor('nome').strip()
            tipo = valor('tipo', 'material')
            unidade = valor('unidade', 'm²')
            try:
                preco = float(valor('preco_unitario', '0') or '0')
                preco_linear = float(valor('preco_linear', '0'))
                largura_m = float(valor('largura_m', '0') or '0')
            except ValueError:
                preco = -1
                preco_linear = -1
                largura_m = -1
            base = next((m for m in banco_materiais if m.get('id') == valor('material_base_id') and m.get('ativo', True)), None)
            if base and unidade == 'm² + linear':
                preco = float(base['preco_unitario'])
            if material and nome and tipo in ('material', 'acabamento', 'servico') and preco >= 0 and preco_linear >= 0 and largura_m >= 0:
                tipo_anterior = material.get('tipo', 'material')
                vinculado = any(
                    orcamento.get('material_id') == material['id']
                    or any(item.get('material_id') == material['id'] or any(acab.get('acabamento_id') == material['id'] for acab in item.get('acabamentos', [])) for item in orcamento.get('itens', []))
                    for orcamento in banco_orcamentos
                )
                if not vinculado or tipo == tipo_anterior:
                    material.update({
                        'tipo': tipo,
                        'codigo': valor('codigo').strip(),
                        'nome': nome,
                        'categoria': valor('categoria', 'Geral').strip(),
                        'unidade': 'm²' if tipo == 'material' else unidade if unidade in ('m²', 'metro linear', 'unidade', 'm² + linear') else 'm²',
                        'preco_unitario': preco,
                        'preco_linear': preco_linear,
                        'material_base_id': base['id'] if base else '',
                        'largura_m': largura_m,
                        'permite_auxiliar': valor('permite_auxiliar') == '1',
                    })
                    registrar_auditoria(usuario, 'alterou', 'material', material['id'], nome)
            redirecionar(self, '/materiais')
            return

        if caminho == '/excluir_material':
            material = next((item for item in banco_materiais if item.get('id') == valor('id') and item.get('ativo', True)), None)
            if material:
                material['ativo'] = False
                registrar_auditoria(usuario, 'excluiu', 'material', material['id'], material.get('nome', ''))
            redirecionar(self, '/materiais')
            return

        if caminho == '/salvar_modelo_pdf':
            def linhas_modelo(chave):
                return [linha.strip() for linha in valor(chave).splitlines() if linha.strip()]

            def cor_modelo(chave):
                cor = valor(chave).strip()
                return cor if len(cor) == 7 and cor.startswith('#') and all(c in '0123456789abcdefABCDEF' for c in cor[1:]) else MODELO_PDF_PADRAO[chave]

            dados_geral['modelo_pdf'] = {
                'cor_principal': cor_modelo('cor_principal'),
                'cor_total': cor_modelo('cor_total'),
                'titulo_orcamento': valor('titulo_orcamento').strip(),
                'titulo_pedido': valor('titulo_pedido').strip(),
                'texto_liberacao': valor('texto_liberacao').strip(),
                'condicoes': linhas_modelo('condicoes'),
                'acessorios': linhas_modelo('acessorios'),
                'obra': linhas_modelo('obra'),
                'confirmacao': valor('confirmacao').strip(),
                'empresa': valor('empresa').strip(),
                'cnpj': valor('cnpj').strip(),
            }
            registrar_auditoria(usuario, 'alterou', 'modelo_pdf', 'modelo', 'Modelo do PDF do orçamento')
            redirecionar(self, '/gerencial')
            return

        if caminho == '/salvar_forma_pagamento':
            nome = valor('nome').strip()
            if nome and not any(item.get('nome', '').casefold() == nome.casefold() and item.get('ativo', True) for item in banco_formas_pagamento):
                forma_id = novo_id('PAG')
                banco_formas_pagamento.append({'id': forma_id, 'nome': nome, 'descricao': valor('descricao').strip(), 'ativo': True})
                registrar_auditoria(usuario, 'criou', 'forma de pagamento', forma_id, nome)
            redirecionar(self, '/financeiro')
            return

        if caminho == '/alterar_forma_pagamento':
            forma = next((item for item in banco_formas_pagamento if item.get('id') == valor('id') and item.get('ativo', True)), None)
            nome = valor('nome').strip()
            if forma and nome:
                forma.update({'nome': nome, 'descricao': valor('descricao').strip()})
                registrar_auditoria(usuario, 'alterou', 'forma de pagamento', forma['id'], nome)
            redirecionar(self, '/financeiro')
            return

        if caminho == '/excluir_forma_pagamento':
            forma = next((item for item in banco_formas_pagamento if item.get('id') == valor('id') and item.get('ativo', True)), None)
            if forma:
                forma['ativo'] = False
                registrar_auditoria(usuario, 'excluiu', 'forma de pagamento', forma['id'], forma.get('nome', ''))
            redirecionar(self, '/financeiro')
            return

        if caminho == '/registrar_recebimento':
            numero = valor('orcamento_numero')
            orcamento = next((item for item in banco_orcamentos if item.get('numero') == numero), None)
            forma = next((item for item in banco_formas_pagamento if item.get('id') == valor('forma_pagamento_id') and item.get('ativo', True)), None)
            try:
                quantia = round(float(valor('valor')), 2)
            except ValueError:
                quantia = 0
            recebido = recebido_orcamento(numero)
            saldo = round(float(orcamento.get('valor_total', 0)) - recebido, 2) if orcamento else 0
            status_recebivel = ('Aprovado', 'Em produção', 'Concluído', 'Vendido')
            if orcamento and orcamento.get('status') in status_recebivel and forma and 0 < quantia <= saldo:
                recebimento_id = novo_id('REC')
                recebimento = {
                    'id': recebimento_id,
                    'orcamento_numero': numero,
                    'cliente_nome': orcamento.get('cliente_nome', ''),
                    'descricao': valor('etapa', 'Pagamento parcial'),
                    'forma_pagamento_id': forma['id'],
                    'forma_pagamento_nome': forma['nome'],
                    'valor': quantia,
                    'data': valor('data') or datetime.now().date().isoformat(),
                    'usuario_id': usuario['id'],
                    'usuario_nome': usuario['nome'],
                }
                banco_recebimentos.append(recebimento)
                registrar_auditoria(usuario, 'registrou recebimento', 'orçamento', numero, f'{moeda(quantia)} - {recebimento["descricao"]}')
            redirecionar(self, '/historico')
            return

        if caminho == '/salvar_funcionario':
            nome = valor('nome').strip()
            login = valor('login').strip().casefold()
            senha = valor('senha')
            login_existe = any(item.get('login', '').casefold() == login for item in banco_usuarios)
            if nome and login and len(senha) >= 10 and not login_existe:
                funcionario_id = novo_id('USR')
                permissoes = {rota: valor(f'permissao_{rota}', 'nenhum') for rota in ABAS}
                permissoes = {rota: nivel if nivel in ('nenhum', 'visualizar', 'editar') else 'nenhum' for rota, nivel in permissoes.items()}
                banco_usuarios.append({
                    'id': funcionario_id,
                    'nome': nome,
                    'login': login,
                    'senha_hash': criar_hash_senha(senha),
                    'administrador': False,
                    'permissoes': permissoes,
                    'ativo': True,
                })
                registrar_auditoria(usuario, 'cadastrou funcionário', 'funcionário', funcionario_id, f'{nome} ({login})')
            redirecionar(self, '/funcionarios')
            return

        if caminho == '/alterar_funcionario':
            funcionario = next((item for item in banco_usuarios if item.get('id') == valor('id') and item.get('ativo', True)), None)
            nome = valor('nome').strip()
            login = valor('login').strip().casefold()
            senha = valor('senha')
            login_existe = any(item.get('id') != valor('id') and item.get('login', '').casefold() == login for item in banco_usuarios)
            if funcionario and nome and login and not login_existe and (not senha or len(senha) >= 10):
                funcionario.update({'nome': nome, 'login': login})
                funcionario['permissoes'] = {
                    rota: valor(f'permissao_{rota}', 'nenhum')
                    if valor(f'permissao_{rota}', 'nenhum') in ('nenhum', 'visualizar', 'editar') else 'nenhum'
                    for rota in ABAS
                }
                if senha:
                    funcionario['senha_hash'] = criar_hash_senha(senha)
                registrar_auditoria(usuario, 'alterou funcionário', 'funcionário', funcionario['id'], f'{nome} ({login})')
            redirecionar(self, '/funcionarios')
            return

        if caminho == '/excluir_funcionario':
            funcionario = next((item for item in banco_usuarios if item.get('id') == valor('id') and item.get('ativo', True)), None)
            if funcionario and funcionario.get('id') != usuario.get('id'):
                if not funcionario.get('administrador') or sum(1 for item in banco_usuarios if item.get('administrador') and item.get('ativo', True)) > 1:
                    funcionario['ativo'] = False
                    registrar_auditoria(usuario, 'desativou funcionário', 'funcionário', funcionario['id'], funcionario.get('nome', ''))
                    for token, usuario_id in list(SESSOES.items()):
                        if usuario_id == funcionario['id']:
                            SESSOES.pop(token, None)
            redirecionar(self, '/funcionarios')
            return

        if caminho == '/alterar_orcamento':
            numero = valor('numero')
            orcamento = next((item for item in banco_orcamentos if item.get('numero') == numero and item.get('ativo', True)), None)
            try:
                entrada_valor = round(float(valor('entrada_valor', orcamento.get('entrada_valor', 0) if orcamento else 0)), 2)
                prazo_entrega_dias = int(valor('prazo_entrega_dias', orcamento.get('prazo_entrega_dias', 6) if orcamento else 6))
            except ValueError:
                entrada_valor = -1
                prazo_entrega_dias = 0
            if orcamento and 0 <= entrada_valor <= float(orcamento.get('valor_total', 0)) and prazo_entrega_dias > 0:
                total = float(orcamento.get('valor_total', 0))
                saldo = round(total - entrada_valor, 2)
                data_orcamento = datetime.strptime(orcamento.get('data', datetime.now().date().isoformat()), '%Y-%m-%d').date()
                orcamento['observacoes'] = valor('observacoes', '').strip()
                orcamento['entrada_valor'] = entrada_valor
                orcamento['entrada_percentual'] = round(entrada_valor * 100 / total, 2) if total else 0
                orcamento['prazo_entrega_dias'] = prazo_entrega_dias
                orcamento['parcelas_previstas'] = [
                    {'etapa': 'Entrada', 'valor': entrada_valor, 'data_prevista': data_orcamento.isoformat()},
                    {'etapa': 'Entrega do material', 'valor': saldo, 'data_prevista': (data_orcamento + timedelta(days=prazo_entrega_dias)).isoformat()},
                ]
                orcamento['revisao'] = int(orcamento.get('revisao', 0)) + 1
                orcamento['revisado_por'] = usuario['nome']
                orcamento['revisado_em'] = datetime.now().isoformat(timespec='seconds')
                registrar_auditoria(usuario, 'revisou orçamento', 'orçamento', numero, f"Revisão {orcamento['revisao']}")
            redirecionar(self, '/historico')
            return

        if caminho == '/aprovar_orcamento':
            numero = valor('numero')
            orcamento = next((item for item in banco_orcamentos if item.get('numero') == numero and item.get('ativo', True)), None)
            if orcamento and orcamento.get('status', 'Em análise') == 'Em análise':
                orcamento['status'] = 'Em produção'
                orcamento['aprovado'] = True
                orcamento['aprovado_por'] = usuario['nome']
                orcamento['aprovado_em'] = datetime.now().isoformat(timespec='seconds')
                registrar_auditoria(usuario, 'aprovou e iniciou produção', 'orçamento', numero)
            redirecionar(self, '/historico')
            return

        if caminho == '/concluir_orcamento':
            numero = valor('numero')
            orcamento = next((item for item in banco_orcamentos if item.get('numero') == numero and item.get('ativo', True)), None)
            if orcamento and orcamento.get('status') == 'Em produção':
                orcamento['status'] = 'Concluído'
                orcamento['concluido_por'] = usuario['nome']
                orcamento['concluido_em'] = datetime.now().isoformat(timespec='seconds')
                registrar_auditoria(usuario, 'concluiu orçamento', 'orçamento', numero)
            redirecionar(self, '/historico')
            return

        if caminho == '/excluir_orcamento':
            numero = valor('numero')
            orcamento = next((item for item in banco_orcamentos if item.get('numero') == numero and item.get('ativo', True)), None)
            if orcamento:
                orcamento['ativo'] = False
                orcamento['status'] = 'Cancelado'
                registrar_auditoria(usuario, 'arquivou orçamento', 'orçamento', numero)
            redirecionar(self, '/historico')
            return

        if caminho == '/salvar_orcamento':
            numero_novo = ''
            cliente_id = valor('cliente_id')
            cliente = next((item for item in banco_clientes if item['id'] == cliente_id), None)

            itens = []
            valor_total = 0.0
            try:
                materiais_ids = dados.get('item_material_id', [])
                descricoes = dados.get('item_descricao', [])
                comprimentos = dados.get('item_comprimento', [])
                larguras = dados.get('item_largura', [])
                observacoes_itens = dados.get('item_observacao', [])
                quantidades_pecas = dados.get('item_quantidade_pecas', [])
                
                if not (len(materiais_ids) == len(descricoes) == len(comprimentos) == len(larguras)):
                    raise ValueError('Itens incompletos')

                for indice, material_id in enumerate(materiais_ids):
                    material = next((item for item in banco_materiais if item['id'] == material_id and item.get('ativo', True) and (item.get('tipo', 'material') == 'material' or (item.get('tipo') == 'acabamento' and item.get('unidade') == 'm² + linear'))), None)
                    comprimento = float(comprimentos[indice])
                    largura = float(larguras[indice])
                    descricao = descricoes[indice].strip()
                    observacao_item = observacoes_itens[indice].strip() if indice < len(observacoes_itens) else ''
                    qtd_pecas = int(quantidades_pecas[indice]) if indice < len(quantidades_pecas) and quantidades_pecas[indice] else 1
                    
                    if not material or not descricao or comprimento <= 0 or largura <= 0 or qtd_pecas < 1:
                        raise ValueError('Item inválido')

                    item_combinado = material.get('tipo') == 'acabamento' and material.get('unidade') == 'm² + linear'
                    if item_combinado:
                        largura = float(material.get('largura_m', 0) or 0)
                        if largura <= 0 or float(material.get('preco_linear', 0) or 0) < 0:
                            raise ValueError('Largura ou preço linear inválido no cadastro do acabamento')
                    area = comprimento * largura
                    preco_material = preco_m2_acabamento(material) if item_combinado else float(material['preco_unitario'])
                    preco_linear_item = float(material.get('preco_linear', 0) or 0) if item_combinado else 0
                    material_base = next((base for base in banco_materiais if base.get('id') == material.get('material_base_id') and base.get('ativo', True)), {}) if item_combinado else {}
                    total_item = (area * preco_material + comprimento * preco_linear_item) * qtd_pecas
                    acabamentos = []
                    acabamentos_ids = dados.get(f'acabamento_id_{indice}', [])
                    acabamentos_descricoes = dados.get(f'acabamento_descricao_{indice}', [])
                    acabamentos_quantidades = dados.get(f'acabamento_quantidade_{indice}', [])
                    acabamentos_larguras = dados.get(f'acabamento_largura_{indice}', [])
                    acabamentos_aux = dados.get(f'acabamento_aux_{indice}', [])
                    
                    if not (len(acabamentos_ids) == len(acabamentos_descricoes) == len(acabamentos_quantidades) == len(acabamentos_larguras)):
                        raise ValueError('Acabamentos incompletos')

                    for posicao_acabamento, (acabamento_id, detalhe, medida_texto, largura_texto) in enumerate(zip(acabamentos_ids, acabamentos_descricoes, acabamentos_quantidades, acabamentos_larguras)):
                        acabamento = next((item for item in banco_materiais if item['id'] == acabamento_id and item.get('tipo') in ('acabamento', 'servico')), None)
                        medida = float(medida_texto)
                        largura_acabamento = float(largura_texto)
                        detalhe = detalhe.strip()
                        if not acabamento or not detalhe or medida <= 0:
                            raise ValueError('Acabamento inválido')
                        
                        unidade = acabamento.get('unidade', 'metro linear')
                        preco_unitario = preco_m2_acabamento(acabamento)
                        preco_linear = float(acabamento.get('preco_linear', 0))
                        largura_cadastrada = float(acabamento.get('largura_m', 0) or 0)
                        registro_acabamento = {
                            'acabamento_id': acabamento['id'],
                            'nome': acabamento['nome'],
                            'descricao': detalhe,
                            'unidade': unidade,
                            'preco_unitario': preco_unitario,
                            'medida': medida,
                            'largura_m': largura_acabamento,
                            'auxiliar': posicao_acabamento < len(acabamentos_aux) and acabamentos_aux[posicao_acabamento] == '1',
                            'quantidade_pecas': qtd_pecas
                        }
                        
                        if unidade == 'm² + linear':
                            if largura_cadastrada <= 0 or preco_linear < 0:
                                raise ValueError('Largura da faixa ou tarifa linear inválida no cadastro')
                            quantidade_m2 = medida * largura_cadastrada
                            subtotal_m2 = quantidade_m2 * preco_unitario
                            subtotal_linear = medida * preco_linear
                            subtotal = (subtotal_m2 + subtotal_linear) * qtd_pecas
                            registro_acabamento.update({
                                'quantidade': medida,
                                'quantidade_m2': quantidade_m2,
                                'quantidade_linear': medida,
                                'altura_m': largura_cadastrada,
                                'preco_linear': preco_linear,
                                'valor_m2': subtotal_m2 * qtd_pecas,
                                'valor_linear': subtotal_linear * qtd_pecas,
                            })
                        else:
                            if unidade == 'm²' and largura_acabamento <= 0:
                                raise ValueError('Largura de acabamento inválida')
                            quantidade_acabamento = medida * largura_acabamento if unidade == 'm²' else medida
                            subtotal = quantidade_acabamento * preco_unitario * qtd_pecas
                            registro_acabamento['quantidade'] = quantidade_acabamento
                        
                        registro_acabamento['valor_total'] = subtotal
                        acabamentos.append(registro_acabamento)
                        total_item += subtotal

                    itens.append({
                        'descricao': descricao,
                        'observacao_item': observacao_item,
                        'material_id': material['id'],
                        'material_nome': material['nome'],
                        'comprimento': comprimento,
                        'largura': largura,
                        'area_m2': area,
                        'preco_material_m2': preco_material,
                        'valor_material': area * preco_material * qtd_pecas,
                        'unidade_principal': 'm² + linear' if item_combinado else 'm²',
                        'material_base_nome': material_base.get('nome', ''),
                        'preco_linear_principal': preco_linear_item,
                        'valor_linear_principal': comprimento * preco_linear_item * qtd_pecas,
                        'acabamentos': acabamentos,
                        'quantidade_pecas': qtd_pecas,
                        'valor_total': total_item,
                    })
                    valor_total += total_item
            except (ValueError, TypeError) as e:
                print("ERRO NO ORÇAMENTO:", e)
                itens = []
                
            forma_id = valor('forma_pagamento_id')
            forma_pagamento = next((item for item in banco_formas_pagamento if item.get('id') == forma_id and item.get('ativo', True)), None)
            try:
                entrada_valor = round(float(valor('entrada_valor', '0')), 2)
                prazo_entrega_dias = int(valor('prazo_entrega_dias', '6'))
                desconto_percentual = float(valor('desconto_percentual', '0'))
                gordura_percentual = float(valor('gordura_percentual', '0'))
            except ValueError:
                entrada_valor = -1
                prazo_entrega_dias = 0
                desconto_percentual = -1
                gordura_percentual = -1
            if not (0 <= desconto_percentual <= 100 and 0 <= gordura_percentual <= 100):
                itens = []
            subtotal_itens = round(valor_total, 2)
            for item in itens:
                item['valor_total_com_gordura'] = round(float(item['valor_total']) * (1 + gordura_percentual / 100), 2)
            subtotal_com_gordura = round(sum(float(item.get('valor_total_com_gordura', item['valor_total'])) for item in itens), 2)
            desconto_valor = round(subtotal_com_gordura * desconto_percentual / 100, 2)
            total_final = round(subtotal_com_gordura - desconto_valor, 2)
            if cliente and itens and forma_pagamento and 0 <= entrada_valor <= total_final and prazo_entrega_dias > 0:
                numero_edicao = valor('orcamento_numero').strip()
                orcamento_existente = next((o for o in banco_orcamentos if o.get('numero') == numero_edicao and o.get('ativo', True)), None)
                numero = orcamento_existente['numero'] if orcamento_existente else novo_numero_orcamento()
                numero_novo = numero
                primeiro_item = itens[0]
                nomes_materiais = ', '.join(dict.fromkeys(item['material_nome'] for item in itens))
                valor_entrega = round(total_final - entrada_valor, 2)
                data_orcamento = datetime.now().date()
                dados_orcamento = {
                    "numero": numero,
                    "cliente_nome": cliente['nome'],
                    "cliente_id": cliente['id'],
                    "cliente_telefone": cliente.get('telefone', ''),
                    "cliente_endereco": cliente.get('endereco', cliente.get('cidade', '')),
                    "vendedor_id": usuario['id'],
                    "vendedor": usuario['nome'],
                    "forma_pagamento_id": forma_pagamento['id'],
                    "forma_pagamento_nome": forma_pagamento['nome'],
                    "entrada_valor": entrada_valor,
                    "entrada_percentual": round(entrada_valor * 100 / total_final, 2) if total_final else 0,
                    "prazo_entrega_dias": prazo_entrega_dias,
                    "subtotal_itens": subtotal_itens,
                    "gordura_percentual": gordura_percentual,
                    "subtotal_com_gordura": subtotal_com_gordura,
                    "desconto_percentual": desconto_percentual,
                    "desconto_valor": desconto_valor,
                    "parcelas_previstas": [
                        {'etapa': 'Entrada', 'valor': entrada_valor, 'data_prevista': data_orcamento.isoformat()},
                        {'etapa': 'Entrega do material', 'valor': valor_entrega, 'data_prevista': (data_orcamento + timedelta(days=prazo_entrega_dias)).isoformat()},
                    ],
                    "material_nome": nomes_materiais,
                    "material_id": primeiro_item['material_id'],
                    "itens": itens,
                    "quantidade": sum(item['area_m2'] * item.get('quantidade_pecas', 1) for item in itens),
                    "unidade": 'm²',
                    "largura": primeiro_item['comprimento'],
                    "altura": primeiro_item['largura'],
                    "observacoes": valor('observacoes', ''),
                    "valor_total": total_final,
                    "status": orcamento_existente.get('status', 'Em análise') if orcamento_existente else "Em análise",
                    "data": orcamento_existente.get('data', data_orcamento.isoformat()) if orcamento_existente else data_orcamento.isoformat()
                }
                if orcamento_existente:
                    dados_orcamento['revisao'] = int(orcamento_existente.get('revisao', 0)) + 1
                    dados_orcamento['revisado_por'] = usuario['nome']
                    dados_orcamento['revisado_em'] = datetime.now().isoformat(timespec='seconds')
                    orcamento_existente.update(dados_orcamento)
                    registrar_auditoria(usuario, 'revisou orçamento e itens', 'orçamento', numero, f"Revisão {dados_orcamento['revisao']} - {cliente['nome']} - {moeda(total_final)}")
                else:
                    banco_orcamentos.append(dados_orcamento)
                    registrar_auditoria(usuario, 'criou', 'orçamento', numero, f'{cliente["nome"]} - {moeda(total_final)}')

            self.send_response(303)
            self.send_header('Location', '/orcamentos' + (f'?sucesso=1&baixar={numero_novo}' if numero_novo else ''))
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()
        
    if __name__ == '__main__':
        porta = int(os.environ.get('PORT', 5000))
        endereco = ('0.0.0.0', porta)
        servidor = ThreadingHTTPServer(endereco, MeuServidor)
        servidor.daemon_threads = True
        print(f"Sistema online na porta {porta}...")
        servidor.serve_forever()
