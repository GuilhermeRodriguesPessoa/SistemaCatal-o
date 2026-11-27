import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libs'))

import json
import base64
from datetime import datetime
from io import BytesIO

ICONE_PLANO = '<path d="M3 4h18v16H3z"/><path d="M3 10h10M13 4v16M13 14h8"/>'

_HTML = r'''
<style>
  .pc-wrap { display:flex; flex-direction:column; gap:18px; }
  .pc-page-head { display:flex; align-items:center; justify-content:space-between; gap:16px; padding-bottom:14px; border-bottom:1px solid var(--line); }
  .pc-page-head h2 { margin:0; color:var(--ink); font-size:24px; }
  .pc-page-head span { padding:6px 10px; border:1px solid #d5e5dc; border-radius:999px; background:#edf5f0; color:var(--green-dark); font-size:12px; font-weight:700; }
  .pc-tabs { display:flex; gap:6px; padding:4px; border:1px solid var(--line); border-radius:10px; background:#edf2ef; }
  .pc-tabs button { flex:1; width:auto; min-height:42px; padding:9px 16px; border:1px solid transparent; border-radius:7px; background:transparent; color:#52645c; font-weight:650; font-size:13px; transition:all .18s; }
  .pc-tabs button:hover { background:#fff; color:var(--green-dark); }
  .pc-tabs button.on { background:#fff; color:var(--green-dark); border-color:#dbe7e0; box-shadow:0 2px 6px #18352a10; }
  .pc-tab-pane[hidden] { display:none; }

  .pc-editor { display:grid; grid-template-columns:minmax(260px,300px) minmax(360px,1fr) minmax(260px,300px); gap:18px; align-items:start; }
  .pc-card { min-width:0; border:1px solid var(--line); border-radius:10px; background:#fff; padding:18px; box-shadow:0 3px 12px #1d342808; }
  .pc-card h3 { display:flex; justify-content:space-between; align-items:center; gap:10px; margin:0 0 14px; font-size:15px; color:var(--green-dark); border-bottom:1px solid var(--line); padding-bottom:10px; }
  .pc-card h3 small { color:var(--muted); font-size:12px; font-weight:500; }
  
  .pc-viewer-wrap { position:relative; min-width:0; border:1px solid #dce5e0; border-radius:10px; overflow:hidden; box-shadow:0 8px 24px #1d34280d; background:#f4f7f9; }
  #pc-3d { height:clamp(420px, 62vh, 700px); cursor:grab; touch-action:none; }
  #pc-3d:active { cursor:grabbing; }
  .pc-empty-state { position:absolute; inset:0; z-index:4; display:grid; align-content:center; justify-items:center; gap:10px; padding:24px; background:#f4f7f9eF; text-align:center; }
  .pc-empty-state[hidden] { display:none; }
  .pc-empty-state strong { color:var(--ink); font-size:16px; }
  .pc-empty-state span { color:var(--muted); font-size:13px; }
  .pc-empty-state button { width:auto; min-height:40px; margin-top:4px; padding:9px 16px; }
  .pc-viewer-toolbar { position:absolute; top:12px; right:12px; display:flex; gap:6px; z-index:5; background:rgba(255,255,255,0.8); padding:4px; border-radius:8px; backdrop-filter:blur(4px); }
  .pc-viewer-toolbar button { width:auto; min-width:74px; min-height:36px; padding:0 10px; background:#fff; color:var(--ink); border:1px solid var(--line); font-size:12px; font-weight:650; box-shadow:0 2px 4px rgba(0,0,0,0.05); }
  .pc-viewer-toolbar button:hover { background:var(--green-soft); color:var(--green); }
  
  .pc-lista-bancadas { display:flex; flex-direction:column; gap:6px; margin-bottom:12px; max-height:200px; overflow-y:auto; }
  .pc-lista-bancadas .item { display:flex; justify-content:space-between; align-items:center; gap:8px; padding:10px 12px; border:1px solid var(--line); border-radius:8px; background:#f9fbfa; cursor:pointer; transition:all .15s; }
  .pc-lista-bancadas .item:hover { border-color:#c8d6ce; background:#f0f5f2; }
  .pc-lista-bancadas .item.sel { border-color:var(--green); background:var(--green-soft); box-shadow:0 0 0 2px rgba(39,107,88,0.1); }
  .pc-lista-bancadas .item strong { display:block; font-size:13px; color:var(--green-dark); }
  .pc-lista-bancadas .item small { color:var(--muted); font-size:11px; }
  .pc-lista-bancadas .item .btn-rm { width:24px; min-height:24px; padding:0; border-radius:4px; background:#f0dada; color:#9a4c40; font-size:14px; line-height:1; }

  .pc-bloco { border:1px solid var(--line); border-radius:8px; padding:12px; margin-bottom:10px; background:#fff; transition:box-shadow .2s; }
  .pc-bloco:hover { box-shadow:0 4px 12px rgba(0,0,0,0.05); }
  .pc-bloco.aux { background:#fff8f0; border-color:#e8c98f; margin-left:16px; border-left:4px solid #b77936; }
  .pc-bloco-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; gap:8px; }
  .pc-bloco-head strong { font-size:13px; color:var(--green-dark); }
  .pc-bloco.aux .pc-bloco-head strong { color:#8a5a1f; }
  .pc-bloco-actions { display:flex; gap:6px; }
  .pc-bloco-actions button { width:auto; min-height:24px; padding:0 10px; font-size:11px; font-weight:700; border-radius:4px; }

  .pc-campo { margin-bottom:8px; }
  .pc-campo label { display:block; margin-bottom:4px; font-size:11px; font-weight:700; color:#55655f; text-transform:uppercase; letter-spacing:0.5px; }
  .pc-campo input, .pc-campo select { width:100%; min-height:36px; padding:6px 10px; font-size:13px; border:1px solid #d0dcd5; border-radius:6px; }
  .pc-campo input:focus, .pc-campo select:focus { border-color:var(--green); outline:none; box-shadow:0 0 0 3px rgba(39,107,88,0.1); }
  .pc-par { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .pc-par3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
  
  .pc-kpis { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-bottom:14px; }
  .pc-kpi { padding:12px; border:1px solid var(--line); border-radius:10px; background:#f8faf9; text-align:center; }
  .pc-kpi span { display:block; color:var(--muted); font-size:11px; font-weight:600; margin-bottom:4px; }
  .pc-kpi strong { font-size:16px; color:var(--green-dark); }

  .pc-chapa { margin-bottom:12px; }
  .pc-chapa small { display:block; margin-bottom:6px; color:var(--muted); font-size:11px; font-weight:700; text-transform:uppercase; }
  .pc-chapa canvas { display:block; width:100%; border-radius:8px; border:1px solid var(--line); box-shadow:0 2px 8px rgba(0,0,0,0.1); }
  
  .pc-cadastros { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr)); gap:18px; }
  .pc-cadastro-card { border:1px solid var(--line); border-radius:12px; background:#fff; overflow:hidden; box-shadow:0 4px 16px rgba(20,40,30,0.04); }
  .pc-cadastro-card header { padding:16px; background:linear-gradient(135deg,#f4f8f6,#fff); border-bottom:1px solid var(--line); }
  .pc-cadastro-card header h3 { margin:0 0 4px; font-size:16px; color:var(--green-dark); }
  .pc-cadastro-card header small { color:var(--muted); font-size:12px; }
  .pc-cadastro-card .body { padding:16px; max-height:500px; overflow-y:auto; }
  .pc-tag { display:inline-block; padding:4px 8px; border-radius:4px; font-size:11px; font-weight:700; }
  .pc-tag-material { background:#e4f3e9; color:#286845; }
  .pc-tag-forma { background:#fff3e2; color:#91601d; }
  
  .pc-acoes { margin-top:16px; }
  .pc-acoes button { width:100%; min-height:48px; font-size:15px; border-radius:10px; box-shadow:0 4px 12px rgba(39,107,88,0.2); }

  @media (max-width:1300px) { .pc-editor { grid-template-columns:minmax(260px,.85fr) minmax(360px,1.15fr); } .pc-editor > aside:last-child { grid-column:1/-1; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; } .pc-editor > aside:last-child > .pc-card { margin-top:0 !important; } }
  @media (max-width:900px) { .pc-editor { grid-template-columns:1fr; } .pc-editor > aside:last-child { grid-column:auto; grid-template-columns:1fr; } #pc-3d { height:420px; } }
  @media (max-width:600px) { .pc-page-head h2 { font-size:21px; } .pc-tabs button { padding:8px 6px; font-size:12px; } .pc-editor > aside:last-child { display:grid; } #pc-3d { height:360px; } .pc-card { padding:14px; } }
</style>

<div class="pc-wrap">
  <header class="pc-page-head"><h2>Plano de corte</h2><span>Projeto 3D</span></header>
  <div class="pc-tabs">
    <button type="button" class="on" data-tab="editor">Editor do projeto</button>
    <button type="button" data-tab="cadastros">Cadastros e configurações</button>
  </div>

  <section class="pc-tab-pane" id="tab-editor">
    <div class="pc-editor">
      <aside>
        <div class="pc-card">
          <h3>Informações do Projeto</h3>
          <div class="pc-campo">
            <label>Vincular Orçamento</label>
            <select id="sel-orcamento"><option value="">Sem vínculo</option></select>
          </div>
          <div class="pc-campo"><label>Nome do Projeto</label><input type="text" id="proj-nome" value="Novo Projeto"></div>
          <div class="pc-campo"><label>Cliente</label><input type="text" id="proj-cliente" placeholder="Nome do cliente"></div>
        </div>

        <div class="pc-card" style="margin-top:16px">
          <h3>Objetos no Projeto <small id="banc-count">0</small></h3>
          <div class="pc-lista-bancadas" id="lista-bancadas"></div>
          <button type="button" id="btn-nova-bancada" class="secondary" style="width:100%; min-height:40px;">+ Adicionar Novo Objeto</button>
        </div>

        <div class="pc-card" style="margin-top:16px" id="card-itens" hidden>
          <h3>Peças do Objeto <small id="itens-count">0</small></h3>
          <div id="painel-itens"></div>
          
          <div style="background:#f4f7f9; padding:12px; border-radius:8px; margin-top:12px; border:1px dashed #c0d0c8;">
            <label style="display:block; font-size:11px; font-weight:700; color:var(--green-dark); margin-bottom:8px;">Adicionar Peça neste Objeto</label>
            <div style="display:flex; gap:8px;">
              <select id="tipo-novo" style="flex:1; min-height:36px; border-radius:6px; border:1px solid #ccc; padding:0 8px;"></select>
              <button type="button" id="btn-add-item" style="width:auto; min-width:80px; padding:0 16px; font-size:13px;">Adicionar</button>
            </div>
          </div>
        </div>
      </aside>

      <div>
        <div class="pc-viewer-wrap">
          <div id="pc-3d"></div>
          <div class="pc-empty-state" id="pc-empty-state">
            <strong>Projeto vazio</strong>
            <span>Adicione uma bancada para começar</span>
            <button type="button" id="pc-empty-add">+ Adicionar bancada</button>
          </div>
          <div class="pc-viewer-toolbar">
            <button type="button" title="Vista frontal" data-view="front">Frontal</button>
            <button type="button" title="Vista superior" data-view="top">Superior</button>
            <button type="button" title="Vista isométrica" data-view="reset">Isométrica</button>
          </div>
        </div>
        <p style="text-align:center; margin-top:10px; color:var(--muted); font-size:12px;">Arraste para girar · Role para aproximar · As medidas estão em metros (m)</p>
      </div>

      <aside>
        <div class="pc-card" id="card-tampo" hidden>
          <h3>Base / Tampo <small id="tampo-dim">-</small></h3>
          <div id="painel-tampo"></div>
        </div>
        
        <div class="pc-card" style="margin-top:16px" id="card-resumo" hidden>
          <h3>Resumo Financeiro</h3>
          <div class="pc-kpis">
            <div class="pc-kpi"><span>ÁREA TOTAL</span><strong id="k-area">-</strong></div>
            <div class="pc-kpi"><span>CHAPAS</span><strong id="k-chapas">-</strong></div>
            <div class="pc-kpi"><span>APROVEIT.</span><strong id="k-aprov">-</strong></div>
          </div>
          <div class="pc-par">
            <div class="pc-campo"><label>Chapa Comp. (m)</label><input id="pc-cl" type="number" value="3.00" min="0.5" step="0.01"></div>
            <div class="pc-campo"><label>Chapa Larg. (m)</label><input id="pc-ca" type="number" value="1.80" min="0.5" step="0.01"></div>
          </div>
          <div class="pc-par">
            <div class="pc-campo"><label>Venda (R$/m²)</label><input id="pc-pv" type="number" value="0" min="0" step="0.01"></div>
            <div class="pc-campo"><label>Custo (R$/m²)</label><input id="pc-pc" type="number" value="0" min="0" step="0.01"></div>
          </div>
          <div class="pc-par" style="margin-top:10px;">
            <div class="pc-kpi" style="border-color:#e8c98f; background:#fff8f0;"><span>CUSTO PEDRA</span><strong id="k-custo" style="color:#b77936;">-</strong></div>
            <div class="pc-kpi venda" style="border-color:#c0d8cd; background:#f0f7f3;"><span>VENDA</span><strong id="k-venda" style="color:var(--green);">-</strong></div>
          </div>
          <div id="pc-aviso"></div>
          <div id="pc-chapas" style="margin-top:16px"></div>
          <div class="pc-legenda" id="pc-legenda"></div>
        </div>

        <div class="pc-acoes" id="acoes-pdf" hidden>
          <button type="button" id="btn-pdf">📄 Emitir PDF do Projeto</button>
        </div>
      </aside>
    </div>
  </section>

  <section class="pc-tab-pane" id="tab-cadastros" hidden>
    <div class="pc-cadastros" id="cadastros-lista"></div>
  </section>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
(() => {
  const MAT = __MATERIAIS__;
  const ORCAMENTOS = __ORCAMENTOS__;
  const T = 0.02; 
  const $ = id => document.getElementById(id);
  const brl = v => (+v).toLocaleString('pt-BR', { style:'currency', currency:'BRL' });
  const n1 = v => (+v).toLocaleString('pt-BR', { maximumFractionDigits:2, minimumFractionDigits:2 });

  // Tipos agora são flexíveis. A posição será escolhida na hora de adicionar.
  const TIPOS_PADRAO = [
    { key: 'lateral', nome: 'Lateral', altura: 0.80 },
    { key: 'frontao', nome: 'Frontão', altura: 0.10 },
    { key: 'rodobanca', nome: 'Rodobanca', altura: 0.05 },
    { key: 'saia', nome: 'Saia', altura: 0.04 },
    { key: 'fechamento', nome: 'Fechamento', altura: 0.20 },
    { key: 'fogao_lenha', nome: 'Pedra Fogão à Lenha', altura: 0.50 }
  ];

  let seqB = 1, seqI = 1;
  const S = {
    projeto: { nome: 'Novo Projeto', cliente: '', orcamentoNumero: '' },
    config: { cor: '#2b2e2d', cl: 3.00, ca: 1.80, kerf: 0.003, pv: 0, pc: 0 },
    bancadas: [], sel: null,
    tipos: [...TIPOS_PADRAO]
  };

  document.querySelectorAll('.pc-tabs button').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.pc-tabs button').forEach(b => b.classList.toggle('on', b === btn));
      document.querySelectorAll('.pc-tab-pane').forEach(p => p.hidden = p.id !== 'tab-' + btn.dataset.tab);
    };
  });

  // ================= BANCADAS =================
  function bancadaAtual() { return S.bancadas.find(b => b.id === S.sel); }

  function novaBancada() {
    const b = {
      id: seqB++, C: 1.80, P: 0.60, cantos: { fl: 0, fr: 0, bl: 0, br: 0 },
      cubas: [], furos: [], fogaoCut: null, itens: []
    };
    S.bancadas.push(b); S.sel = b.id;
    renderBancadas(); renderTampo(); renderItens(); renderResumo(); montar3D(true);
  }

  function removeBancada(id) {
    S.bancadas = S.bancadas.filter(b => b.id !== id);
    if (S.sel === id) S.sel = S.bancadas.length ? S.bancadas[0].id : null;
    renderBancadas(); renderTampo(); renderItens(); renderResumo(); montar3D(true);
  }

  function selecionarBancada(id) {
    S.sel = id;
    renderBancadas(); renderTampo(); renderItens(); renderResumo(); montar3D(true);
  }

  function renderBancadas() {
    const lista = $('lista-bancadas'); lista.innerHTML = '';
    S.bancadas.forEach((b, i) => {
      const el = document.createElement('div');
      el.className = 'item' + (b.id === S.sel ? ' sel' : '');
      el.dataset.id = b.id;
      el.innerHTML = `<div class="info"><strong>Objeto #${i + 1}</strong><small>${n1(b.C)} x ${n1(b.P)} m · ${b.itens.length} peças</small></div><button type="button" class="btn-rm" title="Excluir objeto">×</button>`;
      el.onclick = e => { if (!e.target.closest('.btn-rm')) selecionarBancada(b.id); };
      el.querySelector('.btn-rm').onclick = () => removeBancada(b.id);
      lista.appendChild(el);
    });
    $('banc-count').textContent = S.bancadas.length;
    $('pc-empty-state').hidden = S.bancadas.length > 0;
    $('vazio') && ($('vazio').style.display = S.bancadas.length ? 'none' : 'flex'); // just in case
    $('card-itens').hidden = !bancadaAtual();
    $('card-tampo').hidden = !bancadaAtual();
    $('card-resumo').hidden = !bancadaAtual();
    $('acoes-pdf').hidden = !S.bancadas.length;
  }

  // ================= SELETOR DE ORÇAMENTO =================
  const selOrc = $('sel-orcamento');
  ORCAMENTOS.forEach(o => {
    const opt = document.createElement('option');
    opt.value = o.numero;
    opt.textContent = `${o.numero} - ${o.cliente_nome}`;
    selOrc.appendChild(opt);
  });
  selOrc.onchange = e => {
    const orc = ORCAMENTOS.find(o => o.numero === e.target.value);
    if (orc) {
      S.projeto.orcamentoNumero = orc.numero;
      S.projeto.cliente = orc.cliente_nome;
      S.projeto.nome = `Projeto - ${orc.cliente_nome}`;
      $('proj-nome').value = S.projeto.nome;
      $('proj-cliente').value = S.projeto.cliente;
    } else {
      S.projeto.orcamentoNumero = '';
    }
  };

  // ================= TAMPO =================
  function renderTampo() {
    const box = $('painel-tampo'); box.innerHTML = '';
    const b = bancadaAtual(); if (!b) return;
    box.innerHTML = `
      <div class="pc-par">
        <div class="pc-campo"><label>Comprimento (m)</label><input type="number" id="tam-C" value="${n1(b.C)}" min="0.4" max="5.0" step="0.01"></div>
        <div class="pc-campo"><label>Profundidade (m)</label><input type="number" id="tam-P" value="${n1(b.P)}" min="0.3" max="1.5" step="0.01"></div>
      </div>
      <details style="margin-top:10px; background:#f9fbfa; padding:8px; border-radius:6px; border:1px solid var(--line);">
        <summary style="cursor:pointer;font-size:11px;font-weight:700;color:var(--muted);">Cantos Arredondados (raio m)</summary>
        <div class="pc-par3" style="margin-top:8px">
          <div class="pc-campo"><label>F. Esq</label><input type="number" id="tam-fl" value="${n1(b.cantos.fl)}" min="0" step="0.01"></div>
          <div class="pc-campo"><label>F. Dir</label><input type="number" id="tam-fr" value="${n1(b.cantos.fr)}" min="0" step="0.01"></div>
          <div class="pc-campo"><label>T. Esq</label><input type="number" id="tam-bl" value="${n1(b.cantos.bl)}" min="0" step="0.01"></div>
          <div class="pc-campo"><label>T. Dir</label><input type="number" id="tam-br" value="${n1(b.cantos.br)}" min="0" step="0.01"></div>
        </div>
      </details>
      <div class="pc-check" style="margin-top:12px;"><input type="checkbox" id="chk-cuba" ${b.cubas.length ? 'checked' : ''}><label for="chk-cuba">Adicionar Cuba Inox</label></div>
      <div id="campos-cuba"></div>
      <div class="pc-check"><input type="checkbox" id="chk-furo" ${b.furos.length ? 'checked' : ''}><label for="chk-furo">Furo para Torneira</label></div>
      <div id="campos-furo"></div>
      <div class="pc-check"><input type="checkbox" id="chk-fogao-cut" ${b.fogaoCut ? 'checked' : ''}><label for="chk-fogao-cut">Recorte para Cooktop</label></div>
      <div id="campos-fogao-cut"></div>
    `;
    $('tam-C').oninput = e => { b.C = +e.target.value || 0.4; atualizarLeve(); };
    $('tam-P').oninput = e => { b.P = +e.target.value || 0.3; atualizarLeve(); };
    ['fl','fr','bl','br'].forEach(k => { const el = $('tam-' + k); if (el) el.oninput = e => { b.cantos[k] = +e.target.value || 0; atualizarLeve(); }; });
    $('chk-cuba').onchange = e => { b.cubas = e.target.checked ? [{x:b.C/2,z:b.P/2,w:0.56,d:0.40}] : []; renderCuba(); atualizarLeve(); };
    $('chk-furo').onchange = e => { b.furos = e.target.checked ? [{x:b.C/4,z:b.P/4,d:0.04}] : []; renderFuros(); atualizarLeve(); };
    $('chk-fogao-cut').onchange = e => { b.fogaoCut = e.target.checked ? {x:b.C/2,z:b.P/2,w:0.60,d:0.40,raio:0.05} : null; renderFogaoCut(); atualizarLeve(); };
    $('tampo-dim').textContent = `${n1(b.C)} × ${n1(b.P)} m`;
    renderCuba(); renderFuros(); renderFogaoCut();
  }

  function renderCuba() {
    const b = bancadaAtual(); if (!b) return;
    const box = $('campos-cuba'); box.innerHTML = '';
    b.cubas.forEach((c, i) => {
      const d = document.createElement('div'); d.className = 'pc-bloco'; d.style.background = '#f4f7f9'; d.style.border = 'none';
      d.innerHTML = `<div class="pc-bloco-head"><strong>Cuba ${i+1}</strong>${b.cubas.length > 1 ? `<button type="button" class="pc-btn-rm" data-i="${i}">×</button>` : ''}</div>
        <div class="pc-par">
          <div class="pc-campo"><label>Pos. X (m)</label><input type="number" data-f="x" data-i="${i}" value="${n1(c.x)}" min="0" step="0.01"></div>
          <div class="pc-campo"><label>Pos. Z (m)</label><input type="number" data-f="z" data-i="${i}" value="${n1(c.z)}" min="0" step="0.01"></div>
          <div class="pc-campo"><label>Largura (m)</label><input type="number" data-f="w" data-i="${i}" value="${n1(c.w)}" min="0.1" step="0.01"></div>
          <div class="pc-campo"><label>Prof. (m)</label><input type="number" data-f="d" data-i="${i}" value="${n1(c.d)}" min="0.1" step="0.01"></div>
        </div>`;
      box.appendChild(d);
    });
    if (b.cubas.length) {
      const add = document.createElement('button'); add.type = 'button'; add.textContent = '+ Cuba';
      add.style.width = '100%'; add.style.marginTop = '6px'; add.style.minHeight = '32px'; add.style.fontSize = '12px';
      add.onclick = () => { b.cubas.push({x:b.C/2,z:b.P/2,w:0.56,d:0.40}); renderCuba(); atualizarLeve(); };
      box.appendChild(add);
    }
    box.querySelectorAll('input[data-f]').forEach(inp => inp.oninput = () => { b.cubas[+inp.dataset.i][inp.dataset.f] = +inp.value || 0; atualizarLeve(); });
    box.querySelectorAll('button[data-i]').forEach(btn => btn.onclick = () => { b.cubas.splice(+btn.dataset.i, 1); renderCuba(); atualizarLeve(); });
  }

  function renderFuros() {
    const b = bancadaAtual(); if (!b) return;
    const box = $('campos-furo'); box.innerHTML = '';
    b.furos.forEach((f, i) => {
      const d = document.createElement('div'); d.className = 'pc-bloco'; d.style.background = '#f4f7f9'; d.style.border = 'none';
      d.innerHTML = `<div class="pc-bloco-head"><strong>Furo ${i+1}</strong><button type="button" class="pc-btn-rm" data-i="${i}">×</button></div>
        <div class="pc-par3">
          <div class="pc-campo"><label>Pos. X</label><input type="number" data-f="x" data-i="${i}" value="${n1(f.x)}" min="0" step="0.01"></div>
          <div class="pc-campo"><label>Pos. Z</label><input type="number" data-f="z" data-i="${i}" value="${n1(f.z)}" min="0" step="0.01"></div>
          <div class="pc-campo"><label>Ø (m)</label><input type="number" data-f="d" data-i="${i}" value="${n1(f.d)}" min="0.02" step="0.01"></div>
        </div>`;
      box.appendChild(d);
    });
    const add = document.createElement('button'); add.type = 'button'; add.textContent = '+ Furo';
    add.style.width = '100%'; add.style.marginTop = '6px'; add.style.minHeight = '32px'; add.style.fontSize = '12px';
    add.onclick = () => { b.furos.push({x:b.C/2,z:0.1,d:0.04}); renderFuros(); atualizarLeve(); };
    box.appendChild(add);
    box.querySelectorAll('input[data-f]').forEach(inp => inp.oninput = () => { b.furos[+inp.dataset.i][inp.dataset.f] = +inp.value || 0; atualizarLeve(); });
    box.querySelectorAll('button[data-i]').forEach(btn => btn.onclick = () => { b.furos.splice(+btn.dataset.i, 1); renderFuros(); atualizarLeve(); });
  }

  function renderFogaoCut() {
    const b = bancadaAtual(); if (!b) return;
    const box = $('campos-fogao-cut'); box.innerHTML = '';
    if (!b.fogaoCut) return;
    const f = b.fogaoCut;
    box.innerHTML = `<div class="pc-par" style="background:#f4f7f9; padding:10px; border-radius:6px;">
      <div class="pc-campo"><label>Pos. X (m)</label><input type="number" id="fc-x" value="${n1(f.x)}" min="0" step="0.01"></div>
      <div class="pc-campo"><label>Pos. Z (m)</label><input type="number" id="fc-z" value="${n1(f.z)}" min="0" step="0.01"></div>
      <div class="pc-campo"><label>Largura (m)</label><input type="number" id="fc-w" value="${n1(f.w)}" min="0.2" step="0.01"></div>
      <div class="pc-campo"><label>Prof. (m)</label><input type="number" id="fc-d" value="${n1(f.d)}" min="0.2" step="0.01"></div>
      <div class="pc-campo"><label>Raio (m)</label><input type="number" id="fc-r" value="${n1(f.raio)}" min="0" step="0.01"></div>
    </div>`;
    ['x','z','w','d','raio'].forEach(k => { const el = $('fc-' + k); if (el) el.oninput = () => { b.fogaoCut[k] = +el.value || 0; atualizarLeve(); }; });
  }

  // ================= ITENS =================
  function renderTipoSelect() {
    const sel = $('tipo-novo'); sel.innerHTML = '';
    S.tipos.forEach(t => {
      sel.add(new Option(t.nome, t.key));
    });
  }

  function addItem(tipoKey) {
    const b = bancadaAtual(); if (!b) return;
    const t = S.tipos.find(x => x.key === tipoKey);
    if (!t) return;
    
    // Ao adicionar, define como 'frente' por padrão, mas o usuário pode mudar no card.
    b.itens.push({ 
      id: seqI++, tipo: t.key, nome: t.nome, lado: 'frente', 
      comprimento: b.C, altura: t.altura, espessura: 0.02, raio: 0, filhos: [] 
    });
    renderItens(); atualizarLeve();
  }

  function removeItem(id) {
    const b = bancadaAtual(); if (!b) return;
    b.itens = b.itens.filter(i => i.id !== id);
    renderItens(); atualizarLeve();
  }

  function addFilho(parentId) {
    const b = bancadaAtual(); if (!b) return;
    const p = b.itens.find(i => i.id === parentId); if (!p) return;
    p.filhos.push({ id: seqI++, tipo: 'aux', nome: 'Detalhe Extra', comprimento: p.comprimento, altura: 0.04, espessura: 0.02, raio: 0 });
    renderItens(); atualizarLeve();
  }

  function removeFilho(pid, fid) {
    const b = bancadaAtual(); if (!b) return;
    const p = b.itens.find(i => i.id === pid); if (!p) return;
    p.filhos = p.filhos.filter(f => f.id !== fid);
    renderItens(); atualizarLeve();
  }

  function renderItens() {
    const b = bancadaAtual(); if (!b) return;
    const box = $('painel-itens'); box.innerHTML = '';
    b.itens.forEach(item => {
      const tName = S.tipos.find(x => x.key === item.tipo)?.nome || item.nome || item.tipo;
      const bloco = document.createElement('div'); bloco.className = 'pc-bloco';
      
      bloco.innerHTML = `
        <div class="pc-bloco-head">
          <strong>${tName}</strong>
          <div class="pc-bloco-actions">
            <button type="button" class="pc-btn-aux" data-act="add-aux" data-id="${item.id}">+ Detalhe</button>
            <button type="button" class="pc-btn-rm" data-act="rm" data-id="${item.id}">×</button>
          </div>
        </div>
        
        <div class="pc-campo" style="margin-bottom:10px;">
          <label>Posição da Peça</label>
          <select data-f="lado" data-id="${item.id}" style="font-weight:bold; color:var(--green-dark);">
            <option value="frente" ${item.lado === 'frente' ? 'selected' : ''}>Frente (Ex: Rodobanca, Saia)</option>
            <option value="fundo" ${item.lado === 'fundo' ? 'selected' : ''}>Fundo (Ex: Frontão)</option>
            <option value="esquerda" ${item.lado === 'esquerda' ? 'selected' : ''}>Lateral Esquerda</option>
            <option value="direita" ${item.lado === 'direita' ? 'selected' : ''}>Lateral Direita</option>
            <option value="flutuante" ${item.lado === 'flutuante' ? 'selected' : ''}>Flutuante (Avulso)</option>
          </select>
        </div>

        <div class="pc-par">
          <div class="pc-campo"><label>Comp. (m)</label><input type="number" data-f="comprimento" data-id="${item.id}" value="${n1(item.comprimento)}" min="0.05" step="0.01"></div>
          <div class="pc-campo"><label>Altura (m)</label><input type="number" data-f="altura" data-id="${item.id}" value="${n1(item.altura)}" min="0.01" step="0.01"></div>
          <div class="pc-campo"><label>Esp. (m)</label><input type="number" data-f="espessura" data-id="${item.id}" value="${n1(item.espessura)}" min="0.01" step="0.01"></div>
          <div class="pc-campo"><label>Raio (m)</label><input type="number" data-f="raio" data-id="${item.id}" value="${n1(item.raio)}" min="0" step="0.01"></div>
        </div>`;

      (item.filhos || []).forEach(filho => {
        const cbox = document.createElement('div'); cbox.className = 'pc-bloco aux';
        cbox.innerHTML = `<div class="pc-bloco-head"><strong>↳ ${filho.nome || 'Detalhe'}</strong><button type="button" class="pc-btn-rm" data-act="rm-aux" data-parent="${item.id}" data-id="${filho.id}">×</button></div>
          <div class="pc-par">
            <div class="pc-campo"><label>Comp. (m)</label><input type="number" data-filho-f="comprimento" data-parent="${item.id}" data-id="${filho.id}" value="${n1(filho.comprimento)}" min="0.05" step="0.01"></div>
            <div class="pc-campo"><label>Altura (m)</label><input type="number" data-filho-f="altura" data-parent="${item.id}" data-id="${filho.id}" value="${n1(filho.altura)}" min="0.01" step="0.01"></div>
            <div class="pc-campo"><label>Esp. (m)</label><input type="number" data-filho-f="espessura" data-parent="${item.id}" data-id="${filho.id}" value="${n1(filho.espessura)}" min="0.01" step="0.01"></div>
            <div class="pc-campo"><label>Raio (m)</label><input type="number" data-filho-f="raio" data-parent="${item.id}" data-id="${filho.id}" value="${n1(filho.raio)}" min="0" step="0.01"></div>
          </div>`;
        bloco.appendChild(cbox);
      });
      box.appendChild(bloco);
    });
    
    box.querySelectorAll('button[data-act="rm"]').forEach(btn => btn.onclick = () => removeItem(+btn.dataset.id));
    box.querySelectorAll('button[data-act="add-aux"]').forEach(btn => btn.onclick = () => addFilho(+btn.dataset.id));
    box.querySelectorAll('button[data-act="rm-aux"]').forEach(btn => btn.onclick = () => removeFilho(+btn.dataset.parent, +btn.dataset.id));
    
    box.querySelectorAll('input[data-f], select[data-f]').forEach(inp => {
      inp.onchange = () => {
        const item = b.itens.find(i => i.id === +inp.dataset.id);
        if (item) { 
          item[inp.dataset.f] = inp.type === 'number' ? (+inp.value || 0) : inp.value; 
          atualizarLeve(); 
        }
      };
    });

    box.querySelectorAll('input[data-filho-f]').forEach(inp => inp.oninput = () => {
      const p = b.itens.find(i => i.id === +inp.dataset.parent); if (!p) return;
      const f = p.filhos.find(x => x.id === +inp.dataset.id);
      if (f) { f[inp.dataset.filhoF] = +inp.value || 0; atualizarLeve(); }
    });
    $('itens-count').textContent = b.itens.length;
  }

  function atualizarLeve() {
    renderResumo(); montar3D(false);
    const b = bancadaAtual();
    if (b) {
      const el = document.querySelector(`.pc-lista-bancadas [data-id="${b.id}"] small`);
      if (el) el.textContent = `${n1(b.C)} x ${n1(b.P)} m · ${b.itens.length} peças`;
    }
  }

  // ================= PLANO DE CORTE =================
  function pecasParaCorte(b) {
    const lista = [{ t: 'tampo', w: b.C, h: b.P, raio: b.cantos }];
    b.itens.forEach(it => {
      lista.push({ t: it.tipo, w: it.comprimento, h: it.altura, raio: it.raio });
      (it.filhos || []).forEach(f => lista.push({ t: 'aux', w: f.comprimento, h: f.altura, raio: f.raio }));
    });
    return lista;
  }

  function encaixar(lista) {
    const cfg = S.config;
    const W = Math.max(cfg.cl, cfg.ca), H = Math.min(cfg.cl, cfg.ca), k = cfg.kerf;
    const ps = lista.map(p => ({ ...p, w: Math.max(p.w, p.h), h: Math.min(p.w, p.h) })).sort((a,b) => b.h - a.h || b.w - a.w);
    const chapas = [], fora = [];
    const colocar = (ch, t, w, h) => {
      const fw = w + k, fh = h + k;
      for (const s of ch.sh) if (fh <= s.h + 1e-6 && s.x + w <= W + 1e-6) { ch.it.push({t,x:s.x,y:s.y,w,h}); s.x += fw; return true; }
      const y = ch.sh.reduce((a,s) => a + s.h, 0);
      if (y + h <= H + 1e-6 && w <= W + 1e-6) { ch.sh.push({y,h:fh,x:fw}); ch.it.push({t,x:0,y,w,h}); return true; }
      return false;
    };
    const tenta = (ch, p) => colocar(ch, p.t, p.w, p.h) || colocar(ch, p.t, p.h, p.w);
    ps.forEach(p => {
      if (chapas.some(ch => tenta(ch, p))) return;
      const nova = { sh:[], it:[] };
      if (tenta(nova, p)) chapas.push(nova); else fora.push(p);
    });
    return { chapas, fora, W, H };
  }

  function renderResumo() {
    const cfg = S.config;
    const todas = S.bancadas.flatMap(b => pecasParaCorte(b));
    const res = encaixar(todas);
    const area = todas.reduce((a,p) => a + p.w * p.h, 0);
    const areaC = res.chapas.length * res.W * res.H;
    $('k-area').textContent = n1(area) + ' m²';
    $('k-chapas').textContent = res.chapas.length;
    $('k-aprov').textContent = areaC ? Math.round(area / areaC * 100) + '%' : '-';
    $('k-custo').textContent = cfg.pc > 0 ? brl(areaC * cfg.pc) : '-';
    $('k-venda').textContent = cfg.pv > 0 ? brl(area * cfg.pv) : '-';
    $('pc-aviso').innerHTML = res.fora.length ? `<div style="background:#f8e8e5; color:#9a4c40; padding:8px; border-radius:6px; font-size:11px; margin-top:10px;">⚠ ${res.fora.length} peça(s) maior(es) que a chapa</div>` : '';
    desenharChapas(res);
  }

  const CORES_ITEM = { tampo:'#276b58', lateral:'#b77936', frontao:'#5b7f95', rodobanca:'#8a6fb0', saia:'#2f8f6b', fechamento:'#c0576b', fogao_lenha:'#7a5c2a', aux:'#d0d0d0' };
  function drawRoundRect(g, x, y, w, h, r) {
    r = Math.min(r, w/2, h/2);
    if (r <= 0) { g.rect(x, y, w, h); return; }
    g.beginPath();
    g.moveTo(x+r,y); g.lineTo(x+w-r,y); g.quadraticCurveTo(x+w,y,x+w,y+r);
    g.lineTo(x+w,y+h-r); g.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
    g.lineTo(x+r,y+h); g.quadraticCurveTo(x,y+h,x,y+h-r);
    g.lineTo(x,y+r); g.quadraticCurveTo(x,y,x+r,y);
    g.closePath();
  }
  function desenharChapas(res) {
    const box = $('pc-chapas'); box.innerHTML = '';
    if (!res.chapas.length) { box.innerHTML = '<p class="muted" style="font-size:12px;text-align:center;padding:8px">Sem peças</p>'; $('pc-legenda').innerHTML = ''; return; }
    const cw = Math.max(200, box.clientWidth || 280), esc = cw / res.W;
    res.chapas.forEach((ch, i) => {
      const wrap = document.createElement('div'); wrap.className = 'pc-chapa';
      wrap.innerHTML = `<small>Chapa ${i + 1} / ${res.chapas.length} (${n1(res.W)} × ${n1(res.H)} m)</small>`;
      const c = document.createElement('canvas'); c.width = cw; c.height = Math.round(res.H * esc);
      const g = c.getContext('2d');
      g.fillStyle = '#2a2f2d'; g.fillRect(0, 0, c.width, c.height);
      for (let n = 0; n < 500; n++) { g.fillStyle = `rgba(255,255,255,${Math.random() * .08})`; g.fillRect(Math.random() * cw, Math.random() * c.height, 2, 2); }
      ch.it.forEach(p => {
        const x = p.x * esc, y = p.y * esc, w = p.w * esc, h = p.h * esc;
        g.fillStyle = CORES_ITEM[p.t] || '#888'; g.globalAlpha = .88; drawRoundRect(g, x, y, w, h, 0); g.fill(); g.globalAlpha = 1;
        g.strokeStyle = '#fff'; g.lineWidth = 1; drawRoundRect(g, x + .5, y + .5, w - 1, h - 1, 0); g.stroke();
        const txt = `${n1(p.w)}×${n1(p.h)}`; g.font = '10px sans-serif'; g.fillStyle = '#fff'; g.textBaseline = 'middle';
        if (g.measureText(txt).width < w - 6 && h > 12) g.fillText(txt, x + 4, y + h/2);
      });
      wrap.appendChild(c); box.appendChild(wrap);
    });
    const unicos = [...new Set(res.chapas.flatMap(c => c.it.map(p => p.t)))];
    $('pc-legenda').innerHTML = unicos.map(t => `<span style="font-size:11px; font-weight:600;"><i style="background:${CORES_ITEM[t] || '#888'}"></i>${t}</span>`).join('');
  }

  // ================= 3D CORE =================
  const host = $('pc-3d');
  let renderer, scene, camera, grupo, grade, az = 0.7, pol = 1.05, dist = 4.0, alvo;
  const texCache = {};

  function material(cor) {
    if (!texCache[cor]) {
      const c = document.createElement('canvas'); c.width = c.height = 256;
      const g = c.getContext('2d'); g.fillStyle = cor; g.fillRect(0, 0, 256, 256);
      for (let i = 0; i < 2600; i++) {
        g.fillStyle = Math.random() > .5 ? `rgba(255,255,255,${Math.random() * .22})` : `rgba(0,0,0,${Math.random() * .25})`;
        g.fillRect(Math.random() * 256, Math.random() * 256, 1 + Math.random() * 2, 1 + Math.random() * 2);
      }
      texCache[cor] = new THREE.MeshStandardMaterial({ map: new THREE.CanvasTexture(c), roughness: .35, metalness: .08 });
    }
    return texCache[cor];
  }

  // --- Linhas de Cota 3D (Estilo Técnico) ---
  function criarCota3D(p1, p2, texto, offsetDir) {
    const group = new THREE.Group();
    const mat = new THREE.LineBasicMaterial({ color: 0x111111, linewidth: 2 });
    const arrowMat = new THREE.MeshBasicMaterial({ color: 0x111111 });

    // Aplica offset
    if (offsetDir) {
      p1.add(offsetDir);
      p2.add(offsetDir);
    }

    // Linha principal
    const points = [p1, p2];
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    group.add(new THREE.Line(geo, mat));

    // Setas (Cones)
    const dir = new THREE.Vector3().subVectors(p2, p1).normalize();
    const dist = p1.distanceTo(p2);
    
    if (dist > 0.05) {
      const arrowLen = 0.03;
      const arrowRad = 0.01;
      
      // Seta 1 (apontando de p2 para p1)
      const cone1 = new THREE.Mesh(new THREE.ConeGeometry(arrowRad, arrowLen, 8), arrowMat);
      cone1.position.copy(p1).addScaledVector(dir, arrowLen/2);
      cone1.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), dir);
      group.add(cone1);

      // Seta 2 (apontando de p1 para p2)
      const cone2 = new THREE.Mesh(new THREE.ConeGeometry(arrowRad, arrowLen, 8), arrowMat);
      cone2.position.copy(p2).addScaledVector(dir, -arrowLen/2);
      cone2.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), dir.clone().negate());
      group.add(cone2);
    }

    // Texto (Sprite)
    const c = document.createElement('canvas'); c.width = 256; c.height = 64;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, 256, 64);
    ctx.strokeStyle = '#111111'; ctx.lineWidth = 2; ctx.strokeRect(0,0,256,64);
    ctx.font = 'bold 32px sans-serif'; ctx.fillStyle = '#111111'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(texto, 128, 34);
    const tex = new THREE.CanvasTexture(c);
    const sprMat = new THREE.SpriteMaterial({ map: tex, depthTest: false });
    const sprite = new THREE.Sprite(sprMat);
    
    const mid = new THREE.Vector3().lerpVectors(p1, p2, 0.5);
    sprite.position.copy(mid);
    sprite.scale.set(0.25, 0.0625, 1);
    group.add(sprite);

    return group;
  }

  function criarCooktop(w, d) {
    const g = new THREE.Group();
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x1a1a1a, metalness: 0.8, roughness: 0.3 });
    const burnerMat = new THREE.MeshStandardMaterial({ color: 0x050505, roughness: 0.9 });
    const grateMat = new THREE.MeshStandardMaterial({ color: 0x606060, metalness: 0.9, roughness: 0.2 });
    const frame = new THREE.Mesh(new THREE.BoxGeometry(w, 0.012, d), frameMat); frame.position.y = 0.006; g.add(frame);
    const r = Math.min(w, d) * 0.09, bx = w/4, bz = d/4;
    [[-bx,-bz],[bx,-bz],[-bx,bz],[bx,bz]].forEach(([x,z]) => {
      const burner = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.004, 24), burnerMat);
      burner.position.set(x, 0.014, z); g.add(burner);
      for (let a = 0; a < 4; a++) {
        const ang = a * Math.PI / 4;
        const grate = new THREE.Mesh(new THREE.BoxGeometry(r * 2.2, 0.0012, 0.0035), grateMat);
        grate.position.set(x + Math.cos(ang) * r * 0.4, 0.016, z + Math.sin(ang) * r * 0.4);
        grate.rotation.y = -ang; g.add(grate);
      }
    });
    return g;
  }

  function criarCubaInox(w, d) {
    const g = new THREE.Group();
    const steel = new THREE.MeshStandardMaterial({ color: 0xc0c7cc, metalness: 0.9, roughness: 0.15 });
    const inner = new THREE.MeshStandardMaterial({ color: 0x7d858b, metalness: 0.85, roughness: 0.35 });
    const dark = new THREE.MeshStandardMaterial({ color: 0x1a1a1a, metalness: 0.5 });
    const rim = new THREE.Mesh(new THREE.BoxGeometry(w, 0.004, d), steel); rim.position.y = 0.002; g.add(rim);
    const basin = new THREE.Mesh(new THREE.BoxGeometry(w - 0.04, 0.006, d - 0.04), inner); basin.position.y = 0.0035; g.add(basin);
    const drain = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.008, 16), dark); drain.position.y = 0.005; g.add(drain);
    return g;
  }

  function init3D() {
    if (!window.THREE) { host.innerHTML = '<p style="color:#333;padding:20px">Three.js não carregou.</p>'; return; }
    renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0xf4f7f9, 1);
    host.appendChild(renderer.domElement);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf4f7f9);
    
    // Luzes mais suaves e realistas
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const dir = new THREE.DirectionalLight(0xffffff, 0.8); dir.position.set(2, 4, 3); scene.add(dir);
    const dir2 = new THREE.DirectionalLight(0xffffff, 0.4); dir2.position.set(-2, 2, -3); scene.add(dir2);
    const fill = new THREE.DirectionalLight(0xffffff, 0.2); fill.position.set(0, -2, 4); scene.add(fill);
    
    grade = new THREE.GridHelper(20, 40, 0xc0d0c8, 0xe0e8e4);
    grade.material.opacity = 0.6; grade.material.transparent = true; grade.position.y = -0.30; scene.add(grade);
    
    camera = new THREE.PerspectiveCamera(35, 1, 0.1, 50);
    alvo = new THREE.Vector3(0, 0, 0);
    let arrasta = false, ux = 0, uy = 0;
    host.addEventListener('pointerdown', e => { arrasta = true; ux = e.clientX; uy = e.clientY; host.setPointerCapture(e.pointerId); });
    host.addEventListener('pointerup', () => arrasta = false);
    host.addEventListener('pointermove', e => {
      if (!arrasta) return;
      az -= (e.clientX - ux) * .008; pol = Math.min(1.5, Math.max(.15, pol - (e.clientY - uy) * .008));
      ux = e.clientX; uy = e.clientY; render3D();
    });
    host.addEventListener('wheel', e => { e.preventDefault(); dist = Math.min(20, Math.max(0.8, dist * (1 + e.deltaY * .001))); render3D(); }, { passive: false });
    
    document.querySelectorAll('.pc-viewer-toolbar button').forEach(btn => btn.onclick = () => {
      const v = btn.dataset.view;
      if (v === 'front') { az = 0; pol = 1.4; }
      else if (v === 'top') { az = 0; pol = 0.15; }
      else { az = 0.7; pol = 1.05; montar3D(true); return; }
      render3D();
    });
    new ResizeObserver(redim).observe(host); redim();
  }
  
  function redim() {
    if (!renderer) return;
    renderer.setSize(host.clientWidth, host.clientHeight);
    camera.aspect = host.clientWidth / host.clientHeight; camera.updateProjectionMatrix(); render3D();
  }
  
  function render3D() {
    if (!renderer) return;
    camera.position.set(
      alvo.x + dist * Math.sin(pol) * Math.sin(az),
      alvo.y + dist * Math.cos(pol),
      alvo.z + dist * Math.sin(pol) * Math.cos(az)
    );
    camera.lookAt(alvo);
    renderer.render(scene, camera);
  }

  function montar3D(reenquadrar) {
    if (!renderer) return;
    if (grupo) {
      scene.remove(grupo);
      grupo.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material && o.material.map) o.material.map.dispose(); });
    }
    grupo = new THREE.Group(); scene.add(grupo);
    if (!S.bancadas.length) { render3D(); return; }
    
    const mat = material(S.config.cor);
    let totalW = 0; const pos = [];
    S.bancadas.forEach(b => { pos.push(totalW + b.C/2); totalW += b.C + 0.4; });
    totalW -= 0.4; pos.forEach((p, i) => pos[i] = p - totalW/2);
    
    S.bancadas.forEach((b, idx) => montarBancada(b, pos[idx], mat));
    
    const bb = new THREE.Box3().setFromObject(grupo);
    const centro = bb.getCenter(new THREE.Vector3());
    alvo.copy(centro);
    grade.position.y = bb.min.y - 0.02; 

    if (reenquadrar) dist = Math.max(bb.getSize(new THREE.Vector3()).length() * 1.6, 1.8);
    render3D();
  }

  function montarBancada(b, px, mat) {
    const C = b.C, P = b.P;
    let tampo;
    
    if (b.cantos.fl + b.cantos.fr + b.cantos.bl + b.cantos.br > 0) {
      const sh = new THREE.Shape(); const C2 = C/2, P2 = P/2;
      const rfl = b.cantos.fl, rfr = b.cantos.fr, rbl = b.cantos.bl, rbr = b.cantos.br;
      sh.moveTo(-C2 + rfl, -P2); sh.lineTo(C2 - rfr, -P2);
      if (rfr > 0) sh.quadraticCurveTo(C2, -P2, C2, -P2 + rfr);
      sh.lineTo(C2, P2 - rbr);
      if (rbr > 0) sh.quadraticCurveTo(C2, P2, C2 - rbr, P2);
      sh.lineTo(-C2 + rbl, P2);
      if (rbl > 0) sh.quadraticCurveTo(-C2, P2, -C2, P2 - rbl);
      sh.lineTo(-C2, -P2 + rfl);
      if (rfl > 0) sh.quadraticCurveTo(-C2, -P2, -C2 + rfl, -P2);
      const geo = new THREE.ExtrudeGeometry(sh, { depth: T, bevelEnabled: false });
      geo.rotateX(-Math.PI/2); tampo = new THREE.Mesh(geo, mat);
    } else {
      tampo = new THREE.Mesh(new THREE.BoxGeometry(C, T, P), mat); tampo.position.y = T/2;
    }
    tampo.position.x = px; grupo.add(tampo);

    // --- COTAS DO TAMPO ---
    const offsetCota = 0.15;
    // Cota de Comprimento (frente)
    grupo.add(criarCota3D(
      new THREE.Vector3(px - C/2, 0, P/2 + offsetCota), 
      new THREE.Vector3(px + C/2, 0, P/2 + offsetCota), 
      `${n1(C)} m`
    ));
    // Cota de Profundidade (direita)
    grupo.add(criarCota3D(
      new THREE.Vector3(px + C/2 + offsetCota, 0, -P/2), 
      new THREE.Vector3(px + C/2 + offsetCota, 0, P/2), 
      `${n1(P)} m`
    ));
    
    b.cubas.forEach(c => {
      const g = criarCubaInox(c.w, c.d);
      g.position.set(px - C/2 + c.x, T + 0.001, -P/2 + c.z);
      grupo.add(g);
    });
    b.furos.forEach(f => {
      const m = new THREE.MeshStandardMaterial({ color: 0x0a0a0a });
      const mesh = new THREE.Mesh(new THREE.CylinderGeometry(f.d/2, f.d/2, T + 0.015, 24), m);
      mesh.position.set(px - C/2 + f.x, T/2, -P/2 + f.z);
      grupo.add(mesh);
    });
    if (b.fogaoCut) {
      const f = b.fogaoCut;
      const g = criarCooktop(f.w, f.d);
      g.position.set(px - C/2 + f.x, T + 0.001, -P/2 + f.z);
      grupo.add(g);
    }
    
    b.itens.forEach(item => {
      montarItem(item, b, px, mat);
      (item.filhos || []).forEach(f => montarFilho(item, f, b, px));
    });
  }

  function montarItem(item, b, px, mat) {
    const C = b.C, P = b.P, esp = item.espessura, h = item.altura, L = item.comprimento;
    let w, hh, d, x, y, z;
    
    if (item.lado === 'frente') { w = L; hh = h; d = esp; x = px; z = P/2 - esp/2; y = item.acima ? T + h/2 : -h/2; }
    else if (item.lado === 'fundo') { w = L; hh = h; d = esp; x = px; z = -P/2 + esp/2; y = item.acima ? T + h/2 : -h/2; }
    else if (item.lado === 'esquerda') { w = esp; hh = h; d = L; x = px - C/2 + esp/2; z = -P/2 + L/2; y = item.acima ? T + h/2 : -h/2; }
    else if (item.lado === 'direita') { w = esp; hh = h; d = L; x = px + C/2 - esp/2; z = -P/2 + L/2; y = item.acima ? T + h/2 : -h/2; }
    else if (item.lado === 'flutuante') {
      const geo = new THREE.BoxGeometry(L, T, h);
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(px + C/2 + 0.4 + L/2, T/2, 0);
      grupo.add(mesh); return;
    } else return;
    
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, hh, d), mat);
    mesh.position.set(x, y, z); grupo.add(mesh);

    // --- COTA DA ALTURA DA PEÇA ---
    if (h > 0.05) {
      const offset = 0.15;
      if (item.lado === 'frente') grupo.add(criarCota3D(new THREE.Vector3(x - w/2 - offset, y - h/2, z), new THREE.Vector3(x - w/2 - offset, y + h/2, z), `${n1(h)} m`));
      else if (item.lado === 'fundo') grupo.add(criarCota3D(new THREE.Vector3(x - w/2 - offset, y - h/2, z), new THREE.Vector3(x - w/2 - offset, y + h/2, z), `${n1(h)} m`));
      else if (item.lado === 'esquerda') grupo.add(criarCota3D(new THREE.Vector3(x - w/2 - offset, y - h/2, z + d/2), new THREE.Vector3(x - w/2 - offset, y + h/2, z + d/2), `${n1(h)} m`));
      else if (item.lado === 'direita') grupo.add(criarCota3D(new THREE.Vector3(x + w/2 + offset, y - h/2, z + d/2), new THREE.Vector3(x + w/2 + offset, y + h/2, z + d/2), `${n1(h)} m`));
    }
  }

  function montarFilho(parent, filho, b, px) {
    const matAux = new THREE.MeshStandardMaterial({ color: 0xb77936, roughness: 0.55, metalness: 0.1 });
    const esp = filho.espessura, h = filho.altura, L = filho.comprimento;
    const C = b.C, P = b.P;
    let pX, pY, pZ;
    
    if (parent.lado === 'esquerda') { pX = px - C/2 + parent.espessura/2; pY = parent.acima ? T + parent.altura/2 : -parent.altura/2; pZ = -P/2 + parent.comprimento/2; }
    else if (parent.lado === 'direita') { pX = px + C/2 - parent.espessura/2; pY = parent.acima ? T + parent.altura/2 : -parent.altura/2; pZ = -P/2 + parent.comprimento/2; }
    else if (parent.lado === 'frente') { pX = px; pY = parent.acima ? T + parent.altura/2 : -parent.altura/2; pZ = P/2 - parent.espessura/2; }
    else if (parent.lado === 'fundo') { pX = px; pY = parent.acima ? T + parent.altura/2 : -parent.altura/2; pZ = -P/2 + parent.espessura/2; }
    else return;
    
    const bottom = pY - parent.altura/2;
    const isVert = parent.lado === 'esquerda' || parent.lado === 'direita';
    const cw = isVert ? esp : L;
    const cd = isVert ? L : esp;
    
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(cw, h, cd), matAux);
    mesh.position.set(pX, bottom - h/2, pZ);
    grupo.add(mesh);
  }

  // ================= CADASTROS =================
  function renderCadastros() {
    const lista = $('cadastros-lista');
    lista.innerHTML = `
      <div class="pc-cadastro-card">
        <header><h3>Materiais</h3><small>Pedras cadastradas no sistema</small></header>
        <div class="body">
          <table style="width:100%; border-collapse:collapse;">
            <thead><tr style="border-bottom:1px solid #eee; text-align:left;"><th style="padding:8px;">Material</th><th style="padding:8px;">Preço</th></tr></thead>
            <tbody>
              ${MAT.map(m => `<tr style="border-bottom:1px solid #f9f9f9;"><td style="padding:8px;"><span class="pc-tag pc-tag-material">${m.nome}</span></td><td style="padding:8px; font-weight:600;">${brl(m.preco)}/m²</td></tr>`).join('') || '<tr><td colspan="2" class="muted">Nenhum material.</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
      
      <div class="pc-cadastro-card">
        <header><h3>Tipos de Peças</h3><small>Cadastre apenas o nome e a altura. Você escolhe o lado na hora de montar.</small></header>
        <div class="body">
          <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
            <thead><tr style="border-bottom:1px solid #eee; text-align:left;"><th style="padding:8px;">Nome</th><th style="padding:8px;">Altura Padrão</th><th style="padding:8px; text-align:center;">Ações</th></tr></thead>
            <tbody id="lista-tipos">
              ${S.tipos.map((t, i) => `
                <tr style="border-bottom:1px solid #f9f9f9;">
                  <td style="padding:8px;"><span class="pc-tag pc-tag-forma">${t.nome}</span></td>
                  <td style="padding:8px;">${n1(t.altura)} m</td>
                  <td style="padding:8px; text-align:center;"><button type="button" class="pc-btn-rm" onclick="removeTipo(${i})" style="width:24px; height:24px; padding:0; line-height:1;">×</button></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
          
          <form onsubmit="event.preventDefault(); addTipo();" style="display:grid; gap:12px; padding:16px; background:#f8faf9; border-radius:10px; border:1px solid #e0e8e4;">
            <h4 style="margin:0;font-size:14px; color:var(--green-dark);">Cadastrar Novo Tipo de Peça</h4>
            <div class="pc-par">
              <div class="pc-campo"><label>Nome da Peça</label><input type="text" id="nt-nome" required placeholder="Ex: Rodobanca, Saia..."></div>
              <div class="pc-campo"><label>Altura Padrão (m)</label><input type="number" id="nt-altura" value="0.05" min="0.01" step="0.01" required></div>
            </div>
            <button type="submit" style="min-height:38px; font-size:13px;">+ Adicionar à Lista</button>
          </form>
        </div>
      </div>
    `;
  }

  window.addTipo = () => {
    const nome = document.getElementById('nt-nome').value.trim();
    const altura = parseFloat(document.getElementById('nt-altura').value) || 0.10;
    if (!nome) return;
    const key = 'custom_' + Date.now();
    S.tipos.push({ key, nome, altura });
    renderTipoSelect();
    renderCadastros();
  };

  window.removeTipo = (idx) => {
    S.tipos.splice(idx, 1);
    renderTipoSelect();
    renderCadastros();
  };

  // ================= EVENTS =================
  $('btn-nova-bancada').onclick = novaBancada;
  $('pc-empty-add').onclick = novaBancada;
  $('btn-add-item').onclick = () => addItem($('tipo-novo').value);
  $('proj-nome').oninput = e => { S.projeto.nome = e.target.value; };
  $('proj-cliente').oninput = e => { S.projeto.cliente = e.target.value; };
  ['cl','ca','pv','pc'].forEach(k => { const el = $('pc-' + k); if (el) el.oninput = e => { S.config[k] = +e.target.value || 0; renderResumo(); }; });

  $('btn-pdf').onclick = async () => {
    let imgData = '';
    if (renderer && renderer.domElement) {
      imgData = renderer.domElement.toDataURL('image/png');
    }
    const projetoData = { 
      nome: S.projeto.nome, 
      cliente: S.projeto.cliente, 
      orcamento: S.projeto.orcamentoNumero, 
      bancadas: S.bancadas, 
      config: S.config,
      imagem: imgData
    };
    
    const body = 'projeto=' + encodeURIComponent(JSON.stringify(projetoData));
    try {
      const resp = await fetch('/plano_pdf', { method:'POST', headers:{ 'Content-Type':'application/x-www-form-urlencoded' }, body });
      if (!resp.ok) { 
        const txt = await resp.text();
        alert('Erro ao gerar PDF: ' + resp.status + '\n' + txt); 
        return; 
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = 'plano_corte.pdf'; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { alert('Erro: ' + e.message); }
  };

  // ================= INIT =================
  renderTipoSelect();
  renderBancadas(); renderResumo(); renderCadastros(); init3D(); montar3D(true);
})();
</script>
'''


def gerar_pdf_plano(projeto, caminho, logo_path=None):
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, Image
        TEM_PILLOW = True
    except ImportError:
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.lib.utils import ImageReader
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
            TEM_PILLOW = False
        except ImportError:
            return _pdf_plano_nativo(projeto, caminho)

    largura_pagina, altura_pagina = A4
    margem = 35
    largura_tabela = largura_pagina - margem * 2
    azul_escuro = colors.HexColor('#101a2b')
    azul_total = colors.HexColor('#d8eaf5')
    cinza_linha = colors.HexColor('#9da7b1')
    cinza_claro = colors.HexColor('#f5f7f9')
    p_styles = getSampleStyleSheet()
    
    texto = ParagraphStyle('TextoOrcamento', parent=p_styles['BodyText'], fontName='Helvetica', fontSize=8.5, leading=11, textColor=colors.black, spaceAfter=0)
    texto_centro = ParagraphStyle('TextoCentro', parent=texto, alignment=TA_CENTER)
    texto_direita = ParagraphStyle('TextoDireita', parent=texto, alignment=TA_RIGHT)
    valor_negrito = ParagraphStyle('ValorNegrito', parent=texto_direita, fontName='Helvetica-Bold', fontSize=9.5)
    titulo_secao = ParagraphStyle('TituloSecao', parent=texto_centro, fontName='Helvetica-Bold', fontSize=8.5, leading=10, textColor=colors.white)
    texto_condicao = ParagraphStyle('TextoCondicao', parent=texto, fontSize=7.6, leading=9.2)
    texto_assinatura = ParagraphStyle('TextoAssinatura', parent=texto_centro, fontName='Helvetica-Bold', fontSize=9)

    def paragrafo(valor, estilo=texto):
        return Paragraph(str(valor or '-').replace('\n', '<br/>'), estilo)

    def desenhar_cabecalho(can, doc):
        can.saveState()
        x = margem
        topo = altura_pagina - 28
        can.setStrokeColor(azul_escuro)
        can.setLineWidth(1)
        
        if logo_path and os.path.isfile(logo_path):
            try:
                # Logo aumentado (200x55)
                can.drawImage(ImageReader(logo_path), x, topo - 56, width=200, height=55, preserveAspectRatio=True, anchor='sw', mask='auto')
            except Exception:
                pass
        else:
            can.rect(x, topo - 31, largura_tabela, 31, stroke=1, fill=0)
            can.setStrokeColor(colors.HexColor('#d9ae32'))
            can.setLineWidth(2.5)
            simbolo_x = largura_pagina / 2 - 27
            for deslocamento in range(4):
                can.line(simbolo_x + deslocamento * 7, topo - 23, simbolo_x + 13 + deslocamento * 7, topo - 5)

        can.setFillColor(azul_escuro)
        can.rect(x, topo - 65, largura_tabela, 15, stroke=1, fill=1)
        can.setFillColor(colors.white)
        can.setFont('Helvetica-Bold', 9)
        can.drawCentredString(largura_pagina / 2, topo - 61, 'PLANO DE CORTE — PROJETO')
        
        can.setFillColor(colors.black)
        can.setFont('Helvetica', 7)
        can.drawRightString(largura_pagina - margem, 18, f'Página {doc.page}')
        can.restoreState()

    story = [Spacer(1, 4 * mm)]
    
    dados_cliente = [
        ['Projeto:', paragrafo(projeto.get('nome'), texto), 'Vínculo:', paragrafo(projeto.get('orcamento') or 'Sem vínculo', texto)],
        ['Cliente:', paragrafo(projeto.get('cliente'), texto), 'Data:', paragrafo(datetime.now().strftime('%d/%m/%Y'), texto)]
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
    story.extend([tabela_cliente, Spacer(1, 4 * mm)])

    img_data = projeto.get('imagem')
    if img_data and ',' in img_data and TEM_PILLOW:
        try:
            img_bytes = base64.b64decode(img_data.split(',')[1])
            img = Image(BytesIO(img_bytes))
            aspect = img.imageHeight / float(img.imageWidth)
            img.drawWidth = 480
            img.drawHeight = 480 * aspect
            img.hAlign = 'CENTER'
            story.append(img)
            story.append(Spacer(1, 4 * mm))
        except Exception:
            pass

    linhas_itens = [[
        paragrafo('OBJ.', titulo_secao),
        paragrafo('PEÇA / DESCRIÇÃO', titulo_secao),
        paragrafo('MEDIDAS (M)', titulo_secao),
        paragrafo('ÁREA (M²)', titulo_secao),
    ]]
    
    total_area = 0.0
    for i, b in enumerate(projeto.get('bancadas') or []):
        C = float(b.get('C') or 0)
        P = float(b.get('P') or 0)
        area_t = C * P
        total_area += area_t
        linhas_itens.append([
            paragrafo(f"#{i+1}", texto_centro),
            paragrafo('<b>Base / Tampo</b>', texto),
            paragrafo(f"{C:.2f} × {P:.2f}", texto_centro),
            paragrafo(f"{area_t:.2f}", texto_centro),
        ])
        
        for item in b.get('itens') or []:
            comp = float(item.get('comprimento') or 0)
            alt = float(item.get('altura') or 0)
            area = comp * alt
            total_area += area
            lado = item.get('lado', '')
            nome_completo = f"{item.get('nome', item.get('tipo'))} ({lado.capitalize()})"
            linhas_itens.append([
                paragrafo(f"#{i+1}", texto_centro),
                paragrafo(nome_completo),
                paragrafo(f"{comp:.2f} × {alt:.2f}", texto_centro),
                paragrafo(f"{area:.2f}", texto_centro),
            ])
            
            for filho in item.get('filhos') or []:
                comp_f = float(filho.get('comprimento') or 0)
                alt_f = float(filho.get('altura') or 0)
                area_f = comp_f * alt_f
                total_area += area_f
                linhas_itens.append([
                    paragrafo(f"#{i+1}", texto_centro),
                    paragrafo(f"&nbsp;&nbsp;&nbsp;↳ {filho.get('nome', 'Detalhe')}", texto),
                    paragrafo(f"{comp_f:.2f} × {alt_f:.2f}", texto_centro),
                    paragrafo(f"{area_f:.2f}", texto_centro),
                ])

    tabela_itens = Table(linhas_itens, colWidths=[40, 250, 100, largura_tabela - 390], repeatRows=1, hAlign='LEFT')
    tabela_itens.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), azul_escuro),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.6, cinza_linha),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.extend([tabela_itens, Spacer(1, 4 * mm)])

    linhas_totais = [
        ['', '', paragrafo('<b>ÁREA TOTAL:</b>', texto_direita), paragrafo(f"{total_area:.2f} m²", valor_negrito)]
    ]
    total_table = Table(linhas_totais, colWidths=[40, 250, 100, largura_tabela - 390])
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (2, -1), azul_total),
        ('BACKGROUND', (3, 0), (3, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.7, azul_escuro),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('RIGHTPADDING', (2, 0), (2, -1), 16),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.extend([total_table, Spacer(1, 7 * mm)])

    def secao(texto_secao, linhas_secao):
        tabela = Table([[paragrafo(texto_secao, titulo_secao)]] + [[paragrafo(linha, texto_condicao)] for linha in linhas_secao], colWidths=[largura_tabela])
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
        secao('OBSERVAÇÕES E CONDIÇÕES', [
            '1 - As medidas e quantidades descritas neste plano são baseadas no projeto visual 3D e podem sofrer ajustes após medição local.',
            '2 - A conferência das peças deve ser feita no ato da entrega.',
            '3 - Frete por conta do cliente; não incluso no valor.',
        ]),
        Spacer(1, 9 * mm),
        paragrafo('Confirmo que li as informações acima e concordo com a execução do serviço.', texto_centro),
        Spacer(1, 17 * mm),
        Table([[paragrafo('CLIENTE: __________________________________________', texto_assinatura), paragrafo('CATALÃO MÁRMORES E GRANITOS<br/>CNPJ: 10.446.296/0001-22', texto_assinatura)]], colWidths=[largura_tabela / 2] * 2, style=TableStyle([
            ('LINEABOVE', (0, 0), (-1, -1), 0.7, azul_escuro),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
        ])),
    ])

    documento = SimpleDocTemplate(
        caminho,
        pagesize=A4,
        leftMargin=margem,
        rightMargin=margem,
        topMargin=altura_pagina - (altura_pagina - 28 - 65) + 12,
        bottomMargin=32,
        title=f"Plano de Corte {projeto.get('nome')}",
        author='Catalão Mármores e Granitos Ltda',
    )
    documento.build(story, onFirstPage=desenhar_cabecalho, onLaterPages=desenhar_cabecalho)
    return caminho

def _pdf_plano_nativo(projeto, caminho):
    # Mantido apenas como backup, mas o reportlab já está resolvendo.
    return caminho

def conteudo_plano_corte(materiais, orcamentos=None):
    lista_mat = [
        {'nome': m.get('nome', 'Material'), 'preco': float(m.get('preco_unitario', 0) or 0)}
        for m in materiais
        if m.get('ativo', True) and m.get('unidade', 'm²') == 'm²'
    ]
    lista_orc = [
        {'numero': o.get('numero', ''), 'cliente_nome': o.get('cliente_nome', '')}
        for o in (orcamentos or [])
        if o.get('ativo', True) and o.get('status') in ('Em análise', 'Aprovado', 'Em produção')
    ]
    dados_mat = json.dumps(lista_mat, ensure_ascii=False).replace('</', '<\\/')
    dados_orc = json.dumps(lista_orc, ensure_ascii=False).replace('</', '<\\/')
    
    html = _HTML.replace('__MATERIAIS__', dados_mat)
    return html.replace('__ORCAMENTOS__', dados_orc)